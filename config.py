import os
from datetime import timezone, timedelta

ILO_TIMEOUT  = 5

# Configuración de zona horaria (Ecuador por defecto)
TIMEZONE_OFFSET = -5
EC_TZ = timezone(timedelta(hours=TIMEZONE_OFFSET))

# Configuración de monitoreo de alta frecuencia
POLL_INTERVAL = 15  # segundos
HISTORY_SNAPSHOT_INTERVAL = 3600  # cada 1 hora se guarda snapshot forzoso

# Logs
LOG_FILE = "monitor.log"
LOG_LEVEL = "INFO"