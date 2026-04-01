from ilo import ilo_get
from storage import load_servers
import json

def test_server_storage(server_id):
    servers = load_servers()
    srv = next((s for s in servers if s['id'] == server_id), None)
    if not srv:
        print(f"Error: Server {server_id} not found in DB")
        return

    host, user, passwd = srv['host'], srv['user'], srv['pass']
    print(f"Testing Storage for {srv['label']} ({host})...")
    
    paths = [
        "/Systems/1/Storage",
        "/Systems/1/SmartStorage",
        "/Chassis/1/Drives"
    ]
    
    for path in paths:
        print(f"\n--- Checking path: {path} ---")
        try:
            res = ilo_get(path, host, user, passwd)
            print(f"Success! Found {len(res.get('Members', []))} members or data returned.")
            # Print a snippet of the result
            print(json.dumps(res, indent=2)[:500] + "...")
            
            if "Members" in res:
                for member in res["Members"]:
                    m_path = member.get("@odata.id", "")
                    print(f"  Member: {m_path}")
                    try:
                        m_data = ilo_get(m_path.replace("/redfish/v1", ""), host, user, passwd)
                        if "Drives" in m_data:
                            print(f"    Has {len(m_data['Drives'])} drives.")
                        if "Links" in m_data and "Drives" in m_data["Links"]:
                             print(f"    Has {len(m_data['Links']['Drives'])} drives in Links.")
                    except:
                        pass
        except Exception as e:
            print(f"Failed: {e}")

if __name__ == "__main__":
    import sys
    sid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    test_server_storage(sid)
