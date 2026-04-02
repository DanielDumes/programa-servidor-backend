from db import get_servers_col
from ilo import ilo_get
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def dump_controller_json(host, user, passwd):
    path = "/Systems/1/Storage"
    res = ilo_get(path, host, user, passwd, retries=0)
    if "Members" in res and res["Members"]:
        m_path = res["Members"][0]["@odata.id"].replace("/redfish/v1", "")
        print(f"Dumping JSON for {m_path}...")
        m_data = ilo_get(m_path, host, user, passwd, retries=0)
        print(json.dumps(m_data, indent=2))

if __name__ == "__main__":
    col = get_servers_col()
    srv = col.find_one({"host": "10.11.12.8"})
    if srv:
        dump_controller_json(srv['host'], srv['user'], srv['pass'])
