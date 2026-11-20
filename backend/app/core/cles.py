"""Derivation de cles a usage unique depuis SECRET_KEY.

Chaque usage (scelle d'audit, chiffrement des secrets de double
authentification...) a sa propre cle : la compromission d'un usage ne donne
pas les autres. Changer SECRET_KEY invalide les scelles signes et oblige a
reconfigurer la double authentification.
"""

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings


def deriver_cle(usage: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"barryson-erp",
        info=usage.encode("utf-8"),
    ).derive(get_settings().secret_key.encode("utf-8"))
