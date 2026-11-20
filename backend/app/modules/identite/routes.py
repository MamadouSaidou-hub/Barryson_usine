"""Points d'entree HTTP du module identite. Aucune regle ici : tout est dans service.py."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import JournalAudit, verifier_chaine
from app.core.config import get_settings
from app.core.db import get_db
from app.modules.identite import delegations, service
from app.modules.identite.dependances import (
    Contexte,
    adresse_ip,
    contexte_actif,
    contexte_authentifie,
    exiger,
)
from app.modules.identite.schemas import (
    ConfigurationDoubleFacteur,
    DelegationCreation,
    DelegationPublic,
    DemandeChangementMotDePasse,
    DemandeCode,
    DemandeConnexion,
    DemandeCreationUtilisateur,
    DemandeModificationUtilisateur,
    EntreeAudit,
    MotDePasseTemporaire,
    ReponseSession,
    UtilisateurCree,
    UtilisateurPublic,
    VerificationAudit,
)

router = APIRouter(prefix="/api")


def _poser_cookie(response: Response, ouverte: service.SessionOuverte) -> None:
    reglages = get_settings()
    response.set_cookie(
        reglages.nom_cookie_session,
        ouverte.jeton,
        max_age=reglages.session_duree_max_heures * 3600,
        path="/",
        secure=reglages.cookie_securise,
        httponly=True,  # illisible depuis JavaScript : une faille XSS ne vole pas la session
        samesite="strict",  # jamais envoye depuis un autre site
    )


def _reponse_session(utilisateur, csrf: str, db: Session) -> ReponseSession:
    toutes, deleguees = delegations.permissions_effectives(db, utilisateur)
    return ReponseSession(
        utilisateur=UtilisateurPublic.model_validate(utilisateur),
        permissions=toutes,
        permissions_deleguees=deleguees,
        double_facteur_a_configurer=service.double_facteur_a_configurer(utilisateur),
        csrf_token=csrf,
    )


# --- Authentification ------------------------------------------------------


@router.post("/auth/connexion", response_model=ReponseSession, tags=["Authentification"])
def connexion(demande: DemandeConnexion, request: Request, response: Response,
              db: Annotated[Session, Depends(get_db)]) -> ReponseSession:
    ouverte = service.connecter(db, demande.identifiant, demande.mot_de_passe, code=demande.code,
                                ip=adresse_ip(request), user_agent=request.headers.get("user-agent"))
    _poser_cookie(response, ouverte)
    return _reponse_session(ouverte.utilisateur, ouverte.csrf, db)


@router.get("/auth/moi", response_model=ReponseSession, tags=["Authentification"])
def moi(ctx: Annotated[Contexte, Depends(contexte_authentifie)]) -> ReponseSession:
    """Permet a l'interface de retrouver l'utilisateur et le jeton CSRF apres un rechargement."""
    return _reponse_session(ctx.utilisateur, service.jeton_csrf(ctx.jeton), ctx.db)


@router.post("/auth/deconnexion", status_code=status.HTTP_204_NO_CONTENT, tags=["Authentification"])
def deconnexion(ctx: Annotated[Contexte, Depends(contexte_authentifie)]) -> Response:
    service.deconnecter(ctx.db, ctx.session)
    reponse = Response(status_code=status.HTTP_204_NO_CONTENT)
    reglages = get_settings()
    reponse.delete_cookie(reglages.nom_cookie_session, path="/", secure=reglages.cookie_securise,
                          httponly=True, samesite="strict")
    return reponse


@router.post("/auth/mot-de-passe", response_model=ReponseSession, tags=["Authentification"])
def changer_mot_de_passe(demande: DemandeChangementMotDePasse, request: Request, response: Response,
                         ctx: Annotated[Contexte, Depends(contexte_authentifie)]) -> ReponseSession:
    ouverte = service.changer_mot_de_passe(
        ctx.db, ctx.utilisateur, demande.actuel, demande.nouveau,
        ip=adresse_ip(request), user_agent=request.headers.get("user-agent"),
    )
    _poser_cookie(response, ouverte)
    return _reponse_session(ouverte.utilisateur, ouverte.csrf, ctx.db)


@router.post("/auth/double-facteur/initialiser", response_model=ConfigurationDoubleFacteur,
             tags=["Authentification"])
def initialiser_double_facteur(
    ctx: Annotated[Contexte, Depends(contexte_authentifie)],
) -> ConfigurationDoubleFacteur:
    secret, uri = service.initialiser_double_facteur(ctx.db, ctx.utilisateur)
    return ConfigurationDoubleFacteur(secret=secret, uri=uri)


@router.post("/auth/double-facteur/activer", response_model=ReponseSession, tags=["Authentification"])
def activer_double_facteur(demande: DemandeCode,
                           ctx: Annotated[Contexte, Depends(contexte_authentifie)]) -> ReponseSession:
    service.activer_double_facteur(ctx.db, ctx.utilisateur, demande.code)
    return _reponse_session(ctx.utilisateur, service.jeton_csrf(ctx.jeton), ctx.db)


# --- Administration des comptes ----------------------------------------------


@router.get("/utilisateurs", response_model=list[UtilisateurPublic], tags=["Utilisateurs"])
def lister(ctx: Annotated[Contexte, Depends(exiger("utilisateurs.consulter"))]) -> list:
    return service.lister_utilisateurs(ctx.db, ctx.utilisateur)


@router.post("/utilisateurs", response_model=UtilisateurCree, status_code=status.HTTP_201_CREATED,
             tags=["Utilisateurs"])
def creer(demande: DemandeCreationUtilisateur,
          ctx: Annotated[Contexte, Depends(exiger("utilisateurs.gerer"))]) -> UtilisateurCree:
    utilisateur, temporaire = service.creer_utilisateur(
        ctx.db, ctx.utilisateur, identifiant=demande.identifiant, nom=demande.nom, role=demande.role,
    )
    return UtilisateurCree(utilisateur=UtilisateurPublic.model_validate(utilisateur),
                           mot_de_passe_temporaire=temporaire)


@router.patch("/utilisateurs/{utilisateur_id}", response_model=UtilisateurPublic, tags=["Utilisateurs"])
def modifier(utilisateur_id: uuid.UUID, demande: DemandeModificationUtilisateur,
             ctx: Annotated[Contexte, Depends(exiger("utilisateurs.gerer"))]):
    return service.modifier_utilisateur(ctx.db, ctx.utilisateur, utilisateur_id,
                                        nom=demande.nom, role=demande.role, actif=demande.actif)


@router.post("/utilisateurs/{utilisateur_id}/reinitialiser-mot-de-passe", response_model=MotDePasseTemporaire,
             tags=["Utilisateurs"])
def reinitialiser(utilisateur_id: uuid.UUID,
                  ctx: Annotated[Contexte, Depends(exiger("utilisateurs.gerer"))]) -> MotDePasseTemporaire:
    temporaire = service.reinitialiser_mot_de_passe(ctx.db, ctx.utilisateur, utilisateur_id)
    return MotDePasseTemporaire(mot_de_passe_temporaire=temporaire)


@router.post("/utilisateurs/{utilisateur_id}/reinitialiser-double-facteur",
             status_code=status.HTTP_204_NO_CONTENT, tags=["Utilisateurs"])
def reinitialiser_double_facteur(utilisateur_id: uuid.UUID,
                                 ctx: Annotated[Contexte, Depends(exiger("utilisateurs.gerer"))]) -> Response:
    service.reinitialiser_double_facteur(ctx.db, ctx.utilisateur, utilisateur_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Journal d'audit ---------------------------------------------------------


@router.get("/audit", response_model=list[EntreeAudit], tags=["Audit"])
def lire_audit(ctx: Annotated[Contexte, Depends(exiger("audit.consulter"))],
               limite: Annotated[int, Query(ge=1, le=200)] = 50,
               avant: Annotated[int | None, Query(ge=1, description="Numéros inférieurs à")] = None) -> list:
    requete = select(JournalAudit).where(JournalAudit.entreprise_id == ctx.utilisateur.entreprise_id)
    if avant is not None:
        requete = requete.where(JournalAudit.numero < avant)
    return list(ctx.db.scalars(requete.order_by(JournalAudit.numero.desc()).limit(limite)))


@router.get("/audit/verification", response_model=VerificationAudit, tags=["Audit"])
def verifier_audit(ctx: Annotated[Contexte, Depends(exiger("audit.verifier"))]) -> dict:
    resultat = verifier_chaine(ctx.db)
    service.journaliser_verification(ctx.db, resultat)
    return resultat


# --- Delegations du DG -------------------------------------------------------------------------------


@router.get("/delegations", response_model=list[DelegationPublic], tags=["Délégations"])
def lister_delegations(ctx: Annotated[Contexte, Depends(exiger("delegations.gerer"))],
                       actives: bool = False):
    return delegations.lister(ctx.db, ctx.utilisateur, seulement_actives=actives)


@router.get("/delegations/recues", response_model=list[DelegationPublic], tags=["Délégations"])
def delegations_recues(ctx: Annotated[Contexte, Depends(contexte_actif)]):
    """Les delegations en vigueur dont l'utilisateur connecte beneficie."""
    return delegations.delegations_actives(ctx.db, ctx.utilisateur)


@router.post("/delegations", response_model=DelegationPublic, status_code=status.HTTP_201_CREATED,
             tags=["Délégations"])
def creer_delegation(demande: DelegationCreation,
                     ctx: Annotated[Contexte, Depends(exiger("delegations.gerer"))]):
    return delegations.creer(ctx.db, ctx.utilisateur, demande.model_dump())


@router.post("/delegations/{delegation_id}/revoquer", response_model=DelegationPublic, tags=["Délégations"])
def revoquer_delegation(delegation_id: uuid.UUID,
                        ctx: Annotated[Contexte, Depends(exiger("delegations.gerer"))]):
    return delegations.revoquer(ctx.db, ctx.utilisateur, delegation_id)
