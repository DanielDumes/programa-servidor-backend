from db import get_status_actual
col = get_status_actual()
snap = col.find_one({'server_host': '10.11.12.18'})
if snap:
    t = snap.get('thermal_raw', {})
    for x in t.get('Temperatures', []):
        if x.get('Status', {}).get('State') != 'Absent':
             print(f"Name: {x.get('Name'):<25} | PC: {x.get('PhysicalContext'):<15} | W: {x.get('UpperThresholdNonCritical'):<5} | C: {x.get('UpperThresholdCritical'):<5}")
else:
    print("Server not found")
