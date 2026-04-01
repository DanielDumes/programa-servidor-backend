"""
crypto.py — Cifrado simétrico con Fernet (AES-128-CBC + HMAC)
La clave maestra se genera automáticamente en ilo_master.key la primera vez.

⚠ IMPORTANTE: No subas ilo_master.key al repositorio (add al .gitignore).
   Si pierdes la clave, los usuarios/contraseñas almacenados NO son recuperables.
"""
import os
from cryptography.fernet import Fernet

# Ruta del archivo de clave maestra (junto al backend)
KEY_FILE = os.path.join(os.path.dirname(__file__), "ilo_master.key")

_fernet = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet

    if not os.path.exists(KEY_FILE):
        # Primera ejecución: generar y guardar clave nueva
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
        print(f"[Crypto] ✓ Clave maestra generada y guardada en: {KEY_FILE}")
        print(f"[Crypto] ⚠ Guarda este archivo en un lugar seguro. Sin él no podrás descifrar las credenciales.")
    else:
        with open(KEY_FILE, "rb") as f:
            key = f.read()

    _fernet = Fernet(key)
    return _fernet


def encrypt(plain: str) -> str:
    """Cifra un texto y devuelve el token como string."""
    if not plain:
        return plain
    return _get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    """Descifra un token y devuelve el texto original."""
    if not token:
        return token
    return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")


def is_encrypted(value: str) -> bool:
    """
    Detecta si un valor ya está cifrado (empieza con 'gAAA...').
    Útil para la migración donde los valores pueden ser texto plano o cifrado.
    """
    try:
        _get_fernet().decrypt(value.encode("utf-8"))
        return True
    except Exception:
        return False
