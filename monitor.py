"""
monitor.py — Hilo daemon de monitoreo automático
Consulta todos los servidores frecuentemente (30-60s), actualiza el estado actual con TODOS los detalles
y guarda en historial solo ante cambios o cada hora.
"""
import threading
import time
import concurrent.futures
import re
from datetime import datetime, timezone

from storage import load_servers
from ilo import ilo_get
from db import get_status_actual, get_historial, get_events
from config import POLL_INTERVAL, HISTORY_SNAPSHOT_INTERVAL, EC_TZ
from utils import calculate_power_metrics, serialize_date, format_server_summary
from logger import logger

# variables para Socket.IO
_socketio = None
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
    """
    Obtiene detalles de almacenamiento.
    - Intenta /Systems/1/Storage (estándar Redfish, iLO 5).
    - Solo si esa ruta no devuelve nada, prueba las rutas OEM de SmartStorage (iLO 4).
    Esto evita duplicados en iLO 5, donde ambas APIs exponen el mismo controlador.
    """
    controllers = []
    
    # iLO 5: /Storage devuelve todo. iLO 4: /Storage puede estar vacío y necesita SmartStorage.
    for path in ["/Systems/1/Storage", "/Systems/1/SmartStorage", "/Systems/1/SmartStorage/ArrayControllers"]:
        try:
            ctrl_links = _get_links(path, host, user, passwd, session)
            if not ctrl_links: continue

            for cl in ctrl_links:
                try:
                    ctrl = ilo_get(cl, host, user, passwd, session=session)
                    
                    # 1. Descubrir links de componentes (Físicos y Lógicos)
                    physical_links = []
                    logical_links = []
                    
                    # Rutas estándar
                    physical_links += _get_links(ctrl.get("Drives"), host, user, passwd, session)
                    logical_links  += _get_links(ctrl.get("Volumes"), host, user, passwd, session)
                    
                    # Rutas en el objeto Links
                    lks = ctrl.get("Links", {})
                    physical_links += _get_links(lks.get("Drives"), host, user, passwd)
                    physical_links += _get_links(lks.get("PhysicalDrives"), host, user, passwd)
                    physical_links += _get_links(lks.get("DiskDrives"), host, user, passwd)
                    logical_links  += _get_links(lks.get("LogicalDrives"), host, user, passwd)
                    logical_links  += _get_links(lks.get("Volumes"), host, user, passwd)
                    
                    # Rutas OEM (HPE SmartStorage / iLO 4)
                    oem = ctrl.get("Oem", {})
                    oem_hpe = oem.get("Hp", {}) or oem.get("Hpe", {})
                    if isinstance(oem_hpe, dict):
                        lks_oem = oem_hpe.get("Links", {})
                        physical_links += _get_links(lks_oem.get("PhysicalDrives"), host, user, passwd, session)
                        logical_links  += _get_links(lks_oem.get("LogicalDrives"), host, user, passwd, session)

                    # Deduplicar links
                    physical_links = list(dict.fromkeys(physical_links))
                    logical_links = list(dict.fromkeys(logical_links))
                    
                    all_drives_data = {} # @odata.id -> data
                    
                    # 2. Obtener DATA de discos físicos
                    used_drive_links = set()
                    for dl in physical_links:
                        try:
                            d = ilo_get(dl, host, user, passwd, session=session)
                            if not d: continue
                            
                            # Normalizar data del disco
                            bv = d.get("CapacityBytes")
                            if bv is None:
                                mv = d.get("CapacityMiB")
                                if mv: bv = mv * 1024 * 1024
                            if not bv:
                                gb = d.get("CapacityGB")
                                if gb is not None: bv = float(gb) * 1e9
                            
                            # Fallback Regex
                            if not bv:
                                text = f"{d.get('Name','')} {d.get('Model','')} {d.get('Description','')}"
                                match = re.search(r"(\d+)\s*(GB|TB|GiB|TiB)", text, re.I)
                                if match:
                                    val, unit = int(match.group(1)), match.group(2).upper()
                                    bv = val * (1e12 if "T" in unit else 1e9)
                            
                            # ✨ Especial iLO 4: Extraer capacidad del número de modelo (ej. MK000960 -> 960GB)
                            # Si bv es muy bajo (menos de 1GB) o nulo, usamos el modelo
                            if not bv or bv < 1e9:
                                model_str = d.get("Model") or d.get("Name") or ""
                                # Busca patrones como "0960G" o "1.2T" en el modelo
                                m2 = re.search(r"[A-Z]{2}0*(\d{2,4})G[A-Z]", model_str)
                                if m2:
                                    bv = int(m2.group(1)) * 1e9
                                else:
                                    m3 = re.search(r"(\d+\.?\d*)\s*(GB|TB)", model_str, re.I)
                                    if m3:
                                        val, unit = float(m3.group(1)), m3.group(2).upper()
                                        bv = val * (1e12 if "T" in unit else 1e9)

                            drive_obj = {
                                "id": dl,
                                "name": d.get("Name") or d.get("Id") or f"Disk {dl.split('/')[-1]}",
                                "model": d.get("Model") or d.get("Manufacturer") or "N/A",
                                "capacity_gb": round((bv or 0) / 1e9, 1),
                                "type": d.get("MediaType") or d.get("Protocol") or "N/A",
                                "health": d.get("Status", {}).get("Health") or "OK",
                                "slot": d.get("PhysicalLocation",{}).get("PartLocation",{}).get("ServiceLabel") or d.get("Location")
                            }
                            all_drives_data[dl] = drive_obj
                        except: continue

                    # 3. Obtener DATA de volúmenes y agrupar
                    groups = []
                    for vl in logical_links:
                        try:
                            v = ilo_get(vl, host, user, passwd, session=session)
                            if not v or v.get("VolumeType") == "RawDevice": continue
                            
                            v_drives = []
                            v_drive_links = _get_links(v.get("Links", {}).get("Drives"), host, user, passwd, session)
                            for vdl in v_drive_links:
                                used_drive_links.add(vdl)
                                if vdl in all_drives_data:
                                    v_drives.append(all_drives_data[vdl])
                            
                            groups.append({
                                "name": v.get("Name") or f"Array {v.get('Id')}",
                                "health": v.get("Status", {}).get("Health") or "OK",
                                "drives": v_drives
                            })
                        except: continue
                    
                    # 4. Discos no asignados (o si el mapeo falló)
                    unassigned = []
                    for dl, d_obj in all_drives_data.items():
                        if dl not in used_drive_links:
                            unassigned.append(d_obj)
                    
                    if unassigned:
                        groups.append({
                            "name": "Discos Independientes / No Asignados",
                            "health": "OK",
                            "drives": unassigned
                        })
                    
                    controllers.append({
                        "name": ctrl.get("Name", "Controller"),
                        "health": ctrl.get("Status", {}).get("Health") or "OK",
                        "groups": groups
                    })
                except Exception: continue
        except Exception: continue

        # Break si encontramos datos
        if any(c["groups"] for c in controllers):
            break

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
                    "name": m.get("Name") or m.get("Id") or m.get("SocketLocator"), 
                    "size_mb": m.get("CapacityMiB") or m.get("SizeMB") or 0,
                    "speed_mhz": m.get("OperatingSpeedMhz") or m.get("MaximumFrequencyMHz") or 0,
                    "type": m.get("MemoryDeviceType") or m.get("DIMMType") or "N/A",
                    "health": m.get("Status", {}).get("Health") or "OK",
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

    # ── Ejecución de Consultas ──────────────────────────────
    try:
        # Consultas SECUENCIALES para máxima estabilidad
        r = {
            "systems": _safe_get("/Systems/1",         host, user, passwd),
            "thermal": _safe_get("/Chassis/1/Thermal", host, user, passwd),
            "power":   _safe_get("/Chassis/1/Power",   host, user, passwd),
        }

        # ── Fallback para iLO 4 (Sensores de ventilación) ──
        # iLO 4 a veces no entrega lecturas en Redfish pero sí en /rest/v1
        t_obj = r["thermal"]
        fans_list = t_obj.get("Fans", [])
        active_fans = [f for f in fans_list if f.get("Status", {}).get("State") != "Absent"]
        
        has_speed = any(f.get("Reading") is not None or f.get("CurrentReading") is not None for f in active_fans)
        if active_fans and not has_speed:
            try:
                # Intentar API legacy de iLO 4
                legacy_t = _safe_get("/rest/v1/chassis/1/thermal", host, user, passwd)
                if legacy_t and legacy_t.get("Fans"):
                    r["thermal"] = legacy_t
            except Exception:
                pass
        
        if deep:
            p_storage = prev_snap.get("storage_data") if prev_snap else None
            p_memory  = prev_snap.get("memory_data")  if prev_snap else None
            r["storage"] = _fetch_storage_details(host, user, passwd, p_storage)
            r["memory"]  = _fetch_memory_details(host, user, passwd, p_memory)

        s, t, p = r["systems"], r["thermal"], r["power"]
        st = r.get("storage", [])
        me = r.get("memory", [])

        if not s or not s.get("PowerState"):
            raise ValueError("Respuesta vacía del iLO")

        # ── Extracción de Watts (Usando utilidad compartida) ──
        consumed_watts, capacity_watts = calculate_power_metrics(p)

        # ── Extracción de Temperaturas (Priorizar Inlet Ambient para Reportes) ──
        all_temps = t.get("Temperatures", [])
        inlet_temp = next((x.get("ReadingCelsius") for x in all_temps 
                           if (x.get("Name") == "01-Inlet Ambient" or x.get("MemberId") == "01-Inlet Ambient")), None)
        
        if inlet_temp is None:
            # Fallback: Máximo de sensores disponibles
            temps_raw = [x.get("ReadingCelsius") for x in all_temps 
                         if x.get("Status", {}).get("State") != "Absent" and x.get("ReadingCelsius") is not None]
            inlet_temp = max(temps_raw) if temps_raw else None
        
        fan_warn = sum(1 for f in t.get("Fans", []) 
                       if f.get("Status", {}).get("State") != "Absent" and f.get("Status", {}).get("Health") not in ("OK", None))

        # Totales para reporte e inventario
        ilo_name = s.get("HostName") or s.get("Name", "Servidor iLO")
        total_mem_gb = s.get("MemorySummary", {}).get("TotalSystemMemoryGiB", 0)

        # ── Hilos lógicos totales reales ──────────────────────────────
        total_cpu_threads = s.get("ProcessorSummary", {}).get("LogicalProcessorCount", 0)
        if not total_cpu_threads:
            # Fallback: consultar cada procesador y sumar TotalThreads
            try:
                proc_links = _get_links("/Systems/1/Processors", host, user, passwd)
                for pl in proc_links:
                    proc = _safe_get(pl, host, user, passwd)
                    total_cpu_threads += proc.get("TotalThreads", 0)
            except Exception:
                total_cpu_threads = 0

        # Calcular total de disco sumando todos los drives de todos los grupos
        total_disk_gb = 0
        for ctrl_data in st:
            for group in ctrl_data.get("groups", []):
                for drive in group.get("drives", []):
                    total_disk_gb += drive.get("capacity_gb", 0)

        # ── Detección de Generación iLO (4, 5, 6) ──────────────────
        model_raw = (s.get("Model") or "").upper().replace(" ", "").replace("-", "")
        # Intentar obtener versión real desde el firmware/OEM (más preciso)
        fw_ver = str(s.get("Oem", {}).get("Hpe", {}).get("iLOVersion", "") or s.get("Oem", {}).get("Hp", {}).get("iLOVersion", "")).lower()
        
        ilo_gen = 5 # Default base
        
        if "ilo 4" in fw_ver:
            ilo_gen = 4
        elif "ilo 6" in fw_ver:
            ilo_gen = 6
        elif "ilo 5" in fw_ver:
            ilo_gen = 5
        else:
            # Fallback por Modelo si el firmware no lo dice explícitamente
            if "GEN8" in model_raw or "GEN9" in model_raw:
                ilo_gen = 4
            elif "GEN11" in model_raw:
                ilo_gen = 6
            elif "GEN10" in model_raw:
                ilo_gen = 5
            
        # Fallback heurístico adicional para hardware muy antiguo
        if ilo_gen == 5 and not s.get("UUID") and "GEN" in model_raw:
            ilo_gen = 4

        return {
            "server_id":      srv["id"],
            "server_label":   srv["label"],
            "server_host":    host,
            "ilo_name":       ilo_name,
            "ilo_gen":        ilo_gen,
            "total_mem_gb":   total_mem_gb,
            "total_storage_gb": round(total_disk_gb, 1),
            "total_cpu_threads": total_cpu_threads,
            "reachable":      True,
            "health":         s.get("Status", {}).get("Health"),
            "health_rollup":  s.get("Status", {}).get("HealthRollup"),
            "power_state":    s.get("PowerState"),
            "consumed_watts": consumed_watts,
            "capacity_watts": capacity_watts,
            "max_temp_c":     inlet_temp,

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
            "details": f"El servidor cambió de estado: {prev_power} -> {curr_power}.",
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

    status_col, hist_col, events_col = get_status_actual(), get_historial(), get_events()

    t_start = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        # Pasamos el estado previo a poll_server para permitir persistencia de datos
        def poll_wrapper(srv):
            st = time.time()
            with _lock:
                prev = _prev_states.get(srv["id"], {})
            res = poll_server(srv, deep=True, prev_snap=prev.get("full_snap"))
            dur = time.time() - st
            logger.info(f"  -> [{srv['label']}] Polling finalizado en {dur:.2f}s")
            return res
        
        results = list(ex.map(poll_wrapper, servers))

    # Actualizamos el timestamp exacto tras finalizar todo el polling
    now = datetime.now(timezone.utc)

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
                            ev_copy["timestamp"] = serialize_date(ev_copy["timestamp"])
                            _socketio.emit('new_alert', ev_copy, namespace='/')
                        except Exception as ex_emit:
                            logger.error(f"Error emitiendo socket: {ex_emit}")
                    
                    if ev["severity"] == "Critical":
                        logger.critical(f"ALERTA CRÍTICA: {ev['server_label']} - {ev['details']}")
            
            _prev_states[srv_id] = {
                "reachable":        snap["reachable"],
                "health":           snap.get("health"),
                "power_state":      snap.get("power_state"),
                "fan_warn":         snap.get("fan_warn", 0),
                "last_history_time": snap_save_time,
                "full_snap":        snap if snap.get("reachable") else prev.get("full_snap")
            }

    total_dur = time.time() - t_start
    logger.info(f"[OK] Ciclo de monitoreo completado. Duración total: {total_dur:.2f}s.")

    # Emitir señal de fin de ciclo para refresco de UI en tiempo real
    if _socketio:
        # Buscamos el timestamp más reciente real en la base de datos para informar al frontend
        latest_snap = status_col.find_one(sort=[("timestamp", -1)])
        latest_ts = latest_snap["timestamp"] if latest_snap else now
        
        # Construir lista de resúmenes para empujar al frontend y evitar consultas extra
        summaries = [format_server_summary(s) for s in results if s.get("reachable")]

        _socketio.emit('fleet_update', {
            "timestamp": serialize_date(latest_ts),
            "summaries": summaries,
            "any_reachable": any(s.get("reachable") for s in results)
        }, namespace='/')


def _monitor_loop():
    """Bucle infinito del hilo daemon."""
    while True:
        try: 
            run_cycle()
        except Exception as e: 
            logger.error(f"Error fatal en ciclo: {e}", exc_info=True)
        time.sleep(POLL_INTERVAL)


def start_monitor(socketio_instance=None):
    """Arranca el hilo daemon de monitoreo."""
    global _socketio
    _socketio = socketio_instance
    t = threading.Thread(target=_monitor_loop, name="ilo-monitor", daemon=True)
    t.start()
    logger.info(f"Hilo iniciado (SocketIO {'Activado' if _socketio else 'Desactivado'}). Polling: {POLL_INTERVAL}s.")
