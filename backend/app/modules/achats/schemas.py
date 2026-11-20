"""Contrat d'API du module achats."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.modules.achats.models import Devise, StatutCommande, StatutReception
from app.modules.referentiel.schemas import Nombre
from app.modules.stock.models import CouleurFinition

Quantite = Annotated[Decimal, Field(gt=0, le=10_000_000, max_digits=14, decimal_places=3)]
QuantiteAcceptee = Annotated[Decimal, Field(ge=0, le=10_000_000, max_digits=14, decimal_places=3)]
Prix = Annotated[Decimal, Field(ge=0, le=10**12, max_digits=16, decimal_places=4)]
Texte = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Motif = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)]
Court = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
MAX_LIGNES = 200


class _Entree(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Sortie(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Commande ------------------------------------------------------------------------------------


class LigneCommandeEntree(_Entree):
    article_id: uuid.UUID
    quantite_commandee: Quantite
    prix_unitaire: Prix | None = None
    couleur_finition: CouleurFinition | None = None


Taux = Annotated[Decimal, Field(gt=0, le=10**9, max_digits=16, decimal_places=4)]


class CommandeCreation(_Entree):
    fournisseur_id: uuid.UUID
    devise: Devise
    # Taux du jour : 1 unite de la devise vaut X GNF. Sert a estimer le montant en GNF pour le DG.
    taux_change_gnf: Taux | None = None
    date_arrivee_prevue: date | None = None
    reference_fournisseur: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = (
        None
    )
    commentaire: Texte | None = None
    lignes: Annotated[list[LigneCommandeEntree], Field(min_length=1, max_length=MAX_LIGNES)]


class CommandeModification(_Entree):
    """Brouillon seulement. Les lignes, si elles sont envoyees, remplacent toutes les precedentes."""

    fournisseur_id: uuid.UUID | None = None
    devise: Devise | None = None
    taux_change_gnf: Taux | None = None
    date_arrivee_prevue: date | None = None
    reference_fournisseur: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = (
        None
    )
    commentaire: Texte | None = None
    lignes: Annotated[list[LigneCommandeEntree], Field(min_length=1, max_length=MAX_LIGNES)] | None = None


class Decision(_Entree):
    motif: Motif


class Commande(_Entree):
    reference_fournisseur: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = (
        None
    )


class LigneCommandePublic(BaseModel):
    id: uuid.UUID
    rang: int
    article_id: uuid.UUID
    article_code: str
    article_nom: str
    unite: str
    quantite_commandee: Nombre
    prix_unitaire: Nombre | None
    couleur_finition: str | None
    # Cumul des quantites ACCEPTEES au controle de conformite, et ce qu'il reste a recevoir.
    quantite_recue_acceptee: Nombre
    solde: Nombre
    montant: Nombre | None


class TransitionPublic(_Sortie):
    de_statut: str | None
    vers_statut: str
    acteur_id: uuid.UUID | None
    motif: str | None
    cree_le: datetime


class ReceptionResume(_Sortie):
    id: uuid.UUID
    numero: str
    statut: StatutReception
    date_arrivee: date
    conteneur_reference: str | None
    cree_le: datetime


class CommandePublic(_Sortie):
    id: uuid.UUID
    numero: str
    fournisseur_id: uuid.UUID
    statut: StatutCommande
    devise: str
    taux_change_gnf: Nombre | None
    date_arrivee_prevue: date | None
    reference_fournisseur: str | None
    commentaire: str | None
    cree_par: uuid.UUID | None
    cree_le: datetime
    valide_par: uuid.UUID | None
    valide_le: datetime | None
    valide_via_delegation_id: uuid.UUID | None
    commandee_le: datetime | None
    motif_decision: str | None


class CommandeDetail(CommandePublic):
    lignes: list[LigneCommandePublic] = []
    # Somme des lignes dont le prix est connu, dans la devise de la commande.
    montant_total: Nombre | None = None
    # Estimation en GNF : le total si la devise est le GNF, sinon total x taux saisi a la commande.
    montant_total_gnf: Nombre | None = None
    prix_manquants: int = 0
    receptions: list[ReceptionResume] = []
    transitions: list[TransitionPublic] = []


# --- Reception et controle -----------------------------------------------------------------------


class LigneReceptionEntree(_Entree):
    ligne_commande_id: uuid.UUID
    # Ignoree pour une ligne de bobines : elle vaut le nombre de lignes de la packing list.
    quantite_recue: Quantite | None = None
    observation: Court | None = None


class ReceptionCreation(_Entree):
    date_arrivee: date
    conteneur_reference: Reference | None = None
    numero_facture: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    commentaire: Texte | None = None
    # Packing list deja analysee (POST /api/imports-colisage) pour les bobines du conteneur.
    import_colisage_id: uuid.UUID | None = None
    lignes: Annotated[list[LigneReceptionEntree], Field(min_length=1, max_length=MAX_LIGNES)]

    @model_validator(mode="after")
    def _date_non_future(self) -> "ReceptionCreation":
        if self.date_arrivee > date.today():
            raise ValueError("La date d'arrivée ne peut pas être dans le futur.")
        return self


class LigneControle(_Entree):
    ligne_reception_id: uuid.UUID
    quantite_acceptee: QuantiteAcceptee
    motif_ecart: Court | None = None
    # Bobines refusees (colis endommage...) : numeros fournisseur ; ne s'applique qu'aux lignes de bobines.
    bobines_refusees: Annotated[
        list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]],
        Field(max_length=2000),
    ] = []


class ControleDemande(_Entree):
    decision: Literal["acceptee", "acceptee_avec_reserves", "refusee"]
    controle_documentaire_ok: bool
    commentaire: Texte | None = None
    lignes: Annotated[list[LigneControle], Field(min_length=1, max_length=MAX_LIGNES)]


class LigneReceptionPublic(BaseModel):
    id: uuid.UUID
    ligne_commande_id: uuid.UUID
    article_id: uuid.UUID
    article_code: str
    article_nom: str
    unite: str
    quantite_commandee: Nombre
    # Solde de la commande avant cette reception (hors receptions en cours de controle).
    solde_avant: Nombre
    quantite_recue: Nombre
    quantite_acceptee: Nombre | None
    observation: str | None
    motif_ecart: str | None
    bobines_refusees: list[str]


class ReceptionPublic(_Sortie):
    id: uuid.UUID
    numero: str
    commande_id: uuid.UUID
    import_colisage_id: uuid.UUID | None
    conteneur_reference: str | None
    numero_facture: str | None
    date_arrivee: date
    statut: StatutReception
    commentaire: str | None
    cree_par: uuid.UUID | None
    cree_le: datetime
    controle_documentaire_ok: bool | None
    controle_par: uuid.UUID | None
    controle_le: datetime | None
    commentaire_controle: str | None
    lot_id: uuid.UUID | None


class ReceptionDetail(ReceptionPublic):
    lignes: list[LigneReceptionPublic] = []
    # Avertissements a lire avant de controler (quantite superieure au solde, finition inattendue...).
    avertissements: list[str] = []
    avec_ecarts: bool = False
