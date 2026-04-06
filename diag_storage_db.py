"""
diag_storage_db.py
Diagnóstico rápido: inspecciona qué está guardado en MongoDB para storage_data
de cada servidor, sin hacer ninguna petición al iLO.

Ejecutar: python diag_storage_db.py
"""
from db import get_status_actual, get_servers_col
import json

def main():
    status_col = get_status_actual()
    servers_col = get_servers_col()

    servers = list(servers_col.find({}, {"_id": 0, "id": 1, "label": 1, "host": 1}))
    snaps   = {s["server_id"]: s for s in status_col.find({}, {"_id": 0})}

    print("=" * 70)
    print(f"{'ID':>3}  {'Label':<20}  {'Host':<16}  {'Storage':<30}  {'Ctrl'}")
    print("=" * 70)

    for srv in sorted(servers, key=lambda x: x.get("id", 0)):
        sid   = srv["id"]
        label = srv.get("label", "?")
        host  = srv.get("host",  "?")
        snap  = snaps.get(sid)

        if not snap:
            print(f"{sid:>3}  {label:<20}  {host:<16}  ⚠ Sin snapshot en DB")
            continue

        if not snap.get("reachable", False):
            print(f"{sid:>3}  {label:<20}  {host:<16}  ✗ Servidor OFFLINE/Unreachable")
            continue

        storage = snap.get("storage_data")

        if storage is None:
            print(f"{sid:>3}  {label:<20}  {host:<16}  ✗ storage_data = None (no se guardó)")
        elif storage == []:
            print(f"{sid:>3}  {label:<20}  {host:<16}  ✗ storage_data = [] (vacío)")
        else:
            # Detallar cada controlador
            for ci, ctrl in enumerate(storage):
                drives = ctrl.get("drives", [])
                ctrl_name = ctrl.get("name", f"Controller {ci}")
                health = ctrl.get("health", "?")
                # Capacidad total
                total_gb = sum(d.get("capacity_gb", 0) for d in drives)
                line = (f"{sid:>3}  {label:<20}  {host:<16}  "
                        f"✓ {ctrl_name[:28]:<28}  {len(drives)} drives / {total_gb:.0f} GB  [{health}]")
                print(line)
                for d in drives:
                    print(f"     └─ {d.get('name','?'):<15}  {d.get('type','?'):<5}  "
                          f"{d.get('capacity_gb',0):.1f} GB  {d.get('health','?')}")

    print("=" * 70)
    print("\nSi aparece '✗ storage_data = []' es porque el poll de almacenamiento")
    print("no encontró ningún controlador en '/Systems/1/Storage' ni '/Systems/1/SmartStorage'.")
    print("Ejecuta debug_storage_deep.py apuntando al servidor problemático para ver por qué.\n")

if __name__ == "__main__":
    main()
