import os
from datetime import timezone, timedelta
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

# Tiempos de conexión
ILO_TIMEOUT = int(os.getenv("ILO_TIMEOUT", 5))

# Configuración de zona horaria (Ecuador por defecto: -5)
TIMEZONE_OFFSET = int(os.getenv("TIMEZONE_OFFSET", -5))
EC_TZ = timezone(timedelta(hours=TIMEZONE_OFFSET))

# Configuración de monitoreo
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 15))
HISTORY_SNAPSHOT_INTERVAL = int(os.getenv("HISTORY_SNAPSHOT_INTERVAL", 3600))

# Servidor Flask
PORT = int(os.getenv("PORT", 5000))

# Logs
LOG_FILE = os.getenv("LOG_FILE", "monitor.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Base de Datos
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "ilo_monitor")