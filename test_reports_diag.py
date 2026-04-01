import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:5000/api"

def test_endpoint(path):
    print(f"Testing {path}...")
    try:
        response = requests.get(f"{BASE_URL}{path}")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Success! Data keys: {list(data.keys())}")
            return True
        else:
            print(f"Error: {response.text}")
            return False
    except Exception as e:
        print(f"Connection error: {e}")
        return False

if __name__ == "__main__":
    # Test common report endpoints
    test_endpoint("/reports/history")
    test_endpoint("/reports/weekly")
    test_endpoint("/reports/hourly")
    test_endpoint("/reports/metrics")
