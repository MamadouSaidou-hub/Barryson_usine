"""Points d'entree HTTP du Doctor Rewinder. Aucune regle ici : tout est dans service.py."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.modules.doctor_rewinder import service
from app.modules.doctor_rewinder.models import StatutEncours
from app.modules.doctor_rewinder.schemas import EncoursPublic, Indicateurs, Renvoi, Traitement
from app.modules.identite.dependances import Contexte, exiger

router = APIRouter(prefix="/api", tags=["Doctor Rewinder"])

Lecture = Annotated[Contexte, Depends(exiger("doctor_rewinder.consulter"))]
# Declarer ce qui est revenu : le chef de production, comme la saisie du resultat de fabrication.
Saisie = Annotated[Contexte, Depends(exiger("production.saisir"))]
Validation = Annotated[Contexte, Depends(exiger("doctor_rewinder.valider"))]


# Route fixe declaree avant `/{id}` : sinon « indicateurs » serait lu comme un identifiant.
@router.get("/doctor-rewinder/indicateurs", response_model=Indicateurs)
def indicateurs(ctx: Lecture):
    return service.indicateurs(ctx.db, ctx.utilisateur)


@router.get("/doctor-rewinder", response_model=list[EncoursPublic])
def lister(ctx: Lecture, statut: Annotated[StatutEncours | None, Query()] = None,
           ordre_id: uuid.UUID | None = None):
    return service.lister(ctx.db, ctx.utilisateur, statut=statut, ordre_id=ordre_id)


@router.get("/doctor-rewinder/{encours_id}", response_model=EncoursPublic)
def lire(encours_id: uuid.UUID, ctx: Lecture):
    return service.charger(ctx.db, ctx.utilisateur, encours_id)


@router.put("/doctor-rewinder/{encours_id}/traitement", response_model=EncoursPublic)
def traiter(encours_id: uuid.UUID, demande: Traitement, ctx: Saisie):
    """Retour du Doctor Rewinder : pieces recuperees et pieces non recuperables (pertes definitives)."""
    return service.traiter(ctx.db, ctx.utilisateur, encours_id, demande.model_dump())


@router.post("/doctor-rewinder/{encours_id}/valider", response_model=EncoursPublic)
def valider(encours_id: uuid.UUID, ctx: Validation):
    """Valide le traitement : seule cette validation fait entrer les pieces recuperees en stock."""
    return service.valider(ctx.db, ctx.utilisateur, encours_id)


@router.post("/doctor-rewinder/{encours_id}/renvoyer", response_model=EncoursPublic)
def renvoyer(encours_id: uuid.UUID, demande: Renvoi, ctx: Validation):
    return service.renvoyer(ctx.db, ctx.utilisateur, encours_id, demande.motif)
