from db import get_servers_col
from ilo import ilo_get
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def debug_storage_deep(host, user, passwd):
    print(f"Deep Debug for {host}...")
    paths = ["/Systems/1/Storage", "/Systems/1/SmartStorage"]
    for p in paths:
        try:
            print(f"\nChecking Path: {p}")
            data = ilo_get(p, host, user, passwd, retries=0)
            members = data.get("Members", [])
            print(f"Found {len(members)} members.")
            for m in members:
                m_url = m.get("@odata.id", "").replace("/redfish/v1", "")
                print(f"  Fetching Member: {m_url}")
                m_data = ilo_get(m_url, host, user, passwd, retries=0)
                # print(json.dumps(m_data, indent=2)) # To see the full structure
                
                # Check for Drives, Volumes, etc.
                drives = m_data.get("Drives", [])
                l_drives = m_data.get("Links", {}).get("Drives", [])
                vols = m_data.get("Volumes", {}).get("Members", [])
                l_vols = m_data.get("Links", {}).get("LogicalDrives", [])
                
                print(f"    - Drives (direct): {len(drives)}")
                print(f"    - Drives (links): {len(l_drives)}")
                print(f"    - Volumes (members): {len(vols)}")
                print(f"    - Volumes (links): {len(l_vols)}")
                
                # Pick one from any that have items
                for items, label in [(drives, "Drives (direct)"), (l_drives, "Drives (links)"), (vols, "Volumes (members)")]:
                    if items:
                        t_link = items[0].get("@odata.id", "")
                        print(f"    Testing first {label} link: {t_link}")
                        if t_link:
                            t_data = ilo_get(t_link.replace("/redfish/v1", ""), host, user, passwd, retries=0)
                            print(f"      Data for {t_link}:")
                            print(f"        Name: {t_data.get('Name')}")
                            print(f"        CapacityBytes: {t_data.get('CapacityBytes')}")
                            print(f"        CapacityMiB: {t_data.get('CapacityMiB')}")
                            print(f"        Status: {t_data.get('Status')}")
        except Exception as e:
            print(f"Error checking {p}: {e}")

if __name__ == "__main__":
    col = get_servers_col()
    srv = col.find_one({"host": "10.11.12.8"}) # Focusing on SRV-3 which responded before
    if srv:
        debug_storage_deep(srv['host'], srv['user'], srv['pass'])
    else:
        print("SRV-3 not found.")
