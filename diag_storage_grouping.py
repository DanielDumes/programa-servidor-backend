import json
from storage import load_servers
from ilo import ilo_get

servers = load_servers()
srv = next((s for s in servers if s["host"] == "10.11.12.7"), None)

if not srv:
    print("ERROR: Servidor 10.11.12.7 no encontrado")
    exit()

print(f"--- STORAGE DIAGNOSTIC 10.11.12.7 ---")
# Vamos a mirar la ruta de Storage
path = "/Systems/1/Storage"
try:
    ctrl_coll = ilo_get(path, srv["host"], srv["user"], srv["pass"])
    print(f"Controllers found: {len(ctrl_coll.get('Members', []))}")
    for m in ctrl_coll.get("Members", []):
        c_path = m["@odata.id"]
        print(f"\nListing controller: {c_path}")
        ctrl = ilo_get(c_path, srv["host"], srv["user"], srv["pass"])
        
        # Mirar Drives y Volumes
        d_links = ctrl.get("Drives", []) or ctrl.get("Links", {}).get("Drives", [])
        v_links = ctrl.get("Volumes", []) or ctrl.get("Links", {}).get("Volumes", [])
        
        print(f"  Physical Drives: {len(d_links)}")
        print(f"  Logical Volumes: {len(v_links)}")
        
        for vl in v_links:
            v_data = ilo_get(vl["@odata.id"], srv["host"], srv["user"], srv["pass"])
            print(f"    Volume: {v_data.get('Name')} | {v_data.get('Id')} | {v_data.get('VolumeType')}")
            # Ver si hay links a physical drives
            p_links = v_data.get("Links", {}).get("Drives", [])
            print(f"      Mapped Physical Drives: {len(p_links)}")
            for pl in p_links:
                print(f"        -> {pl['@odata.id']}")

except Exception as e:
    print(f"Error: {e}")
