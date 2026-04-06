import os
import sys
import json
from datetime import datetime

# Add current dir to sys.path to find monitor
sys.path.append(os.getcwd())

from monitor import poll_server
from storage import load_servers

def verify():
    servers = load_servers()
    # Try to find SRV-10 and SRV-16 (SATA only)
    srv10 = next((s for s in servers if s['host'] == '10.11.12.6'), None)
    srv16 = next((s for s in servers if s['host'] == '10.11.12.16'), None)
    
    for srv in [srv10, srv16]:
        if not srv: continue
        print(f"\n--- Testing Server: {srv['label']} ({srv['host']}) ---")
        snap = poll_server(srv, deep=True)
        
        if not snap.get("reachable"):
            print(f"  ✗ Unreachable: {snap.get('error')}")
            continue
            
        storage = snap.get("storage_data", [])
        print(f"  ✓ Reachable. Controllers found: {len(storage)}")
        for i, c in enumerate(storage):
            d_count = len(c.get('drives', []))
            print(f"    [{i}] {c['name']} - {d_count} drives")
            for d in c.get('drives', []):
                print(f"       └─ {d['name']} ({d['capacity_gb']} GB) [{d['health']}]")
        
        # Check if it was empty
        if not storage:
            # Let's try raw dump if empty to see why
            from ilo import ilo_get
            raw_coll = ilo_get("/Systems/1/Storage", srv['host'], srv['user'], srv['pass'])
            print(f"    Raw /Systems/1/Storage Members Count: {len(raw_coll.get('Members', []))}")
            if raw_coll.get('Members'):
                 print(f"    First Member URL: {raw_coll['Members'][0].get('@odata.id')}")

if __name__ == "__main__":
    verify()
