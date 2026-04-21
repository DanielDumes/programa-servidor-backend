from flask import Blueprint, jsonify
from db import get_status_actual
from ilo import handle_errors
from utils import calculate_power_metrics, serialize_date, format_server_summary

bp = Blueprint("metrics", __name__)

@bp.get("/api/servers/<int:server_id>/summary")
@handle_errors
def server_summary(server_id):
    col = get_status_actual()
    snap = col.find_one({"server_id": server_id}, {"_id": 0})
    
    formatted = format_server_summary(snap)
    if not formatted:
        return jsonify({"error": "Datos no disponibles o servidor offline"}), 404

    return jsonify(formatted)

@bp.get("/api/servers/<int:server_id>/storage")
@handle_errors
def server_storage(server_id):
    col = get_status_actual()
    snap = col.find_one({"server_id": server_id}, {"_id": 0})
    if not snap:
        return jsonify({"error": "Servidor no encontrado"}), 404
    # Siempre devolvemos los últimos datos conocidos aunque el servidor esté temporalmente inalcanzable
    return jsonify({"controllers": snap.get("storage_data") or []})


@bp.get("/api/servers/<int:server_id>/memory")
@handle_errors
def server_memory(server_id):
    col = get_status_actual()
    snap = col.find_one({"server_id": server_id}, {"_id": 0})
    if not snap:
        return jsonify({"error": "Servidor no encontrado"}), 404
    # Siempre devolvemos los últimos datos conocidos aunque el servidor esté temporalmente inalcanzable
    mem = snap.get("memory_data") or []
    return jsonify({"dimms": mem, "dimm_count": len(mem)})

@bp.get("/api/health")
def health():
    from storage import load_servers
    col = get_status_actual()
    latest_snap = col.find_one(sort=[("timestamp", -1)])
    latest_ts = None
    if latest_snap and latest_snap.get("timestamp"):
        latest_ts = serialize_date(latest_snap["timestamp"])
        
    return jsonify({
        "status": "ok", 
        "servers": len(load_servers()),
        "last_fleet_update": latest_ts
    })