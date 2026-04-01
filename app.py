from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO
from routes.servers import bp as servers_bp
from routes.metrics import bp as metrics_bp
from routes.reports import bp as reports_bp

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

app.register_blueprint(servers_bp)
app.register_blueprint(metrics_bp)
app.register_blueprint(reports_bp)

# ── RUTA DE PRUEBA (SIMULACIÓN DE ALERTA) ──────────────────
@app.get("/api/test-alert")
def trigger_test_alert():
    from datetime import datetime
    test_ev = {
        "server_id": 999,
        "server_label": "SERVIDOR TEST (PRUEBA)",
        "type": "HealthDegradation",
        "severity": "Critical",
        "details": "Fallo simulado de Disco Duro - Sector Crítico 0x00FF8",
        "timestamp": datetime.now().isoformat()
    }
    socketio.emit('new_alert', test_ev, namespace='/')
    return {"ok": True, "message": "Alerta de prueba enviada al Dashboard"}


def migrate_json_to_mongo():
    """
    Migración única: si MongoDB no tiene servidores pero servers.json existe,
    importa todos los registros a MongoDB y renombra el JSON como respaldo.
    """
    import os
    import json
    from db import get_servers_col
    from config import SERVERS_FILE

    try:
        col = get_servers_col()
        if col.count_documents({}) > 0:
            print("[Migración] MongoDB ya tiene servidores — saltando migración.")
            return

        if not os.path.exists(SERVERS_FILE):
            print("[Migración] No hay servers.json — nada que migrar.")
            return

        with open(SERVERS_FILE, "r") as f:
            servers = json.load(f)

        if not servers:
            print("[Migración] servers.json está vacío — nada que migrar.")
            return

        col.insert_many(servers)
        print(f"[Migración] ✓ {len(servers)} servidor(es) importados desde servers.json a MongoDB.")

        # Renombrar el JSON como respaldo (no lo borramos por seguridad)
        backup_path = SERVERS_FILE + ".bak"
        os.rename(SERVERS_FILE, backup_path)
        print(f"[Migración] servers.json renombrado a servers.json.bak como respaldo.")

    except Exception as e:
        print(f"[Migración] ERROR durante migración: {e}")


if __name__ == "__main__":
    migrate_json_to_mongo()

    # Arranca el monitor de fondo (pasamos socketio para alertas real-time)
    from monitor import start_monitor
    start_monitor(socketio)

    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)