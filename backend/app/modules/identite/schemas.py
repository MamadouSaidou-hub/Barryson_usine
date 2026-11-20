"""Contrat d'API du module identite.

Les entrees refusent tout champ non prevu (`extra="forbid"`) : impossible de
glisser un `role` ou un `mot_de_passe_hash` dans une requete qui ne l'attend
pas. Les sorties ne contiennent jamais de hash ni de jeton de session.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.identite.permissions import Role


class _Entree(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DemandeConnexion(_Entree):
    identifiant: str = Field(min_length=1, max_length=150)
    mot_de_passe: str = Field(min_length=1, max_length=1024)
    # Exige pour les roles soumis a la double authentification, apres une premiere reponse 401
    # portant "code_requis": true.
    code: str | None = Field(default=None, pattern=r"^\d{6}$")


class DemandeCode(_Entree):
    code: str = Field(pattern=r"^\d{6}$")


class ConfigurationDoubleFacteur(BaseModel):
    # A afficher en QR code (uri) ou a saisir a la main (secret) dans l'application du telephone.
    secret: str
    uri: str


class DemandeChangementMotDePasse(_Entree):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    actuel: str = Field(min_length=1, max_length=1024)
    nouveau: str = Field(min_length=1, max_length=1024)


class DemandeCreationUtilisateur(_Entree):
    identifiant: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,49}$")
    nom: str = Field(min_length=2, max_length=150)
    role: Role


class DemandeModificationUtilisateur(_Entree):
    nom: str | None = Field(default=None, min_length=2, max_length=150)
    role: Role | None = None
    actif: bool | None = None


class UtilisateurPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    identifiant: str
    nom: str
    role: str
    actif: bool
    doit_changer_mot_de_passe: bool
    double_facteur_actif: bool
    derniere_connexion_le: datetime | None


class ReponseSession(BaseModel):
    utilisateur: UtilisateurPublic
    permissions: list[str]
    # Parmi `permissions`, celles qui viennent d'une delegation du DG (a signaler dans l'interface).
    permissions_deleguees: list[str] = []
    # Vrai : seul l'ecran de configuration du second facteur est utilisable.
    double_facteur_a_configurer: bool
    # A renvoyer dans l'en-tete X-CSRF-Token de toute requete qui modifie quelque chose.
    csrf_token: str


class UtilisateurCree(BaseModel):
    utilisateur: UtilisateurPublic
    # Affiche une seule fois, a transmettre a la personne hors du logiciel.
    mot_de_passe_temporaire: str


class MotDePasseTemporaire(BaseModel):
    mot_de_passe_temporaire: str


class EntreeAudit(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    numero: int
    horodatage: datetime
    acteur_id: uuid.UUID | None
    action: str
    cible_type: str | None
    cible_id: str | None
    avant: dict | None
    apres: dict | None
    ip: str | None
    entry_hash: str


class VerificationAudit(BaseModel):
    integre: bool
    entrees_verifiees: int
    premiere_anomalie: int | None
    dernier_hash: str


class DelegationCreation(_Entree):
    delegataire_id: uuid.UUID
    permissions: list[str] = Field(min_length=1, max_length=10)
    # Derniere journee de validite (incluse). La duree maximale est reglee cote serveur.
    jusqu_au: date
    motif: str = Field(min_length=5, max_length=300)


class DelegationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    delegant_id: uuid.UUID
    delegataire_id: uuid.UUID
    permissions: list[str]
    date_debut: datetime
    date_fin: datetime
    motif: str
    cree_le: datetime
    revoquee_le: datetime | None
    revoquee_par: uuid.UUID | None
