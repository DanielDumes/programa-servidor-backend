import os
import sys
from datetime import datetime

# Add current dir to sys.path to find monitor
sys.path.append(os.getcwd())

from monitor import poll_server
from db import get_servers_col, get_status_actual

def test():
    col = get_servers_col()
    from storage import _decrypt_doc
    srv_raw = col.find_one({"id": 10}) # Servidor de ejemplo
    if not srv_raw:
        print("Servidor 10 no encontrado")
        return
    srv = _decrypt_doc(srv_raw)
    
    print(f"Probando Deep Poll para {srv['label']} ({srv['host']})...")
    snap = poll_server(srv, deep=True)
    
    if not snap.get("reachable"):
        print(f"Error: {snap.get('error')}")
        return
        
    snap["timestamp"] = datetime.now()
    get_status_actual().replace_one({"server_id": srv["id"]}, snap, upsert=True)
    
    storage = snap.get("storage_data", [])
    print(f"Poll finalizado. Controladores encontrados: {len(storage)}")
    for c in storage:
        print(f"  - {c['name']}: {len(c.get('drives', []))} discos")

if __name__ == "__main__":
    test()
