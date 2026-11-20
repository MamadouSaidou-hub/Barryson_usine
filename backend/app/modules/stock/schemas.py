"""Contrat d'API du module stock.

L'API ne recoit jamais de quantite signee : le sens vient du type de
mouvement (ou de `sens` pour un ajustement). Elle n'accepte que les types
saisis a la main ; consommation, sortie, entree de fabrication et retour sont
produits par les modules production et ventes, jamais forges par un appel.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.modules.referentiel.schemas import Nombre
from app.modules.stock.models import CouleurFinition, CouleurImpression, StatutBobine, StatutImport

Motif = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)]
Quantite = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]
Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)]
Url = Annotated[str, StringConstraints(max_length=500, pattern=r"^https?://")]
Numero = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Poids = Annotated[Decimal, Field(gt=0, le=2000, decimal_places=2)]
Metrage = Annotated[Decimal, Field(gt=0, le=100_000, decimal_places=2)]
ModuleImpression = Literal[45, 48, 70]
MAX_BOBINES = 2000


class _Entree(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Sortie(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _date_non_future(valeur: date) -> date:
    if valeur > date.today():
        raise ValueError("La date de réception ne peut pas être dans le futur.")
    return valeur


# --- Mouvements ------------------------------------------------------------------


class MouvementCreation(_Entree):
    type: Literal["entree_directe", "ajustement", "sortie_exceptionnelle", "rebut_destruction"]
    article_id: uuid.UUID
    quantite: Quantite
    # Obligatoire pour un ajustement uniquement ; ignore pour les autres types.
    sens: Literal["plus", "moins"] | None = None
    motif: Motif
    piece_justificative_url: Url | None = None

    @model_validator(mode="after")
    def _sens_coherent(self) -> "MouvementCreation":
        if self.type == "ajustement" and self.sens is None:
            raise ValueError("Un ajustement doit préciser son sens (plus ou moins).")
        if self.type != "ajustement" and self.sens is not None:
            raise ValueError("Le sens ne s'applique qu'aux ajustements.")
        return self


class ValidationDemande(_Entree):
    decision: Literal["valide", "rejete"]
    motif: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None

    @model_validator(mode="after")
    def _rejet_motive(self) -> "ValidationDemande":
        if self.decision == "rejete" and len(self.motif or "") < 5:
            raise ValueError("Un rejet doit être motivé (5 caractères minimum).")
        return self


class MouvementPublic(_Sortie):
    id: uuid.UUID
    article_id: uuid.UUID
    type: str
    quantite: Nombre
    unite: str
    lot_id: uuid.UUID | None
    bobine_id: uuid.UUID | None
    motif: str
    piece_justificative_url: str | None
    cree_par: uuid.UUID | None
    cree_le: datetime
    # en_attente | valide | rejete — un mouvement en attente ou rejete ne compte pas dans le stock.
    statut: str = "en_attente"
    valide_par: uuid.UUID | None = None


# --- Soldes et reservations ---------------------------------------------------------


class SoldeArticle(BaseModel):
    article_id: uuid.UUID
    code: str
    nom: str
    niveau_stock: str
    unite: str
    physique: Nombre
    reserve: Nombre
    disponible: Nombre
    # Stock negatif : jamais bloquant (ADR 0003), signale comme ecart a regulariser.
    negatif: bool
    sous_seuil_min: bool
    en_attente_validation: int


class ReservationCreation(_Entree):
    article_id: uuid.UUID
    quantite: Quantite
    motif: Motif


class ReservationPublic(_Sortie):
    id: uuid.UUID
    article_id: uuid.UUID
    quantite: Nombre
    motif: str
    statut: str
    cree_par: uuid.UUID | None
    cree_le: datetime
    levee_le: datetime | None


# --- Lots et bobines ---------------------------------------------------------------


class LigneBobine(_Entree):
    numero_fournisseur: Numero
    poids_kg: Poids
    metrage_propre: Metrage | None = None
    couleur_finition: CouleurFinition
    couleur_impression: CouleurImpression | None = None
    module_impression: ModuleImpression | None = None


class ReceptionCreation(_Entree):
    conteneur_reference: Reference
    numero_facture: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    date_reception: Annotated[date, Field()]
    fournisseur_id: uuid.UUID
    article_id: uuid.UUID
    bobines: Annotated[list[LigneBobine], Field(min_length=1, max_length=MAX_BOBINES)]

    @model_validator(mode="after")
    def _date(self) -> "ReceptionCreation":
        _date_non_future(self.date_reception)
        return self


class LotPublic(_Sortie):
    id: uuid.UUID
    conteneur_reference: str
    numero_facture: str | None
    date_reception: date
    fournisseur_id: uuid.UUID
    cree_le: datetime
    nb_bobines: int = 0


class BobinePublic(_Sortie):
    id: uuid.UUID
    lot_id: uuid.UUID
    article_id: uuid.UUID
    numero_fournisseur: str
    poids_kg: Nombre
    metrage_propre: Nombre | None
    couleur_finition: str
    couleur_impression: str | None
    module_impression: int | None
    statut: StatutBobine


# --- Import de packing list -------------------------------------------------------------


class LigneImport(_Entree):
    numero_fournisseur: Numero | None = None
    poids_kg: Annotated[Decimal, Field(gt=0, le=100_000, decimal_places=2)] | None = None
    metrage_propre: Annotated[Decimal, Field(gt=0, le=1_000_000, decimal_places=2)] | None = None
    couleur_brute: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    # Correspondance faite a l'ecran d'apercu : absente = anomalie bloquante.
    couleur_finition: CouleurFinition | None = None
    couleur_impression: CouleurImpression | None = None
    module_impression: ModuleImpression | None = None


class ImportCreation(_Entree):
    conteneur_reference: Reference
    numero_facture: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    date_reception: date
    fournisseur_id: uuid.UUID
    article_id: uuid.UUID
    lignes: Annotated[list[LigneImport], Field(min_length=1, max_length=MAX_BOBINES)]

    @model_validator(mode="after")
    def _date(self) -> "ImportCreation":
        _date_non_future(self.date_reception)
        return self


class Anomalie(BaseModel):
    niveau: Literal["bloquante", "avertissement"]
    code: str
    message: str


class LigneImportPublic(_Sortie):
    rang: int
    numero_fournisseur: str | None
    poids_kg: Nombre | None
    metrage_propre: Nombre | None
    couleur_brute: str | None
    couleur_finition: str | None
    couleur_impression: str | None
    module_impression: int | None
    anomalies: list[Anomalie]


class ImportPublic(_Sortie):
    id: uuid.UUID
    conteneur_reference: str
    numero_facture: str | None
    date_reception: date
    fournisseur_id: uuid.UUID
    article_id: uuid.UUID
    statut: StatutImport
    nb_lignes: int
    nb_bloquantes: int
    nb_avertissements: int
    cree_par: uuid.UUID | None
    cree_le: datetime
    valide_par: uuid.UUID | None
    lot_id: uuid.UUID | None


class ImportDetail(ImportPublic):
    lignes: list[LigneImportPublic]
