from db import get_servers_col
from ilo import ilo_get
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def debug_storage():
    col = get_servers_col()
    servers = list(col.find())
    print(f"Found {len(servers)} servers in DB.\n")
    
    paths = ["/Systems/1/Storage", "/Systems/1/SmartStorage", "/Chassis/1/Drives"]
    
    for srv in servers:
        print(f"=== SERVER: {srv.get('label')} ({srv.get('host')}) ===")
        host, user, passwd = srv.get('host'), srv.get('user'), srv.get('pass')
        
        for p in paths:
            try:
                data = ilo_get(p, host, user, passwd, retries=0)
                members = data.get("Members", [])
                print(f" Path {p}: {len(members)} members found.")
                for m in members:
                    m_url = m.get("@odata.id", "").replace("/redfish/v1", "")
                    try:
                        m_data = ilo_get(m_url, host, user, passwd, retries=0)
                        drives = m_data.get("Drives", [])
                        l_drives = m_data.get("Links", {}).get("Drives", [])
                        vols = m_data.get("Volumes", {}).get("Members", [])
                        l_vols = m_data.get("Links", {}).get("LogicalDrives", [])
                        
                        print(f"   Member {m_url}:")
                        print(f"     Drives: {len(drives)}")
                        print(f"     Links/Drives: {len(l_drives)}")
                        print(f"     Volumes/Members: {len(vols)}")
                        print(f"     Links/LogicalDrives: {len(l_vols)}")
                        
                        # Si hay algo pero no carga en la app, imprimamos una unidad de ejemplo
                        target = drives or l_drives or vols or l_vols
                        if target:
                            t_url = target[0].get("@odata.id", "").replace("/redfish/v1", "")
                            t_data = ilo_get(t_url, host, user, passwd, retries=0)
                            print(f"     SAMPLE COMPONENT ({t_url}):")
                            print(f"       Name: {t_data.get('Name')}")
                            print(f"       Cap (Bytes): {t_data.get('CapacityBytes')}")
                            print(f"       Cap (MiB): {t_data.get('CapacityMiB')}")
                    except Exception as e:
                        print(f"   Member {m_url} Error: {e}")
            except Exception as e:
                # print(f" Path {p} Error: {e}")
                pass
        print("-" * 50)

if __name__ == "__main__":
    debug_storage()
