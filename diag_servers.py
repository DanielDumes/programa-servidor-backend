from db import get_servers_col, get_status_actual
from datetime import datetime

def diag():
    all_srv = list(get_servers_col().find())
    current_snaps = {s['server_id']: s for s in get_status_actual().find()}
    
    print(f"Total Configured: {len(all_srv)}")
    print(f"Total Snapshots: {len(current_snaps)}")
    print("-" * 50)
    
    for s in all_srv:
        sid = s.get('id')
        name = s.get('label')
        host = s.get('host')
        
        snap = current_snaps.get(sid)
        if snap:
            health = snap.get('health', 'Unknown')
            reachable = snap.get('reachable', False)
            ts = snap.get('timestamp')
            status = health if reachable else "Offline"
            last_seen = ts.strftime('%Y-%m-%d %H:%M:%S') if isinstance(ts, datetime) else str(ts)
            print(f"ID {sid}: {name} ({host}) -> {status} (Last: {last_seen})")
            if not reachable:
                print(f"   ERROR: {snap.get('error')}")
        else:
            print(f"ID {sid}: {name} ({host}) -> NO SNAPSHOT FOUND")

if __name__ == '__main__':
    diag()
