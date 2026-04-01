from db import get_servers_col
import json

def list_id():
    col = get_servers_col()
    for s in col.find():
        print(f"ID: {s.get('id')} - Label: {s.get('label')}")

if __name__ == "__main__":
    list_id()
