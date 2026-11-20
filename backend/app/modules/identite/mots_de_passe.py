"""Hachage et politique des mots de passe. Aucune dependance a la base ni a HTTP.

argon2id (profil RFC 9106 a memoire reduite, parametres par defaut
d'argon2-cffi). La politique suit les recommandations NIST 800-63B : la
longueur et le refus des mots de passe previsibles comptent, pas les regles
de composition (majuscule + chiffre + symbole) qui poussent a "Barryson2026!".
"""

import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

LONGUEUR_MIN = 12
LONGUEUR_MAX = 128
# Au-dela, on refuse sans hacher : evite qu'une requete de connexion serve a
# saturer le processeur avec un mot de passe de plusieurs megaoctets.
LONGUEUR_MAX_VERIFIABLE = 1024

_hacheur = PasswordHasher()

_FRAGMENTS_INTERDITS = (
    "barryson", "motdepasse", "password", "azerty", "qwerty", "123456", "abcdef", "conakry", "guinee",
)
_ALPHABET_TEMPORAIRE = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"


def hacher(mot_de_passe: str) -> str:
    return _hacheur.hash(mot_de_passe)


def verifier(hash_stocke: str, mot_de_passe: str) -> bool:
    if len(mot_de_passe) > LONGUEUR_MAX_VERIFIABLE:
        return False
    try:
        return _hacheur.verify(hash_stocke, mot_de_passe)
    except (VerificationError, InvalidHashError):
        return False


def doit_rehacher(hash_stocke: str) -> bool:
    """Vrai si les parametres d'argon2 ont ete durcis depuis le dernier hachage."""
    return _hacheur.check_needs_rehash(hash_stocke)


@lru_cache(maxsize=1)
def _hash_factice() -> str:
    return _hacheur.hash(secrets.token_urlsafe(32))


def verifier_factice(mot_de_passe: str) -> None:
    """Meme cout qu'une vraie verification : le temps de reponse ne revele pas
    si un identifiant existe ou si un compte est verrouille."""
    verifier(_hash_factice(), mot_de_passe)


def verifier_politique(mot_de_passe: str, *, identifiant: str = "", nom: str = "") -> list[str]:
    erreurs: list[str] = []
    if len(mot_de_passe) < LONGUEUR_MIN:
        erreurs.append(f"Le mot de passe doit contenir au moins {LONGUEUR_MIN} caractères.")
    if len(mot_de_passe) > LONGUEUR_MAX:
        erreurs.append(f"Le mot de passe ne doit pas dépasser {LONGUEUR_MAX} caractères.")
    bas = mot_de_passe.lower()
    if identifiant and identifiant.lower() in bas:
        erreurs.append("Le mot de passe ne doit pas contenir l'identifiant.")
    if any(len(partie) >= 4 and partie in bas for partie in nom.lower().split()):
        erreurs.append("Le mot de passe ne doit pas contenir le nom de la personne.")
    if any(fragment in bas for fragment in _FRAGMENTS_INTERDITS) or len(set(mot_de_passe)) < 5:
        erreurs.append("Le mot de passe est trop prévisible.")
    return erreurs


def generer_temporaire() -> str:
    """Mot de passe a usage unique, communique hors du logiciel, a changer a la premiere connexion."""
    while True:
        groupes = ["".join(secrets.choice(_ALPHABET_TEMPORAIRE) for _ in range(4)) for _ in range(4)]
        candidat = "-".join(groupes)
        if not verifier_politique(candidat):
            return candidat
