"""Delegation des validations du DG.

Une delegation n'ajoute au delegataire que les droits listes, uniquement pendant sa periode, tant
qu'elle n'est pas revoquee et que le DG qui l'a accordee est toujours en fonction. Elle ne contourne
rien d'autre : le delegataire reste soumis a la separation (il ne valide pas ce qu'il a saisi).
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import journaliser, maintenant
from app.core.config import get_settings
from app.core.erreurs import DonneesInvalides, Introuvable, OperationInterdite
from app.core.transactions import transactionnel
from app.modules.identite.models import Delegation, Utilisateur
from app.modules.identite.permissions import DELEGABLES, a_la_permission, permissions_du_role


def delegations_actives(
    db: Session, utilisateur: Utilisateur, instant: datetime | None = None
) -> list[Delegation]:
    instant = instant or maintenant()
    requete = (
        select(Delegation)
        .join(Utilisateur, Utilisateur.id == Delegation.delegant_id)
        .where(
            Delegation.delegataire_id == utilisateur.id,
            Delegation.revoquee_le.is_(None),
            Delegation.date_debut <= instant,
            Delegation.date_fin > instant,
            # Le pouvoir delegue disparait avec celui qui l'a accorde.
            Utilisateur.actif.is_(True),
            Utilisateur.role == "dg",
        )
        .order_by(Delegation.date_fin)
    )
    return list(db.scalars(requete))


def droit(db: Session, utilisateur: Utilisateur, permission: str) -> tuple[bool, uuid.UUID | None]:
    """(autorise, delegation_id). Le droit propre au role prime ; la delegation n'intervient qu'a defaut."""
    if a_la_permission(utilisateur.role, permission):
        return True, None
    if permission in DELEGABLES:
        for delegation in delegations_actives(db, utilisateur):
            if permission in delegation.permissions:
                return True, delegation.id
    return False, None


def permissions_effectives(db: Session, utilisateur: Utilisateur) -> tuple[list[str], list[str]]:
    """(toutes les permissions, dont celles qui viennent d'une delegation)."""
    propres = set(permissions_du_role(utilisateur.role))
    deleguees = {p for d in delegations_actives(db, utilisateur) for p in d.permissions} - propres
    return sorted(propres | deleguees), sorted(deleguees)


def _fin_de_journee(jour: date) -> datetime:
    return datetime.combine(jour, time(23, 59, 59), tzinfo=UTC) + timedelta(seconds=1)


@transactionnel
def creer(db: Session, acteur: Utilisateur, donnees: dict[str, Any]) -> Delegation:
    delegataire = db.scalar(
        select(Utilisateur).where(
            Utilisateur.entreprise_id == acteur.entreprise_id, Utilisateur.id == donnees["delegataire_id"]
        )
    )
    if delegataire is None:
        raise DonneesInvalides("Délégataire introuvable.")
    if delegataire.id == acteur.id:
        raise DonneesInvalides("Le DG ne peut pas se déléguer à lui-même.")
    if not delegataire.actif:
        raise DonneesInvalides(f"Le compte de {delegataire.nom} est désactivé.")
    if delegataire.role in ("administrateur", "dg"):
        raise DonneesInvalides(
            "Un administrateur technique ne valide pas d'opérations de gestion, et un "
            "autre DG a déjà ces droits : choisissez un responsable métier."
        )
    permissions = sorted(set(donnees["permissions"]))
    interdites = [p for p in permissions if p not in DELEGABLES]
    if interdites:
        raise DonneesInvalides(f"Droit(s) non délégable(s) : {', '.join(interdites)}.")

    instant = maintenant()
    fin = _fin_de_journee(donnees["jusqu_au"])
    maximum = get_settings().delegation_duree_max_jours
    if fin <= instant:
        raise DonneesInvalides("La date de fin doit être dans le futur.")
    if fin > instant + timedelta(days=maximum):
        raise DonneesInvalides(f"Une délégation dure {maximum} jours au plus : renouvelez-la si besoin.")

    delegation = Delegation(
        entreprise_id=acteur.entreprise_id,
        delegant_id=acteur.id,
        delegataire_id=delegataire.id,
        permissions=permissions,
        date_debut=instant,
        date_fin=fin,
        motif=donnees["motif"],
    )
    db.add(delegation)
    db.commit()
    return delegation


@transactionnel
def revoquer(db: Session, acteur: Utilisateur, delegation_id: uuid.UUID) -> Delegation:
    delegation = db.scalar(
        select(Delegation)
        .where(Delegation.entreprise_id == acteur.entreprise_id, Delegation.id == delegation_id)
        .with_for_update()
    )
    if delegation is None:
        raise Introuvable()
    if delegation.revoquee_le is not None:
        raise OperationInterdite("Cette délégation est déjà révoquée.")
    delegation.revoquee_le, delegation.revoquee_par = maintenant(), acteur.id
    journaliser(db, "delegation.revoquee", cible_type="delegations", cible_id=delegation.id)
    db.commit()
    return delegation


def lister(db: Session, acteur: Utilisateur, *, seulement_actives: bool) -> list[Delegation]:
    requete = select(Delegation).where(Delegation.entreprise_id == acteur.entreprise_id)
    if seulement_actives:
        instant = maintenant()
        requete = requete.where(Delegation.revoquee_le.is_(None), Delegation.date_fin > instant)
    return list(db.scalars(requete.order_by(Delegation.cree_le.desc()).limit(200)))
