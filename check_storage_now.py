import sys
sys.stdout.reconfigure(encoding='utf-8')

from db import get_status_actual, get_servers_col

status_col  = get_status_actual()
servers_col = get_servers_col()

servers = list(servers_col.find({}, {"_id": 0, "id": 1, "label": 1, "host": 1}))
snaps   = {
    s["server_id"]: s
    for s in status_col.find({}, {"_id": 0, "server_id": 1, "reachable": 1, "storage_data": 1})
}

lines = ["-" * 60]
for srv in sorted(servers, key=lambda x: x.get("id", 0)):
    sid   = srv.get("id", "?")
    label = srv.get("label", "?")
    snap  = snaps.get(sid)

    if not snap:
        lines.append("ID %s (%s): SIN SNAPSHOT EN DB" % (sid, label))
        continue

    if not snap.get("reachable", False):
        lines.append("ID %s (%s): OFFLINE" % (sid, label))
        continue

    st = snap.get("storage_data")
    if st is None:
        lines.append("ID %s (%s): storage_data = None" % (sid, label))
    elif st == []:
        lines.append("ID %s (%s): storage_data = [] VACIO" % (sid, label))
    else:
        n_ctrl   = len(st)
        n_drives = sum(len(c.get("drives", [])) for c in st)
        lines.append("ID %s (%s): %d ctrl, %d drives" % (sid, label, n_ctrl, n_drives))
        for c in st:
            drives   = c.get("drives", [])
            total_gb = sum(d.get("capacity_gb", 0) for d in drives)
            lines.append("  Ctrl: %s | health: %s | total: %.0f GB" % (
                c.get("name", "?"), c.get("health", "?"), total_gb))
            for d in drives:
                lines.append("    - %-20s %s %.1f GB %s" % (
                    d.get("name", "?"), d.get("type", "?"),
                    d.get("capacity_gb", 0), d.get("health", "?")))

lines.append("-" * 60)

result = "\n".join(lines)
print(result)

# Escribir a archivo UTF-8
with open("check_storage_result.txt", "w", encoding="utf-8") as f:
    f.write(result)
print("\n[OK] Resultado guardado en check_storage_result.txt")
