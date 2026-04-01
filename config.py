import os

SERVERS_FILE = os.path.join(os.path.dirname(__file__), "servers.json")
ILO_TIMEOUT  = 5

# Configuración de monitoreo de alta frecuencia
POLL_INTERVAL = 15  # segundos
HISTORY_SNAPSHOT_INTERVAL = 3600  # cada 1 hora se guarda snapshot forzoso