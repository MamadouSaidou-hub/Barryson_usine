"""Contrat d'API du module production."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.production.models import StatutOF
from app.modules.referentiel.schemas import Nombre

Metrage = Annotated[Decimal, Field(gt=0, le=100_000, decimal_places=2)]
Quantite = Annotated[int, Field(ge=0, le=1_000_000)]
Texte = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Motif = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)]


class _Entree(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Sortie(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OrdreCreation(_Entree):
    modele_id: uuid.UUID
    bobine_id: uuid.UUID
    metrage_engage: Metrage
    commentaire: Texte | None = None


class OrdreModification(_Entree):
    """Brouillon seulement. Changer de bobine ou de modele : annuler et recreer."""

    metrage_engage: Metrage | None = None
    commentaire: Texte | None = None


class PrevisionDemande(_Entree):
    modele_id: uuid.UUID
    bobine_id: uuid.UUID
    metrage_engage: Metrage


class ResultatSaisie(_Entree):
    tours_totaux: Quantite
    tours_defectueux: Quantite
    pieces_defectueuses_supplementaires: Quantite
    quantite_doctor_rewinder: Quantite
    pertes_definitives: Quantite
    # Vrai si l'operateur declare la bobine entierement consommee ; sinon elle reste « entamee, presente ».
    bobine_epuisee: bool = False


class SortieMatieres(_Entree):
    # Seul le DG (ou son delegataire) peut l'utiliser : sortir des tubes absents du stock.
    derogation_motif: Motif | None = None


class Annulation(_Entree):
    motif: Motif


class Alerte(BaseModel):
    code: str
    message: str


class PrevisionPublic(BaseModel):
    metrage_engage: Nombre
    longueur_rouleau_m: Nombre
    pieces_par_tour: int
    pieces_par_carton: int
    tours_complets: int
    pieces_theoriques: int
    cartons_complets: int
    pieces_restantes: int
    alertes: list[Alerte]


class ResultatCalcule(BaseModel):
    pieces_brutes: int
    pieces_non_conformes: int
    pieces_conformes: int
    cartons_complets: int
    pieces_restantes: int
    ecart_pieces: int
    ecart_pourcentage: Nombre
    rendement: Nombre
    # Doit valoir 0 pour valider : positif = piece oubliee, negatif = piece comptee deux fois.
    ecart_comptage: int
    coherent: bool


class TransitionPublic(_Sortie):
    de_statut: str | None
    vers_statut: str
    acteur_id: uuid.UUID | None
    motif: str | None
    cree_le: datetime


class OrdrePublic(_Sortie):
    id: uuid.UUID
    numero: str
    statut: StatutOF
    modele_id: uuid.UUID
    version_id: uuid.UUID
    bobine_id: uuid.UUID
    metrage_engage: Nombre
    commentaire: str | None
    tours_prevus: int | None
    pieces_theoriques: int | None
    cartons_prevus: int | None
    pieces_restantes_prevues: int | None
    alertes: list[Alerte]
    cree_par: uuid.UUID | None
    cree_le: datetime
    motif_annulation: str | None


class OrdreDetail(OrdrePublic):
    tours_totaux: int | None
    tours_defectueux: int | None
    pieces_defectueuses_supplementaires: int | None
    quantite_doctor_rewinder: int | None
    pertes_definitives: int | None
    bobine_epuisee: bool | None
    resultat_saisi_par: uuid.UUID | None
    resultat_saisi_le: datetime | None
    # Calcule a la demande depuis la saisie : visible des la saisie, fige a la validation.
    resultat: ResultatCalcule | None = None
    version_formule: str | None
    transitions: list[TransitionPublic] = []
