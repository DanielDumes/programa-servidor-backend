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
    from datetime import datetime, timezone
    from utils import serialize_date
    test_ev = {
        "server_id": 999,
        "server_label": "SERVIDOR TEST (PRUEBA)",
        "type": "HealthDegradation",
        "severity": "Critical",
        "details": "Fallo simulado de Disco Duro - Sector Crítico 0x00FF8",
        "timestamp": serialize_date(datetime.now(timezone.utc))
    }
    socketio.emit('new_alert', test_ev, namespace='/')
    return {"ok": True, "message": "Alerta de prueba enviada al Dashboard"}


if __name__ == "__main__":
    from logger import logger
    from monitor import start_monitor
    from config import PORT
    
    logger.info(f"Iniciando backend en el puerto {PORT}...")
    
    # Arranca el monitor de fondo
    start_monitor(socketio)

    socketio.run(app, host="0.0.0.0", port=PORT, allow_unsafe_werkzeug=True)