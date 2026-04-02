from db import get_servers_col
from monitor import poll_server
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def debug_poll(host):
    col = get_servers_col()
    srv = col.find_one({"host": host})
    if not srv:
        print(f"Server {host} not found.")
        return
    
    print(f"Polling {srv['label']} ({host})...")
    # No pasamos prev_snap para forzar carga fresca
    snap = poll_server(srv, deep=True)
    
    print("\n--- POLL RESULT ---")
    print(f"Reachable: {snap['reachable']}")
    print(f"Total Storage GB: {snap.get('total_storage_gb')}")
    print(f"Total Mem GB: {snap.get('total_mem_gb')}")
    
    print("\n--- STORAGE DATA ---")
    st = snap.get("storage_data", [])
    print(json.dumps(st, indent=2))
    
    print("\n--- MEMORY DATA ---")
    me = snap.get("memory_data", [])
    print(f"Count: {len(me)}")
    for m in me:
        print(f"  {m['name']}: {m['size_mb']} MiB - {m['health']}")

if __name__ == "__main__":
    import sys
    host = sys.argv[1] if len(sys.argv) > 1 else "10.11.12.8"
    debug_poll(host)
