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
            return [obj["@odata.id"]]
    return []

print(f"--- STORAGE STRUCTURE 10.11.12.7 ---")
try:
    ctrl_coll = ilo_get("/Systems/1/Storage", srv["host"], srv["user"], srv["pass"])
    for m_link in get_real_links(ctrl_coll):
        ctrl = ilo_get(m_link, srv["host"], srv["user"], srv["pass"])
        print(f"\nController: {ctrl.get('Name')} ({m_link})")
        
        # Volumes (Logical Drives)
        v_links = get_real_links(ctrl.get("Volumes"))
        print(f"  Volumes found: {len(v_links)}")
        for vl in v_links:
            v_data = ilo_get(vl, srv["host"], srv["user"], srv["pass"])
            v_name = v_data.get("Name") or v_data.get("Id")
            print(f"    [Volume] {v_name} ({vl})")
            
            # Physical Drives for this volume
            p_links = get_real_links(v_data.get("Links", {}).get("Drives"))
            print(f"      Mapped Physical Drives: {len(p_links)}")
            for pl in p_links:
                print(f"        -> {pl}")
        
        # All Physical Drives (to see if some are unassigned)
        all_p_links = get_real_links(ctrl.get("Drives"))
        print(f"  Total Physical Drives: {len(all_p_links)}")
        for pl in all_p_links:
            # We don't fetch all of them to save time, unless they are or aren't in volumes
            pass

except Exception as e:
    import traceback
    traceback.print_exc()
