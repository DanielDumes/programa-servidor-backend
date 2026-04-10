from flask import Blueprint, jsonify, request, Response
from datetime import datetime, timezone
from db import get_servers_col, get_status_actual
from ilo import ilo_get, handle_errors, ilo_login
from crypto import encrypt, decrypt, is_encrypted
from monitor import poll_server, sync_server_to_db

bp = Blueprint("servers", __name__)


def _pub(doc):
    """
    Devuelve campos públicos del servidor.
    Descifra el usuario para mostrarlo en la UI, pero NUNCA devuelve la contraseña.
    """
    user = doc.get("user", "")
    if user and is_encrypted(user):
        user = decrypt(user)
    return {
        "id":    doc["id"],
        "label": doc["label"],
        "host":  doc["host"],
        "user":  user,
    }


def _get_creds(doc):
    """Devuelve (host, user, pass) descifrados para conectarse al iLO."""
    user   = doc.get("user", "")
    passwd = doc.get("pass", "")
    if user   and is_encrypted(user):   user   = decrypt(user)
    if passwd and is_encrypted(passwd): passwd = decrypt(passwd)
    return doc["host"], user, passwd


def _next_id(col):
    last = col.find_one({}, {"id": 1}, sort=[("id", -1)])
    return (last["id"] + 1) if last else 1


# ── GET /api/servers ──────────────────────────────────────────────
@bp.get("/api/servers")
def get_servers():
    col  = get_servers_col()
    docs = list(col.find({}, {"_id": 0}).sort("id", 1))
    return jsonify([_pub(s) for s in docs])


# ── GET /api/servers/status ───────────────────────────────────────
@bp.get("/api/servers/status")
def get_fleet_status():
    """Retorna el último estado conocido de todos los servidores (desde cache/mongo)."""
    try:
        from db import get_status_actual
        col = get_status_actual()
        docs = list(col.find({}, {"_id": 0}).sort("server_id", 1))
        
        # Serializar fechas
        for d in docs:
            if "timestamp" in d and isinstance(d["timestamp"], datetime):
                d["timestamp"] = d["timestamp"].isoformat()
                
        return jsonify(docs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── POST /api/servers ─────────────────────────────────────────────
@bp.post("/api/servers")
@handle_errors
def add_server():
    body   = request.json or {}
    host   = body.get("host", "").strip()
    user   = body.get("user", "").strip()
    passwd = body.get("pass", "").strip()
    label  = body.get("label", host).strip()

    if not host or not user or not passwd:
        return jsonify({"error": "host, user y pass son requeridos"}), 400

    col = get_servers_col()

    if col.find_one({"host": host}):
        return jsonify({"error": f"El host {host} ya está registrado"}), 409

    new_id = _next_id(col)

    # 1. Preparar datos para el poll inicial
    srv_for_poll = {
        "id":    new_id,
        "label": label,
        "host":  host,
        "user":  user,
        "pass":  passwd
    }

    # 2. Realizar primer poll RÁPIDO inmediatamente
    snap = sync_server_to_db(srv_for_poll, deep=False)
    
    if snap.get("reachable"):
        # Disparar poll PROFUNDO en segundo plano para obtener discos/ram
        import threading
        threading.Thread(target=sync_server_to_db, args=(srv_for_poll, True), daemon=True).start()
    else:
        return jsonify({"error": f"No se pudo conectar al iLO: {snap.get('error')}"}), 400

    # 3. Cifrar y guardar en la lista de servidores
    doc = {
        "id":    new_id,
        "label": label,
        "host":  host,
        "user":  encrypt(user),    # ← cifrado
        "pass":  encrypt(passwd),  # ← cifrado
    }
    col.insert_one(doc)

    return jsonify(_pub(doc)), 201


# ── DELETE /api/servers/<id> ──────────────────────────────────────
@bp.delete("/api/servers/<int:server_id>")
def delete_server(server_id):
    col    = get_servers_col()
    result = col.delete_one({"id": server_id})
    if result.deleted_count == 0:
        return jsonify({"error": "Servidor no encontrado"}), 404
    return jsonify({"ok": True})


# ── PUT /api/servers/<id> ─────────────────────────────────────────
@bp.put("/api/servers/<int:server_id>")
@handle_errors
def update_server(server_id):
    body = request.json or {}
    col  = get_servers_col()
    srv  = col.find_one({"id": server_id})
    if not srv:
        return jsonify({"error": "Servidor no encontrado"}), 404

    updates = {}
    needs_poll = False

    if "label" in body:
        updates["label"] = body["label"]

    if "host" in body and body["host"].strip() and body["host"].strip() != srv["host"]:
        updates["host"] = body["host"].strip()
        needs_poll = True

    if "user" in body and body["user"].strip():
        updates["user"] = encrypt(body["user"].strip())
        needs_poll = True

    if body.get("pass"):
        updates["pass"] = encrypt(body["pass"].strip())
        needs_poll = True

    if needs_poll:
        # Re-validar y actualizar caché si cambian credenciales o host
        from crypto import decrypt
        host = updates.get("host", srv["host"])
        user = body.get("user", "").strip() or (decrypt(srv["user"]) if is_encrypted(srv["user"]) else srv["user"])
        passwd = body.get("pass", "").strip() or (decrypt(srv["pass"]) if is_encrypted(srv["pass"]) else srv["pass"])
        
        snap = poll_server({"id": server_id, "label": updates.get("label", srv["label"]), "host": host, "user": user, "pass": passwd})
        if not snap.get("reachable"):
            return jsonify({"error": f"No se pudo conectar al iLO con los nuevos datos: {snap.get('error')}"}), 400
        
        snap["timestamp"] = datetime.now()
        get_status_actual().replace_one({"server_id": server_id}, snap, upsert=True)

    if updates:
        col.update_one({"id": server_id}, {"$set": updates})

    updated = col.find_one({"id": server_id})
    return jsonify(_pub(updated))


# ── GET /api/servers/<id>/creds ─────────────────────────────────
@bp.get("/api/servers/<int:server_id>/creds")
def get_server_creds(server_id):
    """
    Retorna usuario y contraseña DESCIFRADOS.
    Solo debe usarse para el asistente de consola remota.
    """
    col = get_servers_col()
    srv = col.find_one({"id": server_id})
    if not srv:
        return jsonify({"error": "Servidor no encontrado"}), 404
    
    _, user, passwd = _get_creds(srv)
    return jsonify({
        "user": user,
        "pass": passwd
    })


# ── GET /api/jirc/<id> ──────────────────────────────────
@bp.get("/api/jirc/<server_id>")
@handle_errors
def get_server_jirc(server_id):
    """
    Genera un archivo JNLP (Java Web Start) para abrir la consola 
    directamente sin login manual, usando un token de sesión.
    """
    # Convertir a int manualmente para evitar fallos de matching de Flask
    try:
        sid = int(server_id)
    except:
        return jsonify({"error": "ID de servidor inválido"}), 400

    col = get_servers_col()
    srv = col.find_one({"id": sid})
    if not srv:
        return jsonify({"error": "Servidor no encontrado"}), 404
    
    host, user, passwd = _get_creds(srv)
    
    # 1. Obtener Token de Sesión real del iLo
    # Si ilo_login falla, handle_errors devolverá el error automáticamente
    token = ilo_login(host, user, passwd)
    
    # 2. Construir el XML del JNLP
    jnlp_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<jnlp spec="1.0+" codebase="https://{host}/irc">
    <information>
        <title>iLO Console - {srv['label']} ({host})</title>
        <vendor>Hewlett Packard Enterprise</vendor>
    </information>
    <security>
        <all-permissions/>
    </security>
    <resources>
        <j2se version="1.5+"/>
        <jar href="irc5.jar" main="true"/>
    </resources>
    <applet-desc name="iLO Remote Console" main-class="com.hp.ilo.ri.irc.IRC" width="1" height="1">
        <param name="ipaddress" value="{host}"/>
        <param name="sessionkey" value="{token}"/>
    </applet-desc>
</jnlp>
"""
    
    safe_host = host.replace('.', '_').replace(':', '_')
    filename = f"iLO_{safe_host}.jnlp"
    
    return Response(
        jnlp_xml.strip(),
        mimetype="application/x-java-jnlp-file",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache"
        }
    )
