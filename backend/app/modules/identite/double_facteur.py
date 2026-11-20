"""Codes a usage unique (TOTP, RFC 6238) : application d'authentification sur telephone.

Pas de dependance a la base ni a HTTP. Le secret est chiffre (AES-256-GCM)
avant stockage, avec l'identifiant du compte comme donnee associee : un secret
recopie sur un autre compte devient indechiffrable.
"""

import base64
import hashlib
import hmac
import os
import secrets
import struct
from datetime import datetime
from urllib.parse import quote

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.cles import deriver_cle

PERIODE_SECONDES = 30
CHIFFRES = 6
# Tolerance d'un pas avant/apres : horloge de telephone legerement decalee.
FENETRE = 1
EMETTEUR = "Barryson ERP"


def generer_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def pas_de_temps(instant: datetime) -> int:
    return int(instant.timestamp()) // PERIODE_SECONDES


def code_pour_pas(secret_base32: str, pas: int) -> str:
    cle = base64.b32decode(secret_base32)
    empreinte = hmac.new(cle, struct.pack(">Q", pas), hashlib.sha1).digest()
    decalage = empreinte[-1] & 0x0F
    valeur = struct.unpack(">I", empreinte[decalage:decalage + 4])[0] & 0x7FFFFFFF
    return str(valeur % 10**CHIFFRES).zfill(CHIFFRES)


def verifier_code(secret_base32: str, code: str, instant: datetime, dernier_pas: int | None) -> int | None:
    """Renvoie le pas de temps reconnu, ou None. Un pas deja utilise est refuse (anti-rejeu)."""
    if len(code) != CHIFFRES or not code.isdigit():
        return None
    courant = pas_de_temps(instant)
    for pas in range(courant - FENETRE, courant + FENETRE + 1):
        if dernier_pas is not None and pas <= dernier_pas:
            continue
        if hmac.compare_digest(code_pour_pas(secret_base32, pas), code):
            return pas
    return None


def uri_configuration(secret_base32: str, identifiant: str) -> str:
    """A afficher en QR code par l'interface, scanne par l'application du telephone."""
    libelle = quote(f"{EMETTEUR}:{identifiant}")
    return (f"otpauth://totp/{libelle}?secret={secret_base32}&issuer={quote(EMETTEUR)}"
            f"&algorithm=SHA1&digits={CHIFFRES}&period={PERIODE_SECONDES}")


def chiffrer(secret_base32: str, utilisateur_id: object) -> str:
    nonce = os.urandom(12)
    chiffre = AESGCM(deriver_cle("totp")).encrypt(nonce, secret_base32.encode("ascii"),
                                                  str(utilisateur_id).encode("ascii"))
    return base64.b64encode(nonce + chiffre).decode("ascii")


def dechiffrer(stocke: str, utilisateur_id: object) -> str | None:
    try:
        brut = base64.b64decode(stocke)
        clair = AESGCM(deriver_cle("totp")).decrypt(brut[:12], brut[12:], str(utilisateur_id).encode("ascii"))
    except (InvalidTag, ValueError):
        return None
    return clair.decode("ascii")
