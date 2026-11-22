"""Contrat d'API du Doctor Rewinder."""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.doctor_rewinder.models import StatutEncours
from app.modules.referentiel.schemas import Nombre

Quantite = Annotated[int, Field(ge=0, le=1_000_000)]
Texte = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Motif = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)]


class _Entree(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Traitement(_Entree):
    quantite_recuperee: Quantite
    quantite_non_recuperable: Quantite
    commentaire: Texte | None = None


class Renvoi(_Entree):
    motif: Motif


class EncoursPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ordre_id: uuid.UUID
    bobine_id: uuid.UUID
    modele_id: uuid.UUID
    article_id: uuid.UUID
    pieces_par_carton: int
    metrage: Nombre
    quantite_envoyee: int
    date_envoi: date
    statut: StatutEncours
    quantite_recuperee: int | None
    quantite_non_recuperable: int | None
    commentaire: str | None
    traite_par: uuid.UUID | None
    date_traitement: datetime | None
    valide_par: uuid.UUID | None
    valide_le: datetime | None
    mouvement_id: uuid.UUID | None
    pieces_reliquat: int | None
    cree_le: datetime


class Indicateurs(BaseModel):
    encours_ouverts: int
    pieces_en_cours: int
    a_valider: int
    pieces_envoyees_traitees: int
    pieces_recuperees: int
    taux_recuperation: Nombre | None
    delai_moyen_jours: Nombre | None
    anciennete_max_jours: int | None
    # Pour descendre du chiffre a l'operation d'origine.
    plus_ancien_id: uuid.UUID | None
