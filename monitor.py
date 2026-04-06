"""
monitor.py — Hilo daemon de monitoreo automático
Consulta todos los servidores frecuentemente (30-60s), actualiza el estado actual con TODOS los detalles
y guarda en historial solo ante cambios o cada hora.
"""
import threading
import time
import concurrent.futures
from datetime import datetime, timezone

from storage import load_servers
from ilo import ilo_get
from db import get_status_actual, get_historial, get_events
from config import POLL_INTERVAL, HISTORY_SNAPSHOT_INTERVAL

# Estado previo en memoria para detectar cambios y controlar snapshots por hora
_prev_states = {}   
# { server_id: {"health": ..., "power_state": ..., "reachable": ..., "last_history_time": datetime} }
_lock = threading.Lock()


# ── Helpers de Extracción de Datos ───────────────────────────────────────────

def _safe_get(path, host, user, passwd, session=None):
    """Auxiliar para llamar a ilo_get sin lanzar excepciones."""
    try:
        return ilo_get(path, host, user, passwd, session=session)
    except Exception:
        return {}

def _get_links(obj_or_path, host, user, passwd, session=None):
    """Extrae una lista de enlaces (@odata.id) de una colección o link de Redfish."""
    if not obj_or_path: return []
    # Si es un path (string), lo consultamos primero
    if isinstance(obj_or_path, str):
        try:
            obj_or_path = ilo_get(obj_or_path, host, user, passwd, session=session)
        except Exception: return []
    
    # Si es un objeto tipo link (tiene @odata.id pero no Members)
    if isinstance(obj_or_path, dict) and "@odata.id" in obj_or_path and "Members" not in obj_or_path:
        try:
            path = obj_or_path["@odata.id"].replace("/redfish/v1", "")
            obj_or_path = ilo_get(path, host, user, passwd, session=session)
        except Exception: return []

    # Ahora procesamos el objeto (que debería tener Members o ser una lista)
    links = []
    if isinstance(obj_or_path, list):
        items = obj_or_path
    elif isinstance(obj_or_path, dict):
        items = obj_or_path.get("Members", [])
    else:
        return []

    for item in items:
        if isinstance(item, dict) and "@odata.id" in item:
            links.append(item["@odata.id"].replace("/redfish/v1", ""))
    return [l for l in links if l]

def _fetch_storage_details(host, user, passwd, prev_storage=None, session=None):
    """Obtiene detalles de almacenamiento de forma SECUENCIAL y RECURSIVA."""
    controllers = []
    
    # Rutas para buscar controladores
    for path in ["/Systems/1/Storage", "/Systems/1/SmartStorage"]:
        try:
            ctrl_links = _get_links(path, host, user, passwd, session)
            for cl in ctrl_links:
                try:
                    ctrl = ilo_get(cl, host, user, passwd, session=session)
                    # Buscar componentes de forma más agresiva (Drives, Volumes, LogicalDrives, PhysicalDrives)
                    all_comp_links = []
                    
                    # 1. Rutas estándar en la raíz del controlador
                    all_comp_links += _get_links(ctrl.get("Drives"), host, user, passwd, session)
                    all_comp_links += _get_links(ctrl.get("Volumes"), host, user, passwd, session)
                    
                    # 2. Rutas en objeto Links
                    lks = ctrl.get("Links", {})
                    all_comp_links += _get_links(lks.get("Drives"), host, user, passwd, session)
                    all_comp_links += _get_links(lks.get("LogicalDrives"), host, user, passwd, session)
                    all_comp_links += _get_links(lks.get("PhysicalDrives"), host, user, passwd, session)
                    
                    # 3. Oem-Specific (HPE SmartStorage suele anidar aquí)
                    oem_hpe = ctrl.get("Oem", {}).get("Hpe", {})
                    all_comp_links += _get_links(oem_hpe.get("Links", {}).get("LogicalDrives"), host, user, passwd, session)
                    all_comp_links += _get_links(oem_hpe.get("Links", {}).get("PhysicalDrives"), host, user, passwd, session)
                    
                    # Deduplicar links
                    all_comp_links = list(dict.fromkeys(all_comp_links))
                    
                    drives = []
                    for dl in all_comp_links:
                        try:
                            d = ilo_get(dl, host, user, passwd, session=session)
                            if not d: continue
                            
                            # Intentar obtener capacidad de varias fuentes
                            bv = d.get("CapacityBytes")
                            if bv is None:
                                mv = d.get("CapacityMiB")
                                if mv: bv = mv * 1024 * 1024
                            
                            # Si sigue siendo 0 o None, intentamos sacar del nombre o descripción (ej: "960GB...")
                            if not bv:
                                text_to_search = f"{d.get('Name','')} {d.get('Model','')} {d.get('Description','')}"
                                import re
                                match = re.search(r"(\d+)\s*(GB|TB|GiB|TiB)", text_to_search, re.I)
                                if match:
                                    val, unit = int(match.group(1)), match.group(2).upper()
                                    mult = 1e12 if "T" in unit else 1e9
                                    bv = val * mult

                            drives.append({
                                "name":        d.get("Name") or d.get("Id") or f"Drive {dl.split('/')[-1]}",
                                "model":       d.get("Model") or d.get("Manufacturer") or "N/A",
                                "capacity_gb": round((bv or 0) / 1e9, 1),
                                "type":        d.get("MediaType") or d.get("Protocol") or "N/A",
                                "protocol":    d.get("Protocol", "N/A"),
                                "health":      d.get("Status", {}).get("Health") or "OK",
                            })
                        except Exception: continue
                    
                    controllers.append({
                        "name": ctrl.get("Name", "Controller"),
                        "health": ctrl.get("Status", {}).get("Health") or "OK",
                        "drives": drives
                    })
                except Exception: continue
        except Exception: continue

    if not controllers and prev_storage: return prev_storage
    return controllers

def _fetch_memory_details(host, user, passwd, prev_memory=None, session=None):
    """Obtiene detalles de memoria de forma SECUENCIAL."""
    try:
        mem_links = _get_links("/Systems/1/Memory", host, user, passwd, session)
        results = []
        for ml in mem_links:
            try:
                m = ilo_get(ml, host, user, passwd, session=session)
                if m.get("Status", {}).get("State") == "Absent": continue
                results.append({
                    "name": m.get("Name") or m.get("Id"), 
                    "size_mb": m.get("CapacityMiB", 0),
                    "speed_mhz": m.get("OperatingSpeedMhz", 0), 
                    "type": m.get("MemoryDeviceType", "N/A"),
                    "health": m.get("Status", {}).get("Health"),
                })
            except Exception: continue
        
        if prev_memory and len(results) < len(prev_memory):
            # Persistencia selectiva por slot
            res_names = {r["name"] for r in results}
            for pm in prev_memory:
                if pm["name"] not in res_names: results.append(pm)
            results.sort(key=lambda x: x["name"])
            
        return results if results else (prev_memory or [])
    except Exception: return prev_memory or []

def poll_server(srv, deep=True, prev_snap=None):
    """
    Consulta un servidor. 
    - deep=True: Obtiene todo (lento por discos/ram).
    - deep=False: Solo resumen, temperaturas y energía (rápido).
    """
    host, user, passwd = srv["host"], srv["user"], srv["pass"]

    # Usar una sesión persistente por servidor para evitar saturar el iLO
    import requests
    with requests.Session() as session:
        session.auth = (user, passwd) # Autenticación a nivel de sesión
        try:
            # Consultas SECUENCIALES para máxima estabilidad en iLO 5 (Gen10)
            # El uso de Session Keep-Alive hace que sea rápido sin romper el iLO
            r = {
                "systems": _safe_get("/Systems/1",         host, user, passwd, session),
                "thermal": _safe_get("/Chassis/1/Thermal", host, user, passwd, session),
                "power":   _safe_get("/Chassis/1/Power",   host, user, passwd, session),
            }
            if deep:
                p_storage = prev_snap.get("storage_data") if prev_snap else None
                p_memory  = prev_snap.get("memory_data")  if prev_snap else None
                r["storage"] = _fetch_storage_details(host, user, passwd, p_storage, session)
                r["memory"]  = _fetch_memory_details(host, user, passwd, p_memory,  session)

            s, t, p = r["systems"], r["thermal"], r["power"]
            st = r.get("storage", [])
            me = r.get("memory", [])

            if not s or not s.get("PowerState"):
                raise ValueError("Respuesta vacía del iLO")

            ctrl = (p.get("PowerControl") or [{}])[0]
            temps = [x.get("ReadingCelsius") for x in t.get("Temperatures", []) 
                     if x.get("Status", {}).get("State") != "Absent" and x.get("ReadingCelsius") is not None]
            
            fan_warn = sum(1 for f in t.get("Fans", []) 
                           if f.get("Status", {}).get("State") != "Absent" and f.get("Status", {}).get("Health") not in ("OK", None))

            # Totales para reporte e inventario
            ilo_name = s.get("HostName") or s.get("Name", "Servidor iLO")
            total_mem_gb = s.get("MemorySummary", {}).get("TotalSystemMemoryGiB", 0)
            
            # Calcular total de disco sumando todos los drives de todos los controladores
            total_disk_gb = 0
            for ctrl_data in st:
                for drive in ctrl_data.get("drives", []):
                    total_disk_gb += drive.get("capacity_gb", 0)

            return {
                "server_id":      srv["id"],
                "server_label":   srv["label"],
                "server_host":    host,
                "ilo_name":       ilo_name,
                "total_mem_gb":   total_mem_gb,
                "total_storage_gb": round(total_disk_gb, 1),
                "reachable":      True,
                "health":         s.get("Status", {}).get("Health"),
                "health_rollup":  s.get("Status", {}).get("HealthRollup"),
                "power_state":    s.get("PowerState"),
                "consumed_watts": ctrl.get("PowerConsumedWatts"),
                "capacity_watts": ctrl.get("PowerCapacityWatts"),
                "max_temp_c":     max(temps) if temps else None,
                "fan_count":      len(t.get("Fans", [])),
                "fan_warn":       fan_warn,
                "storage_data":   st,
                "memory_data":    me,
                "systems_raw":    s,
                "thermal_raw":    t,
                "power_raw":      p,
                "error":          None,
            }
        except Exception as e:
            return {
                "server_id": srv["id"], "server_label": srv["label"], "server_host": host,
                "ilo_name": "Error", "total_mem_gb": 0, "total_storage_gb": 0,
                "reachable": False, "health": None, "health_rollup": None, "power_state": None,
                "consumed_watts": None, "capacity_watts": None, "max_temp_c": None, "fan_count": 0, "fan_warn": 0,
                "storage_data": [], "memory_data": [], "error": str(e),
            }


def sync_server_to_db(srv, deep=True):
    """Polls a server and updates its current state in MongoDB."""
    snap = poll_server(srv, deep=deep)
    snap["timestamp"] = datetime.now(timezone.utc)
    if snap.get("reachable"):
        get_status_actual().replace_one({"server_id": srv["id"]}, snap, upsert=True)
    return snap


def _detect_and_log_events(snapshot, prev):
    """
    Compara snapshot actual vs previo y detecta SOLO cambios reales de hardware.
    Ignoramos completamente los estados de conexión entre el dashboard y el iLO.
    Solo generamos eventos cuando el servidor iLO mismo reporta un cambio crítico.
    """
    # Si el servidor no responde, NO generamos ningún evento ni alerta.
    # Esto puede ser un corte temporal de red entre el dashboard y el iLO.
    if not snapshot["reachable"]:
        return []

    now    = snapshot["timestamp"]
    events = []

    # Solo comparar si tenemos un estado previo real del hardware
    if not prev.get("reachable", True):
        # El prev era unreachable: ahora volvió. No es un evento de hardware,
        # solo restauración de conectividad. No loguear nada.
        return []

    # ── 1. Cambio de Health del sistema ──────────────────────────────────
    prev_health, curr_health = prev.get("health"), snapshot["health"]
    if prev_health and curr_health and prev_health != curr_health:
        severity = "Critical" if curr_health in ("Critical", "Warning") else "Info"
        etype    = "HealthDegradation" if curr_health in ("Critical", "Warning") else "HealthRecovery"
        events.append({
            "timestamp": now, "server_id": snapshot["server_id"],
            "server_label": snapshot["server_label"], "server": snapshot["server_host"],
            "type": etype, "severity": severity,
            "old_status": prev_health, "new_status": curr_health,
            "details": f"Salud del sistema cambió de {prev_health} a {curr_health}.",
        })

    # ── 2. Cambio de estado de energía (encendido/apagado) ───────────────
    prev_power, curr_power = prev.get("power_state"), snapshot["power_state"]
    if prev_power and curr_power and prev_power != curr_power:
        severity = "Critical" if curr_power in ("Off", "PoweringOff") else "Info"
        events.append({
            "timestamp": now, "server_id": snapshot["server_id"],
            "server_label": snapshot["server_label"], "server": snapshot["server_host"],
            "type": "PowerStateChanged", "severity": severity,
            "old_status": prev_power, "new_status": curr_power,
            "details": f"El servidor cambió de estado: {prev_power} → {curr_power}.",
        })

    # ── 3. Ventiladores con fallo (fan_warn > 0 cuando antes era 0) ──────
    prev_fan_warn, curr_fan_warn = prev.get("fan_warn", 0), snapshot.get("fan_warn", 0)
    if prev_fan_warn == 0 and curr_fan_warn > 0:
        events.append({
            "timestamp": now, "server_id": snapshot["server_id"],
            "server_label": snapshot["server_label"], "server": snapshot["server_host"],
            "type": "FanWarning", "severity": "Warning",
            "old_status": "OK", "new_status": "Warning",
            "details": f"{curr_fan_warn} ventilador(es) reportan estado anormal.",
        })
    elif prev_fan_warn > 0 and curr_fan_warn == 0:
        events.append({
            "timestamp": now, "server_id": snapshot["server_id"],
            "server_label": snapshot["server_label"], "server": snapshot["server_host"],
            "type": "FanRecovery", "severity": "Info",
            "old_status": "Warning", "new_status": "OK",
            "details": "Los ventiladores han vuelto a estado normal.",
        })

    return events


def run_cycle():
    """Ejecuta un ciclo completo de monitoreo de alta frecuencia con todos los detalles."""
    servers = load_servers()
    if not servers: return

    now = datetime.now(timezone.utc)
    status_col, hist_col, events_col = get_status_actual(), get_historial(), get_events()

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        # Pasamos el estado previo a poll_server para permitir persistencia de datos
        def poll_wrapper(srv):
            with _lock:
                prev = _prev_states.get(srv["id"], {})
            return poll_server(srv, deep=True, prev_snap=prev.get("full_snap"))
        
        results = list(ex.map(poll_wrapper, servers))

    for snap in results:
        snap["timestamp"] = now
        srv_id = snap["server_id"]

        # 1. Actualizar ESTADO ACTUAL solo si el servidor respondió correctamente
        #    Si no responde, mantenemos el último estado conocido en DB (no sobreescribimos)
        if snap.get("reachable"):
            status_col.replace_one({"server_id": srv_id}, snap, upsert=True)

        # 2. Detectar cambios de HARDWARE y manejar HISTORIAL
        with _lock:
            prev = _prev_states.get(srv_id, {})
            events = _detect_and_log_events(snap, prev)

            # El historial por hora SOLO se guarda si el servidor respondió correctamente.
            # No guardamos snapshots de error (pérdida de conexión dashboard → iLO).
            last_hist = prev.get("last_history_time")
            is_new    = not last_hist
            snap_save_time = last_hist  # Por defecto, no actualizamos el tiempo

            if snap.get("reachable"):
                if is_new or len(events) > 0 or (now - last_hist).total_seconds() >= HISTORY_SNAPSHOT_INTERVAL:
                    hist_col.insert_one(snap)
                    snap_save_time = now

            if events:
                events_col.insert_many(events)
                for ev in events:
                    # Emitir alerta real-time via Socket.IO
                    if _socketio:
                        try:
                            # Serializar fecha para el socket
                            ev_copy = ev.copy()
                            if isinstance(ev_copy["timestamp"], datetime):
                                ev_copy["timestamp"] = ev_copy["timestamp"].isoformat()
                            _socketio.emit('new_alert', ev_copy, namespace='/')
                        except Exception as ex_emit:
                            print(f"[Monitor] Error emitiendo socket: {ex_emit}")
                    
                    if ev["severity"] == "Critical": print(f"!!! ALERTA CRÍTICA: {ev['server_label']} - {ev['details']}")
            
            _prev_states[srv_id] = {
                "reachable":        snap["reachable"],
                "health":           snap.get("health"),
                "power_state":      snap.get("power_state"),
                "fan_warn":         snap.get("fan_warn", 0),
                "last_history_time": snap_save_time,
                "full_snap":        snap if snap.get("reachable") else prev.get("full_snap")
            }

    # Emitir señal de fin de ciclo para refresco de UI en tiempo real
    if _socketio:
        _socketio.emit('fleet_update', {"timestamp": now.isoformat()}, namespace='/')


def _monitor_loop():
    """Bucle infinito del hilo daemon."""
    while True:
        try: run_cycle()
        except Exception as e: print(f"[Monitor] Error fatal en ciclo: {e}")
        time.sleep(POLL_INTERVAL)


def start_monitor(socketio_instance=None):
    """Arranca el hilo daemon de monitoreo."""
    global _socketio
    _socketio = socketio_instance
    t = threading.Thread(target=_monitor_loop, name="ilo-monitor", daemon=True)
    t.start()
    print(f"[Monitor] Hilo iniciado (SocketIO {'Activado' if _socketio else 'Desactivado'}). Polling: {POLL_INTERVAL}s.")
