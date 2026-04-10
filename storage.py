from db import get_servers_col
from crypto import decrypt, is_encrypted


def _decrypt_doc(doc):
    """
    Descifra user y pass de un documento MongoDB.
    Si el valor ya es texto plano (migración progresiva), lo deja como está.
    """
    d = {k: v for k, v in doc.items() if k != "_id"}
    if d.get("user"):
        d["user"] = decrypt(d["user"]) if is_encrypted(d["user"]) else d["user"]
    if d.get("pass"):
        d["pass"] = decrypt(d["pass"]) if is_encrypted(d["pass"]) else d["pass"]
    return d


def load_servers():
    """
    Devuelve lista de servidores con credenciales descifradas.
    Usado por monitor.py y routes/metrics.py para conectarse al iLO.
    """
    col = get_servers_col()
    return [_decrypt_doc(s) for s in col.find({}, {"_id": 0}).sort("id", 1)]