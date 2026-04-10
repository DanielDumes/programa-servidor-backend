from flask import Blueprint, jsonify
from db import get_status_actual
from ilo import handle_errors
from utils import calculate_power_metrics, serialize_date

bp = Blueprint("metrics", __name__)

@bp.get("/api/servers/<int:server_id>/summary")
@handle_errors
def server_summary(server_id):
    col = get_status_actual()
    snap = col.find_one({"server_id": server_id}, {"_id": 0})
    
    if not snap or not snap.get("reachable"):
        return jsonify({"error": "Datos no disponibles o servidor offline"}), 404

    s = snap.get("systems_raw", {})
    t = snap.get("thermal_raw", {})
    p = snap.get("power_raw", {})
    
    # Usar utilidad compartida para calcular potencia
    consumed_w, capacity_w = calculate_power_metrics(p)

    return jsonify({
        "summary": {
            "name":          s.get("HostName") or s.get("Name", "Servidor"),
            "model":         s.get("Model", "N/A"),
            "serial":        s.get("SerialNumber", "N/A"),
            "bios_version":  s.get("BiosVersion", "N/A"),
            "power_state":   s.get("PowerState", "Unknown"),
            "health":        s.get("Status", {}).get("Health", "Unknown"),
            "health_rollup": s.get("Status", {}).get("HealthRollup", "Unknown"),
            "memory_gib":    s.get("MemorySummary", {}).get("TotalSystemMemoryGiB", 0),
            "cpu_count":         s.get("ProcessorSummary", {}).get("Count", 0),
            "logical_cpu_count": snap.get("total_cpu_threads") or s.get("ProcessorSummary", {}).get("LogicalProcessorCount", 0),
            "cpu_model":         s.get("ProcessorSummary", {}).get("Model", "N/A"),
        },
        "temperatures": [
            {
                "name":           x.get("Name"),
                "reading_c":      x.get("ReadingCelsius"),
                "upper_caution":  x.get("UpperThresholdNonCritical"),
                "upper_critical": x.get("UpperThresholdCritical"),
                "health":         x.get("Status", {}).get("Health", "Unknown"),
                "location":       x.get("PhysicalContext"),
            }
            for x in t.get("Temperatures", [])
            if x.get("Status", {}).get("State") != "Absent"
            and x.get("ReadingCelsius") is not None
        ],
        "fans": [
            {
                "name": f.get("Name") or f.get("FanName"),
                "rpm": f.get("Reading") or f.get("CurrentReading"),
                "health": f.get("Status", {}).get("Health"),
                "units": f.get("Units") or f.get("ReadingUnits") or "RPM"
            }
            for f in t.get("Fans", [])
            if f.get("Status", {}).get("State") != "Absent"
        ],

        "power": {
            "consumed_watts": consumed_w,
            "capacity_watts": capacity_w,
            "power_supplies": [
                {
                    "name":        ps.get("Name"),
                    "health":      ps.get("Status", {}).get("Health"),
                    "power_watts": ps.get("LastPowerOutputWatts"),
                }
                for ps in p.get("PowerSupplies", [])
                if ps.get("Status", {}).get("State") != "Absent"
            ],
        },
        "last_updated": serialize_date(snap.get("timestamp"))
    })

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
    return jsonify({"status": "ok", "servers": len(load_servers())})