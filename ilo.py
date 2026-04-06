import requests
import urllib3
from functools import wraps
from flask import jsonify
from config import ILO_TIMEOUT

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def ilo_get(path, host, user, passwd, retries=2, session=None):
    # Asegurar que el path no tenga el prefijo /redfish/v1 si ilo_get lo va a añadir
    clean_path = path if not path.startswith("/redfish/v1") else path.replace("/redfish/v1", "")
    url = f"https://{host}/redfish/v1{clean_path}"
    
    last_err = None
    kwargs = {
        "verify": False,
        "timeout": ILO_TIMEOUT,
        "headers": {"Accept": "application/json", "OData-Version": "4.0"}
    }
    
    # Si la sesión NO tiene auth configurado, o si no hay sesión, usamos auth explícito
    if not session or not session.auth:
        kwargs["auth"] = (user, passwd)
    
    getter = session.get if session else requests.get
    
    for i in range(retries + 1):
        try:
            resp = getter(url, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            last_err = e
            if i < retries:
                import time
                time.sleep(1)
                continue
    raise last_err

def handle_errors(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except requests.exceptions.ConnectionError:
            return jsonify({"error": "No se pudo conectar al iLO"}), 503
        except requests.exceptions.Timeout:
            return jsonify({"error": "Timeout al conectar"}), 504
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code
            if code == 401:
                return jsonify({"error": "Credenciales incorrectas"}), 401
            return jsonify({"error": f"HTTP {code}"}), code
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return wrapper