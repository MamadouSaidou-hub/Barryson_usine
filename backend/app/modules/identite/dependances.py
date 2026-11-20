"""Dependances FastAPI : authentification, CSRF et controle des droits a chaque appel.

Usage dans un module metier :

    @router.post("/ordres")
    def creer(ctx: Annotated[Contexte, Depends(exiger("production.saisir"))]): ...

Le controle est fait ici, cote serveur, quel que soit ce qu'affiche l'interface.
"""

import hmac
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.audit import journaliser
from app.core.config import get_settings
from app.core.db import get_db
from app.modules.identite import service
from app.modules.identite.models import SessionUtilisateur, Utilisateur
from app.modules.identite.permissions import CATALOGUE, a_la_permission

METHODES_SURES = frozenset({"GET", "HEAD", "OPTIONS"})
ENTETE_CSRF = "X-CSRF-Token"


@dataclass
class Contexte:
    utilisateur: Utilisateur
    session: SessionUtilisateur
    jeton: str
    db: Session


def adresse_ip(request: Request) -> str | None:
    # Derriere Caddy, uvicorn reecrit client.host depuis X-Forwarded-For
    # uniquement pour les proxys listes dans FORWARDED_ALLOW_IPS.
    return request.client.host if request.client else None


def _contexte(request: Request, db: Session, *, autoriser_changement_en_attente: bool) -> Contexte:
    db.info["ip"] = adresse_ip(request)
    jeton = request.cookies.get(get_settings().nom_cookie_session)
    try:
        utilisateur, session = service.authentifier(db, jeton)
    except service.SessionInvalide as erreur:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, erreur.message) from erreur
    assert jeton is not None

    if request.method not in METHODES_SURES:
        fourni = request.headers.get(ENTETE_CSRF, "").encode("utf-8")
        if not hmac.compare_digest(fourni, service.jeton_csrf(jeton).encode("utf-8")):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Jeton CSRF absent ou invalide.")

    db.info.update(acteur_id=utilisateur.id, entreprise_id=utilisateur.entreprise_id)
    if not autoriser_changement_en_attente:
        if utilisateur.doit_changer_mot_de_passe:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Vous devez changer votre mot de passe avant toute autre action.")
        if service.double_facteur_a_configurer(utilisateur):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Vous devez activer la double authentification avant toute autre action.")
    return Contexte(utilisateur, session, jeton, db)


def contexte_authentifie(request: Request, db: Annotated[Session, Depends(get_db)]) -> Contexte:
    """Session valide, meme si un changement de mot de passe ou l'activation du second facteur
    est en attente : reserve aux ecrans qui permettent justement de s'en acquitter."""
    return _contexte(request, db, autoriser_changement_en_attente=True)


def contexte_actif(request: Request, db: Annotated[Session, Depends(get_db)]) -> Contexte:
    """Session valide et mot de passe definitif : prerequis de toute action metier."""
    return _contexte(request, db, autoriser_changement_en_attente=False)


def exiger(permission: str) -> Callable[..., Contexte]:
    if permission not in CATALOGUE:
        # Une faute de frappe dans une permission doit casser au demarrage, pas ouvrir un acces.
        raise ValueError(f"Permission inconnue : {permission!r}")

    def dependance(request: Request, ctx: Annotated[Contexte, Depends(contexte_actif)]) -> Contexte:
        if not a_la_permission(ctx.utilisateur.role, permission):
            details = {"permission": permission, "methode": request.method, "chemin": request.url.path}
            journaliser(ctx.db, "acces.refuse", apres=details)
            ctx.db.commit()
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Accès refusé.")
        return ctx

    return dependance
