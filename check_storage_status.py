from db import get_status_actual, get_servers_col
import json

def check_missing_storage():
    status_col = get_status_actual()
    snaps = list(status_col.find())
    
    for snap in snaps:
        sid = snap.get('server_id')
        label = snap.get('server_label', 'N/A')
        host = snap.get('server_host', 'N/A')
        storage_gb = snap.get('total_storage_gb', 0)
        reachable = snap.get('reachable', False)
        
        if reachable and (storage_gb == 0 or not snap.get('storage_data')):
            print(f"ID {sid}: {label} ({host}) is missing storage!")
        else:
            print(f"ID {sid}: {label} ({host}) has {storage_gb} GB")

if __name__ == "__main__":
    check_missing_storage()
