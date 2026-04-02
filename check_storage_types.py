from db import get_servers_col
from ilo import ilo_get
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def check_keys(host, user, passwd):
    path = "/Systems/1/Storage"
    res = ilo_get(path, host, user, passwd, retries=0)
    for member in res.get("Members", []):
        m_path = member["@odata.id"].replace("/redfish/v1", "")
        print(f"\nAnalyzing Controller: {m_path}")
        ctrl = ilo_get(m_path, host, user, passwd, retries=0)
        
        for key in ["Drives", "Volumes"]:
            val = ctrl.get(key)
            if val:
                print(f" Key '{key}' exists. Type: {type(val).__name__}")
                if isinstance(val, dict):
                    print(f"   Has 'Members': {'Members' in val}")
                    if 'Members' in val:
                        print(f"   Members Count: {len(val['Members'])}")
                elif isinstance(val, list):
                    print(f"   List Count: {len(val)}")

        if "Links" in ctrl:
            for key in ["Drives", "LogicalDrives", "PhysicalDrives"]:
                val = ctrl["Links"].get(key)
                if val:
                    print(f" Links['{key}'] exists. Type: {type(val).__name__}")
                    if isinstance(val, list):
                        print(f"   List Count: {len(val)}")

if __name__ == "__main__":
    col = get_servers_col()
    srv = col.find_one({"host": "10.11.12.8"})
    if srv:
        check_keys(srv['host'], srv['user'], srv['pass'])
