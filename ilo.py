import requests
import urllib3
from functools import wraps
from flask import jsonify
from config import ILO_TIMEOUT

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def ilo_get(path, host, user, passwd, retries=2, session=None):
    url = f"https://{host}/redfish/v1{path}"
    last_err = None
    getter = session.get if session else requests.get
    
    # Si la sesión ya tiene auth configurado, no lo pasamos en el get para evitar conflictos
    current_auth = (user, passwd) if not (session and session.auth) else None
    
    for i in range(retries + 1):
        try:
            resp = getter(
                url,
                auth=current_auth,
                verify=False,
                timeout=ILO_TIMEOUT,
                headers={"Accept": "application/json", "OData-Version": "4.0"}
            )
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            last_err = e
            if i < retries:
                import time
                time.sleep(1) # Pequeña espera antes de reintentar
                continue
    # Si llegamos aquí, fallaron todos los intentos
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