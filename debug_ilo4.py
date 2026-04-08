import json
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from storage import load_servers
from ilo import ilo_get

TARGET_IP = "10.11.12.2"
PATHS = [
    "/Chassis/1/Thermal",
    "/Systems/1",
    "/Systems/1/Memory",
    "/Systems/1/SmartStorage",
    "/Systems/1/SmartStorage/ArrayControllers",
]

def run_debug():
    print(f"--- DIAGNÓSTICO PROFUNDO iLO 4: {TARGET_IP} ---")
    servers = load_servers()
    srv = next((s for s in servers if s["host"] == TARGET_IP), None)
    if not srv: return

    results = {}
    for path in PATHS:
        print(f"Consultando {path}...", end=" ", flush=True)
        try:
            data = ilo_get(path, srv["host"], srv["user"], srv["pass"])
            results[path] = data
            print("OK")
            
            # Exploración recursiva de miembros
            if isinstance(data, dict) and "Members" in data:
                for member in data["Members"]:
                    m_path = member.get("@odata.id", "").replace("/redfish/v1", "")
                    if m_path:
                        print(f"  -> Explorando {m_path}...", end=" ", flush=True)
                        m_data = ilo_get(m_path, srv["host"], srv["user"], srv["pass"])
                        results[m_path] = m_data
                        print("OK")
                        
                        # Si es una controladora, buscar sus discos
                        if "/ArrayControllers/" in m_path:
                            # Intentar varias sub-rutas típicas de iLO 4
                            for sub in ["DiskDrives", "LogicalDrives", "PhysicalDrives"]:
                                s_path = f"{m_path.rstrip('/')}/{sub}"
                                print(f"    -> Buscando {sub}...", end=" ", flush=True)
                                try:
                                    s_data = ilo_get(s_path, srv["host"], srv["user"], srv["pass"])
                                    results[s_path] = s_data
                                    print("OK")
                                    # Entrar en cada disco
                                    if "Members" in s_data:
                                        for d_member in s_data["Members"]:
                                            d_path = d_member.get("@odata.id", "").replace("/redfish/v1", "")
                                            print(f"      -> Disco {d_path}...", end=" ", flush=True)
                                            results[d_path] = ilo_get(d_path, srv["host"], srv["user"], srv["pass"])
                                            print("OK")
                                except: print("NO")

        except Exception as e:
            print(f"FALLÓ ({e})")

    with open(f"debug_ilo4_{TARGET_IP.replace('.', '_')}.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print("\n--- DIAGNÓSTICO COMPLETADO ---")

if __name__ == "__main__":
    run_debug()
