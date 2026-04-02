import requests
import json
import urllib3
from ilo import ilo_get

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def test_session(host, user, passwd):
    print(f"Testing session for {host}...")
    with requests.Session() as s:
        try:
            # 1. First request
            data1 = ilo_get("/Systems/1", host, user, passwd, session=s)
            print(f"Request 1 (/Systems/1) Success. PowerState: {data1.get('PowerState')}")
            
            # 2. Second request
            data2 = ilo_get("/Systems/1/Memory", host, user, passwd, session=s)
            print(f"Request 2 (/Systems/1/Memory) Success. Members: {len(data2.get('Members', []))}")
        except Exception as e:
            print(f"Session test failed: {e}")

if __name__ == "__main__":
    test_session("10.11.12.8", "pasante_tics", "pasante_tics_2024") # Estimating creds based on typical iLO setups here
    # Actually I should use the real ones from DB
    from db import get_servers_col
    srv = get_servers_col().find_one({"host": "10.11.12.8"})
    if srv:
        test_session(srv['host'], srv['user'], srv['pass'])
