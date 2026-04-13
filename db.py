"""
db.py — Conexión central a MongoDB
Colecciones:
  - servers       : lista de servidores iLO
  - status_actual  : ÚLTIMO estado conocido de cada servidor (se actualiza cada 30-60s)
  - historial     : snapshots históricos (se guarda por cambio o cada 1 hora)
  - events        : log de cambios detectados (alertas)
"""
from pymongo import MongoClient, ASCENDING, DESCENDING
from config import MONGO_URI, DB_NAME

_client = None


def get_db():
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client[DB_NAME]


def get_servers_col():
    col = get_db()["servers"]
    # Índice único en el campo id (entero) para queries rápidas
    col.create_index([("id", ASCENDING)], unique=True)
    return col


def get_status_actual():
    """Retorna la colección que guarda el último estado de cada servidor."""
    col = get_db()["status_actual"]
    col.create_index([("server_id", ASCENDING)], unique=True)
    return col


def get_historial():
    """Retorna la colección de histórico (antes snapshots)."""
    col = get_db()["historial"]
    col.create_index([("timestamp", DESCENDING)])
    col.create_index([("server_id", ASCENDING), ("timestamp", DESCENDING)])
    return col


def get_snapshots():
    # Alias para compatibilidad con código anterior o frontend
    return get_historial()


def get_events():
    col = get_db()["events"]
    col.create_index([("timestamp", DESCENDING)])
    col.create_index([("server_id", ASCENDING), ("timestamp", DESCENDING)])
    return col
