from datetime import datetime

def calculate_power_metrics(power_raw):
    """
    Calcula vatios consumidos y capacidad total considerando redundancia 1+1.
    Extraído para evitar duplicación entre monitor.py y metrics.py.
    """
    if not power_raw:
        return 0, 0
        
    p_controls = power_raw.get("PowerControl", [])
    p_supplies = power_raw.get("PowerSupplies", [])
    
    consumed_w = 0
    capacity_w = 0
    
    # 1. Consumo real (usamos el máximo reportado por los controles)
    if p_controls:
        consumed_w = max([c.get("PowerConsumedWatts") or 0 for c in p_controls])
        
    # 2. Capacidad (Priorizar un solo módulo para sistemas redundantes 1+1)
    active_psus = [ps for ps in p_supplies if ps.get("Status", {}).get("State") != "Absent"]
    if active_psus:
        # Tomamos el primero asumiendo que el iLO reporta la capacidad por módulo (ej. 800W)
        capacity_w = active_psus[0].get("PowerCapacityWatts") or 0
        
    # Fallback: Si no hay PSUs individuales, usar el máximo del control central
    if not capacity_w and p_controls:
        capacity_w = max([c.get("PowerCapacityWatts") or 0 for c in p_controls])
        
    return consumed_w, capacity_w

def serialize_date(dt):
    """Serializa objetos datetime a ISO format con sufijo Z (UTC)."""
    if not dt: return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.isoformat() + "Z"
        return dt.isoformat()
    return dt

def format_server_summary(snap):
    """Convierte un snapshot crudo de la DB en el formato JSON que espera el frontend."""
    if not snap or not snap.get("reachable"):
        return None

    s = snap.get("systems_raw", {})
    t = snap.get("thermal_raw", {})
    p = snap.get("power_raw", {})
    
    consumed_w, capacity_w = calculate_power_metrics(p)

    return {
        "server_id": snap.get("server_id"),
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
    }
