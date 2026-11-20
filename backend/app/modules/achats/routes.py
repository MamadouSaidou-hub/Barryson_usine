"""Points d'entree HTTP du module achats. Aucune regle ici : tout est dans service.py.

Un point d'entree par etape du circuit, chacun avec son propre droit : le responsable stock
prepare et passe la commande, le DG la valide, le responsable stock controle la reception.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.modules.achats import service
from app.modules.achats.models import StatutCommande, StatutReception
from app.modules.achats.schemas import (
    Commande,
    CommandeCreation,
    CommandeDetail,
    CommandeModification,
    CommandePublic,
    ControleDemande,
    Decision,
    LigneCommandePublic,
    LigneReceptionPublic,
    ReceptionCreation,
    ReceptionDetail,
    ReceptionPublic,
    ReceptionResume,
    TransitionPublic,
)
from app.modules.identite.dependances import Contexte, contexte_actif, exiger

router = APIRouter(prefix="/api", tags=["Achats"])

Lecture = Annotated[Contexte, Depends(exiger("achats.consulter"))]
Saisie = Annotated[Contexte, Depends(exiger("achats.saisir"))]
ValidationDG = Annotated[Contexte, Depends(exiger("achats.valider"))]
SaisieStock = Annotated[Contexte, Depends(exiger("stock.saisir"))]
ControleStock = Annotated[Contexte, Depends(exiger("stock.valider_reception"))]


def _detail_commande(ctx: Contexte, commande) -> CommandeDetail:
    vue = CommandeDetail.model_validate(commande)
    lignes = service.vue_lignes_commande(ctx.db, commande)
    vue.lignes = [LigneCommandePublic.model_validate(ligne) for ligne in lignes]
    montants = [ligne["montant"] for ligne in lignes if ligne["montant"] is not None]
    vue.montant_total = sum(montants) if montants else None
    if vue.montant_total is not None:
        if commande.devise == "GNF":
            vue.montant_total_gnf = vue.montant_total
        elif commande.taux_change_gnf is not None:
            vue.montant_total_gnf = vue.montant_total * commande.taux_change_gnf
    vue.prix_manquants = sum(1 for ligne in lignes if ligne["montant"] is None)
    vue.receptions = [ReceptionResume.model_validate(r) for r in service.receptions_de(ctx.db, commande.id)]
    vue.transitions = [TransitionPublic.model_validate(t) for t in service.transitions(ctx.db, commande)]
    return vue


def _detail_reception(ctx: Contexte, reception) -> ReceptionDetail:
    vue = ReceptionDetail.model_validate(reception)
    lignes = service.vue_lignes_reception(ctx.db, reception)
    vue.lignes = [LigneReceptionPublic.model_validate(ligne) for ligne in lignes]
    if reception.statut == "en_controle":
        vue.avertissements = service.avertissements_reception(ctx.db, reception, lignes)
    vue.avec_ecarts = reception.statut in ("acceptee_avec_reserves", "refusee") or any(
        ligne["quantite_acceptee"] is not None and ligne["quantite_acceptee"] < ligne["quantite_recue"]
        for ligne in lignes
    )
    return vue


# --- Commandes ------------------------------------------------------------------------------------


@router.get("/commandes-achat", response_model=list[CommandePublic])
def lister(
    ctx: Lecture,
    statut: Annotated[StatutCommande | None, Query()] = None,
    fournisseur_id: uuid.UUID | None = None,
    en_attente_marchandise: Annotated[
        bool, Query(description="Conteneurs attendus, plus proches d'abord")
    ] = False,
):
    return service.lister(
        ctx.db,
        ctx.utilisateur,
        statut=statut,
        fournisseur_id=fournisseur_id,
        en_attente_marchandise=en_attente_marchandise,
    )


@router.get("/commandes-achat/{commande_id}", response_model=CommandeDetail)
def lire(commande_id: uuid.UUID, ctx: Lecture):
    return _detail_commande(ctx, service.charger(ctx.db, ctx.utilisateur, commande_id))


@router.post("/commandes-achat", response_model=CommandeDetail, status_code=status.HTTP_201_CREATED)
def creer(demande: CommandeCreation, ctx: Saisie):
    return _detail_commande(ctx, service.creer(ctx.db, ctx.utilisateur, demande.model_dump()))


@router.put("/commandes-achat/{commande_id}", response_model=CommandeDetail)
def modifier(commande_id: uuid.UUID, demande: CommandeModification, ctx: Saisie):
    return _detail_commande(
        ctx, service.modifier(ctx.db, ctx.utilisateur, commande_id, demande.model_dump(exclude_unset=True))
    )


@router.post("/commandes-achat/{commande_id}/soumettre", response_model=CommandeDetail)
def soumettre(commande_id: uuid.UUID, ctx: Saisie):
    return _detail_commande(ctx, service.soumettre(ctx.db, ctx.utilisateur, commande_id))


@router.post("/commandes-achat/{commande_id}/valider", response_model=CommandeDetail)
def valider(commande_id: uuid.UUID, ctx: ValidationDG):
    return _detail_commande(ctx, service.valider(ctx.db, ctx.utilisateur, commande_id, ctx.delegation_id))


@router.post("/commandes-achat/{commande_id}/refuser", response_model=CommandeDetail)
def refuser(commande_id: uuid.UUID, demande: Decision, ctx: ValidationDG):
    return _detail_commande(ctx, service.refuser(ctx.db, ctx.utilisateur, commande_id, demande.motif))


@router.post("/commandes-achat/{commande_id}/commander", response_model=CommandeDetail)
def commander(commande_id: uuid.UUID, ctx: Saisie, demande: Commande | None = None):
    reference = demande.reference_fournisseur if demande else None
    return _detail_commande(ctx, service.commander(ctx.db, ctx.utilisateur, commande_id, reference))


@router.post("/commandes-achat/{commande_id}/annuler", response_model=CommandeDetail)
def annuler(commande_id: uuid.UUID, demande: Decision, ctx: Annotated[Contexte, Depends(contexte_actif)]):
    # Le droit exact depend de l'etat (initiateur avant validation, DG ensuite) : verifie dans le service.
    return _detail_commande(ctx, service.annuler(ctx.db, ctx.utilisateur, commande_id, demande.motif))


@router.post("/commandes-achat/{commande_id}/solder", response_model=CommandeDetail)
def solder(commande_id: uuid.UUID, demande: Decision, ctx: Saisie):
    return _detail_commande(ctx, service.solder(ctx.db, ctx.utilisateur, commande_id, demande.motif))


# --- Receptions et controle de conformite ---------------------------------------------------------


@router.post(
    "/commandes-achat/{commande_id}/receptions",
    response_model=ReceptionDetail,
    status_code=status.HTTP_201_CREATED,
)
def receptionner(commande_id: uuid.UUID, demande: ReceptionCreation, ctx: SaisieStock):
    """La marchandise est arrivee. Rien n'entre en stock avant le controle de conformite."""
    return _detail_reception(
        ctx, service.receptionner(ctx.db, ctx.utilisateur, commande_id, demande.model_dump())
    )


@router.get("/receptions-achat", response_model=list[ReceptionPublic])
def lister_receptions(
    ctx: Lecture,
    statut: Annotated[StatutReception | None, Query()] = None,
    commande_id: uuid.UUID | None = None,
    avec_ecarts: Annotated[bool, Query(description="Litiges : réserves ou refus")] = False,
):
    return service.lister_receptions(
        ctx.db, ctx.utilisateur, statut=statut, commande_id=commande_id, avec_ecarts=avec_ecarts
    )


@router.get("/receptions-achat/{reception_id}", response_model=ReceptionDetail)
def lire_reception(reception_id: uuid.UUID, ctx: Lecture):
    return _detail_reception(ctx, service.charger_reception(ctx.db, ctx.utilisateur, reception_id))


@router.post("/receptions-achat/{reception_id}/controle", response_model=ReceptionDetail)
def controler(reception_id: uuid.UUID, demande: ControleDemande, ctx: ControleStock):
    """Decide : acceptee, avec reserves, ou refusee. Seules les quantites acceptees entrent en stock."""
    return _detail_reception(
        ctx, service.controler(ctx.db, ctx.utilisateur, reception_id, demande.model_dump())
    )
