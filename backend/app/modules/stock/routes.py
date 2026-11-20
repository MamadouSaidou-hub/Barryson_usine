"""Points d'entree HTTP du module stock. Aucune regle ici : tout est dans service.py.

Aucune route DELETE ni PATCH sur les mouvements : une erreur se corrige par un
mouvement inverse (ajustement), jamais en reecrivant l'histoire.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.modules.identite.dependances import Contexte, contexte_actif, exiger
from app.modules.referentiel.models import NiveauStock
from app.modules.stock import service
from app.modules.stock.models import CouleurFinition, StatutBobine, StatutImport, TypeMouvement
from app.modules.stock.schemas import (
    BobinePublic,
    ImportCreation,
    ImportDetail,
    ImportPublic,
    LotPublic,
    MouvementCreation,
    MouvementPublic,
    ReceptionCreation,
    ReservationCreation,
    ReservationPublic,
    SoldeArticle,
    ValidationDemande,
)

router = APIRouter(prefix="/api")

Lecture = Annotated[Contexte, Depends(exiger("stock.consulter"))]
Saisie = Annotated[Contexte, Depends(exiger("stock.saisir"))]
ValidationReception = Annotated[Contexte, Depends(exiger("stock.valider_reception"))]


def _vue_mouvement(mouvement, validation) -> MouvementPublic:
    vue = MouvementPublic.model_validate(mouvement)
    vue.statut = service.statut_mouvement(mouvement, validation)
    vue.valide_par = validation.valide_par if validation else None
    return vue


def _vue_lot(lot, nb: int) -> LotPublic:
    vue = LotPublic.model_validate(lot)
    vue.nb_bobines = nb
    return vue


# --- Mouvements ----------------------------------------------------------------------


@router.get("/stock/soldes", response_model=list[SoldeArticle], tags=["Stock"])
def soldes(ctx: Lecture, niveau: Annotated[NiveauStock | None, Query()] = None,
           article_id: uuid.UUID | None = None,
           sous_seuil: Annotated[bool, Query(description="Seulement sous le seuil minimum")] = False):
    return service.soldes(ctx.db, ctx.utilisateur, niveau=niveau, article_id=article_id,
                          sous_seuil=sous_seuil)


@router.get("/stock/mouvements", response_model=list[MouvementPublic], tags=["Stock"])
def lister_mouvements(ctx: Lecture, article_id: uuid.UUID | None = None,
                      type: Annotated[TypeMouvement | None, Query()] = None,
                      statut: Annotated[str | None, Query(pattern="^(en_attente|valide|rejete)$")] = None,
                      avant: Annotated[datetime | None, Query(description="Plus anciens que")] = None,
                      limite: Annotated[int, Query(ge=1, le=200)] = 50):
    lignes = service.lister_mouvements(ctx.db, ctx.utilisateur, article_id=article_id, type_=type,
                                       statut=statut, avant=avant, limite=limite)
    return [_vue_mouvement(m, v) for m, v in lignes]


@router.post("/stock/mouvements", response_model=MouvementPublic, status_code=status.HTTP_201_CREATED,
             tags=["Stock"])
def creer_mouvement(demande: MouvementCreation, ctx: Saisie):
    mouvement = service.creer_mouvement_manuel(ctx.db, ctx.utilisateur, demande.model_dump())
    return _vue_mouvement(mouvement, None)


@router.post("/stock/mouvements/{mouvement_id}/validation", response_model=MouvementPublic, tags=["Stock"])
def valider_mouvement(mouvement_id: uuid.UUID, demande: ValidationDemande,
                      ctx: Annotated[Contexte, Depends(contexte_actif)]):
    # Le droit exact depend du type de mouvement : verifie dans le service.
    mouvement, validation = service.valider_mouvement(ctx.db, ctx.utilisateur, mouvement_id,
                                                      demande.decision, demande.motif)
    return _vue_mouvement(mouvement, validation)


# --- Reservations -------------------------------------------------------------------------


@router.get("/stock/reservations", response_model=list[ReservationPublic], tags=["Stock"])
def lister_reservations(ctx: Lecture,
                        statut: Annotated[str | None, Query(pattern="^(ouverte|levee)$")] = None,
                        article_id: uuid.UUID | None = None):
    return service.lister_reservations(ctx.db, ctx.utilisateur, statut, article_id)


@router.post("/stock/reservations", response_model=ReservationPublic, status_code=status.HTTP_201_CREATED,
             tags=["Stock"])
def creer_reservation(demande: ReservationCreation, ctx: Saisie):
    return service.creer_reservation(ctx.db, ctx.utilisateur, demande.model_dump())


@router.post("/stock/reservations/{reservation_id}/lever", response_model=ReservationPublic, tags=["Stock"])
def lever_reservation(reservation_id: uuid.UUID, ctx: Saisie):
    return service.lever_reservation(ctx.db, ctx.utilisateur, reservation_id)


# --- Lots, bobines, receptions -----------------------------------------------------------------


@router.get("/lots", response_model=list[LotPublic], tags=["Lots et bobines"])
def lister_lots(ctx: Lecture):
    return [_vue_lot(lot, nb) for lot, nb in service.lister_lots(ctx.db, ctx.utilisateur)]


@router.get("/lots/{lot_id}", response_model=LotPublic, tags=["Lots et bobines"])
def lire_lot(lot_id: uuid.UUID, ctx: Lecture):
    return _vue_lot(*service.charger_lot(ctx.db, ctx.utilisateur, lot_id))


@router.get("/bobines", response_model=list[BobinePublic], tags=["Lots et bobines"])
def lister_bobines(ctx: Lecture, lot_id: uuid.UUID | None = None,
                   statut: Annotated[StatutBobine | None, Query()] = None,
                   couleur: Annotated[CouleurFinition | None, Query()] = None):
    return service.lister_bobines(ctx.db, ctx.utilisateur, lot_id=lot_id, statut=statut, couleur=couleur)


@router.post("/receptions", response_model=LotPublic, status_code=status.HTTP_201_CREATED,
             tags=["Lots et bobines"])
def creer_reception(demande: ReceptionCreation, ctx: Saisie):
    lot = service.creer_reception(ctx.db, ctx.utilisateur, demande.model_dump())
    return _vue_lot(lot, len(demande.bobines))


# --- Import de packing list ---------------------------------------------------------------------


def _detail_import(ctx: Contexte, importation) -> ImportDetail:
    detail = ImportDetail.model_validate({**ImportPublic.model_validate(importation).model_dump(),
                                          "lignes": service.lignes_import(ctx.db, importation)},
                                         from_attributes=True)
    return detail


@router.get("/imports-colisage", response_model=list[ImportPublic], tags=["Import packing list"])
def lister_imports(ctx: Lecture, statut: Annotated[StatutImport | None, Query()] = None):
    return service.lister_imports(ctx.db, ctx.utilisateur, statut)


@router.post("/imports-colisage", response_model=ImportDetail, status_code=status.HTTP_201_CREATED,
             tags=["Import packing list"])
def creer_import(demande: ImportCreation, ctx: Saisie):
    """Etape 1 : analyse sans rien ecrire en stock. Renvoie l'apercu et les anomalies."""
    return _detail_import(ctx, service.creer_import(ctx.db, ctx.utilisateur, demande.model_dump()))


@router.get("/imports-colisage/{import_id}", response_model=ImportDetail, tags=["Import packing list"])
def lire_import(import_id: uuid.UUID, ctx: Lecture):
    return _detail_import(ctx, service.charger_import(ctx.db, ctx.utilisateur, import_id))


@router.post("/imports-colisage/{import_id}/valider", response_model=ImportDetail,
             tags=["Import packing list"])
def valider_import(import_id: uuid.UUID, ctx: ValidationReception):
    """Etape 2 : cree le lot, les bobines et les receptions. Refuse s'il reste une anomalie bloquante."""
    return _detail_import(ctx, service.valider_import(ctx.db, ctx.utilisateur, import_id))


@router.post("/imports-colisage/{import_id}/annuler", response_model=ImportDetail,
             tags=["Import packing list"])
def annuler_import(import_id: uuid.UUID, ctx: Saisie):
    return _detail_import(ctx, service.annuler_import(ctx.db, ctx.utilisateur, import_id))

