"""Points d'entree HTTP du module production. Aucune regle ici : tout est dans service.py.

Un point d'entree par transition de la machine a etats : jamais de PATCH
generique sur le statut. Chaque transition exige son propre droit.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.modules.identite.dependances import Contexte, contexte_actif, exiger
from app.modules.production import service
from app.modules.production.models import StatutOF
from app.modules.production.schemas import (
    Annulation,
    OrdreCreation,
    OrdreDetail,
    OrdreModification,
    OrdrePublic,
    PrevisionDemande,
    PrevisionPublic,
    ResultatCalcule,
    ResultatSaisie,
    SortieMatieres,
)

router = APIRouter(prefix="/api", tags=["Production"])

Lecture = Annotated[Contexte, Depends(exiger("production.consulter"))]
Saisie = Annotated[Contexte, Depends(exiger("production.saisir"))]
Validation = Annotated[Contexte, Depends(exiger("production.valider"))]
Cloture = Annotated[Contexte, Depends(exiger("production.cloturer"))]
Annule = Annotated[Contexte, Depends(exiger("production.annuler"))]


def _detail(ctx: Contexte, ordre) -> OrdreDetail:
    vue = OrdreDetail.model_validate(ordre)
    resultat = service.resultat_calcule(ctx.db, ordre)
    if resultat is not None:
        vue.resultat = ResultatCalcule(
            pieces_brutes=resultat.pieces_brutes, pieces_non_conformes=resultat.pieces_non_conformes,
            pieces_conformes=resultat.pieces_conformes, cartons_complets=resultat.cartons_complets,
            pieces_restantes=resultat.pieces_restantes, ecart_pieces=resultat.ecart_pieces,
            ecart_pourcentage=resultat.ecart_pourcentage, rendement=resultat.rendement,
            ecart_comptage=resultat.ecart_comptage, coherent=resultat.coherent)
    vue.transitions = service.transitions(ctx.db, ordre)
    return vue


@router.post("/production/previsions", response_model=PrevisionPublic)
def previsualiser(demande: PrevisionDemande, ctx: Lecture):
    """Calcule la prevision sans rien creer : pour l'ecran de preparation d'un ordre."""
    return service.previsualiser(ctx.db, ctx.utilisateur, demande.modele_id, demande.bobine_id,
                                 demande.metrage_engage)


@router.get("/ordres-fabrication", response_model=list[OrdrePublic])
def lister(ctx: Lecture, statut: Annotated[StatutOF | None, Query()] = None,
           bobine_id: uuid.UUID | None = None, modele_id: uuid.UUID | None = None):
    return service.lister(ctx.db, ctx.utilisateur, statut=statut, bobine_id=bobine_id, modele_id=modele_id)


@router.get("/ordres-fabrication/{ordre_id}", response_model=OrdreDetail)
def lire(ordre_id: uuid.UUID, ctx: Lecture):
    return _detail(ctx, service.charger(ctx.db, ctx.utilisateur, ordre_id))


@router.post("/ordres-fabrication", response_model=OrdreDetail, status_code=status.HTTP_201_CREATED)
def creer(demande: OrdreCreation, ctx: Saisie):
    return _detail(ctx, service.creer(ctx.db, ctx.utilisateur, demande.model_dump()))


@router.patch("/ordres-fabrication/{ordre_id}", response_model=OrdreDetail)
def modifier(ordre_id: uuid.UUID, demande: OrdreModification, ctx: Saisie):
    return _detail(ctx, service.modifier_brouillon(ctx.db, ctx.utilisateur, ordre_id,
                                                   demande.model_dump(exclude_unset=True)))


@router.post("/ordres-fabrication/{ordre_id}/soumettre", response_model=OrdreDetail)
def soumettre(ordre_id: uuid.UUID, ctx: Saisie):
    return _detail(ctx, service.soumettre(ctx.db, ctx.utilisateur, ordre_id))


@router.post("/ordres-fabrication/{ordre_id}/valider-matieres", response_model=OrdreDetail)
def valider_matieres(ordre_id: uuid.UUID, request: Request,
                     base: Annotated[Contexte, Depends(contexte_actif)],
                     demande: SortieMatieres | None = None):
    """Sortie des tubes. Normale : responsable stock. Avec derogation (stock insuffisant) : DG ou
    delegataire, meme droit que les sorties exceptionnelles : sortir ce qui n'est pas en stock engage l'usine.
    """
    motif = demande.derogation_motif if demande else None
    ctx = exiger("stock.valider_sortie_exceptionnelle" if motif else "stock.executer_sortie")(request, base)
    return _detail(ctx, service.valider_matieres(ctx.db, ctx.utilisateur, ordre_id, derogation_motif=motif))


@router.post("/ordres-fabrication/{ordre_id}/demarrer", response_model=OrdreDetail)
def demarrer(ordre_id: uuid.UUID, ctx: Saisie):
    return _detail(ctx, service.demarrer(ctx.db, ctx.utilisateur, ordre_id))


@router.put("/ordres-fabrication/{ordre_id}/resultat", response_model=OrdreDetail)
def saisir_resultat(ordre_id: uuid.UUID, demande: ResultatSaisie, ctx: Saisie):
    """Saisie du rapport de l'operateur. Renvoie le calcul et le controle de coherence, sans les imposer :
    seule la validation exige un comptage coherent."""
    return _detail(ctx, service.saisir_resultat(ctx.db, ctx.utilisateur, ordre_id, demande.model_dump()))


@router.post("/ordres-fabrication/{ordre_id}/valider-resultat", response_model=OrdreDetail)
def valider_resultat(ordre_id: uuid.UUID, ctx: Validation):
    return _detail(ctx, service.valider_resultat(ctx.db, ctx.utilisateur, ordre_id))


@router.post("/ordres-fabrication/{ordre_id}/cloturer", response_model=OrdreDetail)
def cloturer(ordre_id: uuid.UUID, ctx: Cloture):
    return _detail(ctx, service.cloturer(ctx.db, ctx.utilisateur, ordre_id))


@router.post("/ordres-fabrication/{ordre_id}/annuler", response_model=OrdreDetail)
def annuler(ordre_id: uuid.UUID, demande: Annulation, ctx: Annule):
    return _detail(ctx, service.annuler(ctx.db, ctx.utilisateur, ordre_id, demande.motif))
