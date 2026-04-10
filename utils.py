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
