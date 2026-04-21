"""
routes/reports.py — Endpoints de reportes históricos con MongoDB
  GET /api/reports/weekly          → eventos últimos 7 días + métricas KPI
  GET /api/reports/history         → lista de fechas con datos en MongoDB
  GET /api/reports/daily?date=...  → snapshots de todos los servidores en un día
  GET /api/reports/metrics         → promedios de temperatura y energía por hora
  GET /api/reports/hourly          → snapshots de salud por hora para todos los servers
  GET /api/reports/download        → descarga CSV de la semana
  POST /api/monitor/run-now        → fuerza un ciclo de monitoreo inmediato (debug)
"""
from flask import Blueprint, jsonify, request, Response
from datetime import datetime, timezone, timedelta
import csv
import io

from db import get_snapshots, get_events, get_servers_col
from config import EC_TZ
from utils import serialize_date

bp = Blueprint("reports", __name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serialize(doc):
    """Convierte documento MongoDB a dict serializable (ObjectId → str, datetime → ISO UTC)."""
    out = {}
    for k, v in doc.items():
        if k == "_id":
            out["_id"] = str(v)
        elif isinstance(v, datetime):
            out[k] = serialize_date(v)
        else:
            out[k] = v
    return out


def _events_in_range(since: datetime, until: datetime):
    """Obtiene eventos de hardware real en el rango dado. Excluye eventos de conectividad."""
    col = get_events()
    # Solo eventos de hardware real: cambios de salud, energía y ventiladores
    HARDWARE_TYPES = ["HealthDegradation", "HealthRecovery", "PowerStateChanged", "FanWarning", "FanRecovery"]
    return [
        _serialize(d)
        for d in col.find(
            {
                "timestamp": {"$gte": since, "$lt": until},
                "type": {"$in": HARDWARE_TYPES},
            },
            {"_id": 1, "timestamp": 1, "server_id": 1, "server": 1, "server_label": 1,
             "type": 1, "old_status": 1, "new_status": 1, "details": 1, "severity": 1}
        ).sort("timestamp", -1)
    ]

HARDWARE_EVENT_TYPES = ["HealthDegradation", "HealthRecovery", "PowerStateChanged", "FanWarning", "FanRecovery"]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@bp.get("/api/reports/weekly")
def weekly_report():
    try:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        until = datetime.now(timezone.utc)
        logs  = _events_in_range(since, until)
    except Exception as e:
        return jsonify({"error": f"No se pudo conectar a MongoDB: {str(e)}"}), 503

    try:
        from db import get_status_actual
        cur_off = list(get_status_actual().find({"power_state": "Off"}, {"_id": 0, "server_label": 1, "server_host": 1, "timestamp": 1}))
        for c in cur_off:
            c["timestamp"] = serialize_date(c.get("timestamp"))
    except Exception:
        cur_off = []

    return jsonify({
        "metrics": {
            "total_events":    len(logs),
            "critical_alarms": sum(1 for l in logs if l["type"] == "HealthDegradation"),
            "recoveries":      sum(1 for l in logs if l["type"] == "HealthRecovery"),
            "power_events":    sum(1 for l in logs if l["type"] == "PowerStateChanged"),
            "fan_events":      sum(1 for l in logs if l["type"] in ["FanWarning", "FanRecovery"]),
        },
        "logs": logs,
        "off_servers": cur_off
    })


@bp.get("/api/reports/history")
def history():
    """
    Devuelve lista de fechas (UTC) que tienen al menos un snapshot,
    junto con conteo de snapshots y eventos del día.
    """
    try:
        # Agrupar snapshots por fecha (día en Ecuador -05:00)
        pipeline = [
            {
                "$group": {
                    "_id": {
                        "year":  {"$year":  {"date": "$timestamp", "timezone": "-05:00"}},
                        "month": {"$month": {"date": "$timestamp", "timezone": "-05:00"}},
                        "day":   {"$dayOfMonth": {"date": "$timestamp", "timezone": "-05:00"}},
                    },
                    "snapshots": {"$sum": 1},
                    "servers":   {"$addToSet": "$server_id"},
                    "min_ts":    {"$min": "$timestamp"},
                }
            },
            {"$sort": {"_id.year": -1, "_id.month": -1, "_id.day": -1}},
            {"$limit": 60},   # máximo 60 días de historial
        ]
        raw = list(get_snapshots().aggregate(pipeline))

        days = []
        for r in raw:
            d = r["_id"]
            date_str = f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}"

            # Contar eventos de hardware real de ese día (excluir conexiones)
            day_start = datetime(d["year"], d["month"], d["day"], tzinfo=EC_TZ)
            day_end   = day_start + timedelta(days=1)

            HARDWARE_TYPES = ["HealthDegradation", "HealthRecovery", "PowerStateChanged", "FanWarning", "FanRecovery"]
            events_count = get_events().count_documents(
                {
                    "timestamp": {"$gte": day_start, "$lt": day_end},
                    "type": {"$in": HARDWARE_TYPES},
                }
            )

            days.append({
                "date":         date_str,
                "snapshots":    r["snapshots"],
                "server_count": len(r["servers"]),
                "events":       events_count,
            })

        return jsonify({"days": days})

    except Exception as e:
        return jsonify({"error": str(e)}), 503


@bp.get("/api/reports/daily")
def daily_report():
    """
    Devuelve el último snapshot de cada servidor para el día indicado.
    Query param: ?date=YYYY-MM-DD  (default: hoy)
    """
    date_str = request.args.get("date")
    try:
        if date_str:
            d = datetime.strptime(date_str, "%Y-%m-%d")
        else:
            d = datetime.now(timezone.utc)

        day_start = datetime(d.year, d.month, d.day, tzinfo=EC_TZ)
        day_end   = day_start + timedelta(days=1)

        # 1. Obtener lista maestra de servidores configurados
        all_servers = list(get_servers_col().find({}, {"_id": 0}))
        
        # 2. Obtener todos los snapshots del día
        snapshots_raw = list(get_snapshots().find(
            {"timestamp": {"$gte": day_start, "$lt": day_end}}
        ).sort("timestamp", -1))
        
        # Serializar y asegurar campos obligatorios
        snapshots = []
        fleet_map = {s["id"]: s for s in all_servers}

        for d in snapshots_raw:
            sd = _serialize(d)
            srv_id = sd.get("server_id")
            master = fleet_map.get(srv_id, {})
            
            if not sd.get("server_label"): sd["server_label"] = master.get("label") or f"iLO {srv_id}"
            if not sd.get("server_host"):  sd["server_host"]  = master.get("host") or "N/A"
            
            snapshots.append(sd)
            
        events = _events_in_range(day_start, day_end)

        return jsonify({
            "date":      day_start.strftime("%Y-%m-%d"),
            "snapshots": snapshots,
            "events":    events,
            "fleet":     all_servers,  # Añadimos la lista maestra para referencia del frontend
        })

    except ValueError:
        return jsonify({"error": "Formato de fecha inválido. Usa YYYY-MM-DD"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@bp.get("/api/reports/hourly")
def hourly_report():
    """
    Devuelve el estado de salud de cada servidor para cada hora del día indicado.
    Útil para la cuadrícula de disponibilidad.
    """
    date_str = request.args.get("date")
    try:
        if date_str:
            d = datetime.strptime(date_str, "%Y-%m-%d")
        else:
            d = datetime.now(timezone.utc)

        day_start = datetime(d.year, d.month, d.day, tzinfo=EC_TZ)
        day_end   = day_start + timedelta(days=1)

        # Agrupar por servidor y por hora
        pipeline = [
            {"$match": {"timestamp": {"$gte": day_start, "$lt": day_end}}},
            {"$sort": {"timestamp": -1}},
            {"$group": {
                "_id": {
                    "server_id": "$server_id",
                    "hour":      {"$hour": {"date": "$timestamp", "timezone": "-05:00"}}
                },
                "health":      {"$first": "$health"},
                "reachable":   {"$first": "$reachable"},
                "label":       {"$first": "$server_label"},
            }},
            {"$sort": {"_id.server_id": 1, "_id.hour": 1}}
        ]

        docs = list(get_snapshots().aggregate(pipeline))
        
        # Estructurar datos: { server_id: { label, hours: { hour: status } } }
        results = {}
        last_known_status = {}  # { server_id: last good status }

        for doc in docs:
            sid  = doc["_id"]["server_id"]
            hour = doc["_id"]["hour"]
            
            if sid not in results:
                label = doc.get("label") or f"Server {sid}"
                results[sid] = {"label": label, "hours": {}}
            
            # Si el servidor respondió correctamente, usamos su health real
            # Si no respondió, mantenemos el último estado conocido (no marcamos "Offline")
            if doc.get("reachable"):
                status = doc.get("health") or "Unknown"
                last_known_status[sid] = status
            else:
                status = last_known_status.get(sid, "Unknown")
            
            results[sid]["hours"][hour] = status

        return jsonify({
            "date":   day_start.strftime("%Y-%m-%d"),
            "data":   results
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.get("/api/reports/metrics")
def historical_metrics():
    """
    Devuelve promedios de temperatura y potencia por hora para un servidor o para toda la flota.
    Params: server_id (opcional), days=7 (default)
    """
    sid  = request.args.get("server_id", type=int)
    days = request.args.get("days", default=7, type=int)

    try:
        since = datetime.now(timezone.utc) - timedelta(days=days) # Revert to UTC range
        match = {"timestamp": {"$gte": since}}
        if sid:
            match["server_id"] = sid

        pipeline = [
            {"$match": match},
            {"$sort": {"timestamp": 1}},
            {"$group": {
                "_id": {
                    "year":  {"$year":  {"date": "$timestamp", "timezone": "-05:00"}},
                    "month": {"$month": {"date": "$timestamp", "timezone": "-05:00"}},
                    "day":   {"$dayOfMonth": {"date": "$timestamp", "timezone": "-05:00"}},
                    "hour":  {"$hour": {"date": "$timestamp", "timezone": "-05:00"}}
                },
                "avg_temp":  {"$avg": "$max_temp_c"},
                "max_temp":  {"$max": "$max_temp_c"},
                "avg_power": {"$avg": "$consumed_watts"},
                "ts":        {"$first": "$timestamp"}
            }},
            {"$sort": {"_id.year": 1, "_id.month": 1, "_id.day": 1, "_id.hour": 1}}
        ]

        raw = list(get_snapshots().aggregate(pipeline))
        
        points = []
        for r in raw:
            points.append({
                "ts":        r["ts"].isoformat(),
                "hour":      r["_id"]["hour"],
                "avg_temp":  round(r["avg_temp"], 1) if r["avg_temp"] is not None else None,
                "max_temp":  r["max_temp"],
                "avg_power": round(r["avg_power"], 1) if r["avg_power"] is not None else None,
            })

        return jsonify({
            "server_id": sid,
            "days":      days,
            "points":    points
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.get("/api/reports/download")
def download_csv():
    """Descarga CSV de eventos de los últimos 7 días."""
    try:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        logs  = _events_in_range(since, datetime.now(timezone.utc))
    except Exception as e:
        return jsonify({"error": str(e)}), 503

    # 1. Obtener datos actuales de hardware (Inventario) para enriquecer el CSV
    stats = {}
    try:
        from db import get_status_actual
        cur_stats = list(get_status_actual().find({}, {
            "server_id": 1, "ilo_name": 1, "total_mem_gb": 1, "total_storage_gb": 1
        }))
        stats = {s["server_id"]: s for s in cur_stats}
    except:
        pass

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Fecha/Hora", "Servidor", "IP", "Nombre iLO", 
        "RAM (GB)", "Disco (GB)", "Tipo Evento",
        "Estado Anterior", "Estado Nuevo", "Detalles"
    ])

    for l in logs:
        sid = l.get("server_id") # Nota: asegurar que server_id esté en events
        sinfo = stats.get(sid, {})
        writer.writerow([
            l.get("timestamp", ""),
            l.get("server_label", ""),
            l.get("server", ""),
            sinfo.get("ilo_name", "N/A"),
            sinfo.get("total_mem_gb", "N/A"),
            sinfo.get("total_storage_gb", "N/A"),
            l.get("type", ""),
            l.get("old_status", ""),
            l.get("new_status", ""),
            l.get("details", ""),
        ])

    output.seek(0)
    filename = f"reporte_completo_ilo_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@bp.post("/api/monitor/run-now")
def run_now():
    """Fuerza un ciclo de monitoreo inmediato (útil para pruebas)."""
    try:
        from monitor import run_cycle
        import threading
        t = threading.Thread(target=run_cycle, daemon=True)
        t.start()
        return jsonify({"ok": True, "message": "Ciclo de monitoreo iniciado en background."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
