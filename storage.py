"""
storage.py — Acceso a servidores usando MongoDB con cifrado de credenciales.
- load_servers(): devuelve servidores con user/pass DESCIFRADOS (para uso interno).
- save_servers(): cifra user/pass antes de guardar (usado solo en migración).
"""
from db import get_servers_col
from crypto import encrypt, decrypt, is_encrypted


def _decrypt_doc(doc):
    """
    Descifra user y pass de un documento MongoDB.
    Si el valor ya es texto plano (migración progresiva), lo deja como está.
    """
    d = {k: v for k, v in doc.items() if k != "_id"}
    if d.get("user"):
        d["user"] = decrypt(d["user"]) if is_encrypted(d["user"]) else d["user"]
    if d.get("pass"):
        d["pass"] = decrypt(d["pass"]) if is_encrypted(d["pass"]) else d["pass"]
    return d


def load_servers():
    """
    Devuelve lista de servidores con credenciales descifradas.
    Usado por monitor.py y routes/metrics.py para conectarse al iLO.
    """
    col = get_servers_col()
    return [_decrypt_doc(s) for s in col.find({}, {"_id": 0}).sort("id", 1)]


def save_servers(servers):
    """
    Cifra user/pass y reemplaza toda la colección.
    Usado únicamente para la migración inicial desde servers.json.
    """
    col = get_servers_col()
    col.delete_many({})
    if servers:
        docs = []
        for s in servers:
            doc = dict(s)
            # Solo cifrar si aún no está cifrado
            if doc.get("user") and not is_encrypted(doc["user"]):
                doc["user"] = encrypt(doc["user"])
            if doc.get("pass") and not is_encrypted(doc["pass"]):
                doc["pass"] = encrypt(doc["pass"])
            docs.append(doc)
        col.insert_many(docs)