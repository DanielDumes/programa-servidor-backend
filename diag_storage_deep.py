import json
from storage import load_servers
from ilo import ilo_get

servers = load_servers()
srv = next((s for s in servers if s["host"] == "10.11.12.7"), None)

if not srv:
    print("ERROR: Servidor 10.11.12.7 no encontrado")
    exit()

def get_real_links(obj):
    if not obj: return []
    if isinstance(obj, list):
        return [l["@odata.id"] if isinstance(l, dict) else l for l in obj]
    if isinstance(obj, dict):
        if "Members" in obj:
            return [l["@odata.id"] if isinstance(l, dict) else l for l in obj["Members"]]
        if "@odata.id" in obj:
            # Si es un link a una colección, tenemos que navegarla
            try:
                coll = ilo_get(obj["@odata.id"], "10.11.12.7", "pasante3", "Pasante-2025") # Hardcoding credentials from previous log if needed? No, wait.
                # Use srv credentials
                return get_real_links(coll)
            except: return [obj["@odata.id"]]
    return []

# Better way: reuse srv
host, user, passwd = srv["host"], srv["user"], srv["pass"]

print(f"--- DETAILED STORAGE ANALYSYS 10.11.12.7 ---")
try:
    # 1. Standard Storage
    ctrl_coll = ilo_get("/Systems/1/Storage", host, user, passwd)
    for ctrl_ref in ctrl_coll.get("Members", []):
        c_link = ctrl_ref["@odata.id"]
        ctrl = ilo_get(c_link, host, user, passwd)
        print(f"\nController: {ctrl.get('Name')} | {ctrl.get('Id')}")
        
        # Volumes Collection
        v_coll_link = ctrl.get("Volumes", {}).get("@odata.id")
        if v_coll_link:
            v_coll = ilo_get(v_coll_link, host, user, passwd)
            for v_ref in v_coll.get("Members", []):
                v_data = ilo_get(v_ref["@odata.id"], host, user, passwd)
                print(f"  [Volume/Array] {v_data.get('Name')} | {v_data.get('Id')} | Type: {v_data.get('VolumeType')}")
                
                # Associated Drives
                d_refs = v_data.get("Links", {}).get("Drives", [])
                print(f"    Drives in this Volume: {len(d_refs)}")
                for d_ref in d_refs:
                    d_data = ilo_get(d_ref["@odata.id"], host, user, passwd)
                    print(f"      -> {d_data.get('Name')} | {d_data.get('Id')} | Slot: {d_data.get('PhysicalLocation',{}).get('PartLocation',{}).get('ServiceLabel')}")

        # Physical Drives not in volumes?
        # That would require tracking all IDs.
        
except Exception as e:
    import traceback
    traceback.print_exc()
