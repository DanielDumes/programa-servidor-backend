import requests
import urllib3
from functools import wraps
from flask import jsonify
from config import ILO_TIMEOUT

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def ilo_get(path, host, user, passwd):
    url = f"https://{host}/redfish/v1{path}"
    resp = requests.get(
        url,
        auth=(user, passwd),
        verify=False,
        timeout=ILO_TIMEOUT,
        headers={"Accept": "application/json", "OData-Version": "4.0"}
    )
    resp.raise_for_status()
    return resp.json()

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