"""Regles du module achats (M03).

Rien n'entre en stock a la reception : la marchandise arrivee attend un controle de conformite
(documentaire puis quantitatif). Seules les quantites acceptees au controle creent des mouvements.
"""

import uuid
from collections import Counter
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import journaliser, maintenant
from app.core.erreurs import Conflit, DonneesInvalides, Introuvable, OperationInterdite
from app.core.numerotation import prochain_numero
from app.core.transactions import transactionnel
from app.modules.achats.models import (
    ETATS_ATTENTE_MARCHANDISE,
    ArticleCatalogue,
    CommandeAchat,
    LigneCommandeAchat,
    LigneReception,
    ReceptionAchat,
    TransitionCommande,
)
from app.modules.identite import delegations
from app.modules.identite.models import Utilisateur
from app.modules.identite.permissions import ConflitDeSeparation, a_la_permission, exiger_valideur_distinct
from app.modules.referentiel import service as referentiel
from app.modules.referentiel.models import Article, Fournisseur
from app.modules.stock import service as stock
from app.modules.stock.models import ImportColisage, LigneImportColisage

STATUTS_ACCEPTES = ("acceptee", "acceptee_avec_reserves")


# --- Acces ----------------------------------------------------------------------------------------


def charger(
    db: Session, acteur: Utilisateur, commande_id: uuid.UUID, *, verrou: bool = False
) -> CommandeAchat:
    requete = select(CommandeAchat).where(
        CommandeAchat.entreprise_id == acteur.entreprise_id, CommandeAchat.id == commande_id
    )
    commande = db.scalar(requete.with_for_update() if verrou else requete)
    if commande is None:
        raise Introuvable()
    return commande


def charger_reception(
    db: Session, acteur: Utilisateur, reception_id: uuid.UUID, *, verrou: bool = False
) -> ReceptionAchat:
    requete = select(ReceptionAchat).where(
        ReceptionAchat.entreprise_id == acteur.entreprise_id, ReceptionAchat.id == reception_id
    )
    reception = db.scalar(requete.with_for_update() if verrou else requete)
    if reception is None:
        raise Introuvable()
    return reception


def lister(
    db: Session,
    acteur: Utilisateur,
    *,
    statut: str | None,
    fournisseur_id: uuid.UUID | None,
    en_attente_marchandise: bool,
) -> list[CommandeAchat]:
    requete = select(CommandeAchat).where(CommandeAchat.entreprise_id == acteur.entreprise_id)
    if statut:
        requete = requete.where(CommandeAchat.statut == statut)
    if fournisseur_id:
        requete = requete.where(CommandeAchat.fournisseur_id == fournisseur_id)
    if en_attente_marchandise:
        # Conteneurs attendus : les plus proches d'abord, ceux sans date prevue a la fin.
        requete = requete.where(CommandeAchat.statut.in_(ETATS_ATTENTE_MARCHANDISE)).order_by(
            CommandeAchat.date_arrivee_prevue.asc().nulls_last(), CommandeAchat.cree_le
        )
    else:
        requete = requete.order_by(CommandeAchat.cree_le.desc())
    return list(db.scalars(requete.limit(300)))


def lister_receptions(
    db: Session, acteur: Utilisateur, *, statut: str | None, commande_id: uuid.UUID | None, avec_ecarts: bool
) -> list[ReceptionAchat]:
    requete = select(ReceptionAchat).where(ReceptionAchat.entreprise_id == acteur.entreprise_id)
    if statut:
        requete = requete.where(ReceptionAchat.statut == statut)
    if commande_id:
        requete = requete.where(ReceptionAchat.commande_id == commande_id)
    if avec_ecarts:
        requete = requete.where(ReceptionAchat.statut.in_(("acceptee_avec_reserves", "refusee")))
    return list(db.scalars(requete.order_by(ReceptionAchat.cree_le.desc()).limit(300)))


def transitions(db: Session, commande: CommandeAchat) -> list[TransitionCommande]:
    return list(
        db.scalars(
            select(TransitionCommande)
            .where(TransitionCommande.commande_id == commande.id)
            .order_by(TransitionCommande.cree_le, TransitionCommande.id)
        )
    )


def lignes_de(db: Session, commande_id: uuid.UUID) -> list[LigneCommandeAchat]:
    return list(
        db.scalars(
            select(LigneCommandeAchat)
            .where(LigneCommandeAchat.commande_id == commande_id)
            .order_by(LigneCommandeAchat.rang)
        )
    )


def receptions_de(db: Session, commande_id: uuid.UUID) -> list[ReceptionAchat]:
    return list(
        db.scalars(
            select(ReceptionAchat)
            .where(ReceptionAchat.commande_id == commande_id)
            .order_by(ReceptionAchat.cree_le)
        )
    )


def quantites_acceptees(
    db: Session, commande_id: uuid.UUID, *, sauf_reception: uuid.UUID | None = None
) -> dict[uuid.UUID, Decimal]:
    """Cumul, par ligne de commande, des quantites acceptees au controle (la seule qui compte)."""
    requete = (
        select(LigneReception.ligne_commande_id, func.sum(LigneReception.quantite_acceptee))
        .join(ReceptionAchat, ReceptionAchat.id == LigneReception.reception_id)
        .where(ReceptionAchat.commande_id == commande_id, ReceptionAchat.statut.in_(STATUTS_ACCEPTES))
    )
    if sauf_reception:
        requete = requete.where(ReceptionAchat.id != sauf_reception)
    return {
        ligne: total or Decimal(0)
        for ligne, total in db.execute(requete.group_by(LigneReception.ligne_commande_id))
    }


def vue_lignes_commande(db: Session, commande: CommandeAchat) -> list[dict[str, Any]]:
    acceptees = quantites_acceptees(db, commande.id)
    lignes = lignes_de(db, commande.id)
    articles = {
        a.id: a
        for a in db.scalars(select(Article).where(Article.id.in_([ligne.article_id for ligne in lignes])))
    }
    catalogue = {
        e.id: e
        for e in db.scalars(
            select(ArticleCatalogue).where(
                ArticleCatalogue.id.in_([ligne.catalogue_id for ligne in lignes if ligne.catalogue_id])
            )
        )
    }
    vue = []
    for ligne in lignes:
        article, recu = articles[ligne.article_id], acceptees.get(ligne.id, Decimal(0))
        entree = catalogue.get(ligne.catalogue_id)
        vue.append(
            {
                "id": ligne.id,
                "rang": ligne.rang,
                "article_id": ligne.article_id,
                "article_code": article.code,
                "article_nom": article.nom,
                "unite": article.unite_gestion,
                "quantite_commandee": ligne.quantite_commandee,
                "prix_unitaire": ligne.prix_unitaire,
                "couleur_finition": ligne.couleur_finition,
                "catalogue_id": ligne.catalogue_id,
                "catalogue_libelle": entree.libelle if entree else None,
                "reference_couleur_fournisseur": entree.reference_couleur_fournisseur if entree else None,
                "poids_net_type_kg": entree.poids_net_type_kg if entree else None,
                "metrage_type_m": entree.metrage_type_m if entree else None,
                "quantite_recue_acceptee": recu,
                "solde": max(ligne.quantite_commandee - recu, Decimal(0)),
                "montant": None
                if ligne.prix_unitaire is None
                else ligne.quantite_commandee * ligne.prix_unitaire,
            }
        )
    return vue


# --- Machine a etats de la commande ---------------------------------------------------------------


def _passer(
    db: Session,
    commande: CommandeAchat,
    acteur: Utilisateur,
    attendus: tuple[str, ...],
    vers: str,
    motif: str | None = None,
) -> None:
    if commande.statut not in attendus:
        raise Conflit(
            f"Transition impossible : la commande {commande.numero} est « {commande.statut} », "
            f"elle doit être « {' ou '.join(attendus)} »."
        )
    db.add(
        TransitionCommande(
            entreprise_id=commande.entreprise_id,
            commande_id=commande.id,
            de_statut=commande.statut,
            vers_statut=vers,
            acteur_id=acteur.id,
            motif=motif,
        )
    )
    commande.statut = vers


def _commit(db: Session, message: str = "Modification concurrente : réessayez.") -> None:
    try:
        db.commit()
    except IntegrityError as erreur:
        db.rollback()
        raise Conflit(message) from erreur


def _verifier_lignes(db: Session, acteur: Utilisateur, lignes: list[dict[str, Any]],
                     fournisseur_id: uuid.UUID) -> list[Article]:
    for ligne in lignes:
        _appliquer_catalogue(db, acteur, ligne, fournisseur_id)
    cles = Counter((ligne["article_id"], ligne.get("couleur_finition"), ligne.get("catalogue_id"))
                   for ligne in lignes)
    doublons = [cle for cle, nombre in cles.items() if nombre > 1]
    if doublons:
        raise DonneesInvalides(
            "Une même référence (article, finition et produit du catalogue) ne peut figurer qu'une "
            "seule fois : regroupez les quantités."
        )
    articles = []
    for ligne in lignes:
        article = referentiel.charger_ou_invalide(db, Article, acteur, ligne["article_id"], "Article")
        if not article.actif:
            raise DonneesInvalides(f"L'article {article.code} est désactivé.")
        if article.niveau_stock == "produit_fini":
            raise DonneesInvalides(
                f"L'article {article.code} est un produit fini : il se fabrique, il ne s'achète pas."
            )
        if ligne.get("couleur_finition") and article.unite_gestion != "rouleau":
            raise DonneesInvalides(f"La finition ne s'applique qu'aux bobines (article {article.code}).")
        articles.append(article)
    return articles


def _appliquer_catalogue(db: Session, acteur: Utilisateur, ligne: dict[str, Any],
                         fournisseur_id: uuid.UUID) -> None:
    """Une ligne tiree du catalogue doit venir du fournisseur de la commande et en reprendre la finition."""
    if ligne.get("catalogue_id") is None:
        return
    try:
        entree = _entree_catalogue(db, acteur, ligne["catalogue_id"])
    except Introuvable as erreur:
        raise DonneesInvalides("Produit du catalogue introuvable.") from erreur
    if not entree.actif:
        raise DonneesInvalides(f"Le produit « {entree.libelle} » du catalogue est désactivé.")
    if entree.fournisseur_id != fournisseur_id:
        raise DonneesInvalides(
            f"Le produit « {entree.libelle} » n'est pas dans le catalogue de ce fournisseur.")
    if entree.article_id != ligne["article_id"]:
        raise DonneesInvalides(f"L'article de la ligne ne correspond pas au produit « {entree.libelle} ».")
    if entree.couleur_finition is not None:
        if ligne.get("couleur_finition") not in (None, entree.couleur_finition):
            raise DonneesInvalides(f"La finition de la ligne contredit le produit « {entree.libelle} ».")
        ligne["couleur_finition"] = entree.couleur_finition


def _verifier_taux(devise: str, taux: Decimal | None) -> None:
    if devise == "GNF" and taux is not None and taux != 1:
        raise DonneesInvalides("Une commande en GNF n'a pas de taux de change.")


def _fournisseur_actif(db: Session, acteur: Utilisateur, fournisseur_id: uuid.UUID) -> Fournisseur:
    fournisseur = referentiel.charger_ou_invalide(db, Fournisseur, acteur, fournisseur_id, "Fournisseur")
    if not fournisseur.actif:
        raise DonneesInvalides(f"Le fournisseur {fournisseur.code} est désactivé.")
    return fournisseur


def _inserer_lignes(db: Session, commande: CommandeAchat, lignes: list[dict[str, Any]]) -> None:
    db.add_all(
        LigneCommandeAchat(commande_id=commande.id, rang=rang, **ligne)
        for rang, ligne in enumerate(lignes, start=1)
    )


# --- Preparation de la commande -------------------------------------------------------------------


@transactionnel
def creer(db: Session, acteur: Utilisateur, donnees: dict[str, Any]) -> CommandeAchat:
    _fournisseur_actif(db, acteur, donnees["fournisseur_id"])
    _verifier_taux(donnees["devise"], donnees.get("taux_change_gnf"))
    lignes = donnees.pop("lignes")
    _verifier_lignes(db, acteur, lignes, donnees["fournisseur_id"])
    commande = CommandeAchat(
        entreprise_id=acteur.entreprise_id,
        numero=prochain_numero(db, acteur.entreprise_id, "BCA"),
        cree_par=acteur.id,
        **donnees,
    )
    db.add(commande)
    db.flush()
    _inserer_lignes(db, commande, lignes)
    db.add(
        TransitionCommande(
            entreprise_id=commande.entreprise_id,
            commande_id=commande.id,
            de_statut=None,
            vers_statut="brouillon",
            acteur_id=acteur.id,
        )
    )
    _commit(db)
    return commande


@transactionnel
def modifier(
    db: Session, acteur: Utilisateur, commande_id: uuid.UUID, changements: dict[str, Any]
) -> CommandeAchat:
    commande = charger(db, acteur, commande_id, verrou=True)
    if commande.statut != "brouillon":
        raise Conflit("Seule une commande en brouillon peut être modifiée.")
    if changements.get("fournisseur_id"):
        _fournisseur_actif(db, acteur, changements["fournisseur_id"])
    lignes = changements.pop("lignes", None)
    ancien_fournisseur = commande.fournisseur_id
    for champ, valeur in changements.items():
        setattr(commande, champ, valeur)
    _verifier_taux(commande.devise, commande.taux_change_gnf)
    if lignes is None and commande.fournisseur_id != ancien_fournisseur and any(
            ligne.catalogue_id for ligne in lignes_de(db, commande.id)):
        raise DonneesInvalides(
            "Des lignes viennent du catalogue de l'ancien fournisseur : renvoyez les lignes de la commande.")
    if lignes is not None:
        _verifier_lignes(db, acteur, lignes, commande.fournisseur_id)
        for ancienne in lignes_de(db, commande.id):
            db.delete(ancienne)
        db.flush()
        _inserer_lignes(db, commande, lignes)
    _commit(db)
    return commande


@transactionnel
def soumettre(db: Session, acteur: Utilisateur, commande_id: uuid.UUID) -> CommandeAchat:
    commande = charger(db, acteur, commande_id, verrou=True)
    _passer(db, commande, acteur, ("brouillon",), "soumise")
    _fournisseur_actif(db, acteur, commande.fournisseur_id)
    _commit(db)
    return commande


@transactionnel
def valider(
    db: Session, acteur: Utilisateur, commande_id: uuid.UUID, delegation_id: uuid.UUID | None = None
) -> CommandeAchat:
    """Le DG, ou un delegataire qu'il a designe, autorise la commande. Seuils non fixes : toute commande
    passe par l'un d'eux."""
    commande = charger(db, acteur, commande_id, verrou=True)
    # Avant tout changement d'etat : un refus ne doit laisser aucune trace autre que son journal.
    try:
        exiger_valideur_distinct(commande.cree_par, acteur.id)
    except ConflitDeSeparation as erreur:
        journaliser(
            db, "validation.refusee_meme_personne", cible_type="commandes_achat", cible_id=commande.id
        )
        db.commit()
        raise OperationInterdite(str(erreur)) from erreur
    _passer(db, commande, acteur, ("soumise",), "validee")
    commande.valide_par, commande.valide_le = acteur.id, maintenant()
    commande.valide_via_delegation_id = delegation_id
    _commit(db)
    return commande


@transactionnel
def refuser(db: Session, acteur: Utilisateur, commande_id: uuid.UUID, motif: str) -> CommandeAchat:
    commande = charger(db, acteur, commande_id, verrou=True)
    _passer(db, commande, acteur, ("soumise",), "refusee", motif)
    commande.motif_decision = motif
    _commit(db)
    return commande


@transactionnel
def commander(
    db: Session, acteur: Utilisateur, commande_id: uuid.UUID, reference_fournisseur: str | None
) -> CommandeAchat:
    """La commande validee est passee au fournisseur : on attend desormais la marchandise."""
    commande = charger(db, acteur, commande_id, verrou=True)
    _passer(db, commande, acteur, ("validee",), "commandee")
    if reference_fournisseur:
        commande.reference_fournisseur = reference_fournisseur
    commande.commandee_le = maintenant()
    _commit(db)
    return commande


@transactionnel
def annuler(db: Session, acteur: Utilisateur, commande_id: uuid.UUID, motif: str) -> CommandeAchat:
    peut_saisir = a_la_permission(acteur.role, "achats.saisir")
    peut_valider, _ = delegations.droit(db, acteur, "achats.valider")
    if not (peut_saisir or peut_valider):  # aucun droit sur les achats : on ne dit rien de la commande
        journaliser(db, "acces.refuse", apres={"permission": "achats.saisir", "commande": str(commande_id)})
        db.commit()
        raise OperationInterdite("Accès refusé.")
    commande = charger(db, acteur, commande_id, verrou=True)
    if commande.statut not in ("brouillon", "soumise", "validee", "commandee"):
        raise Conflit(f"La commande {commande.numero} est « {commande.statut} » : elle ne s'annule plus.")
    # L'initiateur retire sa propre demande tant qu'elle n'est pas autorisee ; ensuite, seul le DG.
    if commande.statut in ("validee", "commandee") and not peut_valider:
        journaliser(db, "acces.refuse", apres={"permission": "achats.valider", "commande": str(commande.id)})
        db.commit()
        raise OperationInterdite("Accès refusé.")
    # Verifications avant de toucher a l'etat : une requete lancee apres le changement provoquerait
    # un enregistrement premature (autoflush), avant que le motif obligatoire ne soit renseigne.
    if db.scalar(
        select(ReceptionAchat.id).where(
            ReceptionAchat.commande_id == commande.id, ReceptionAchat.statut == "en_controle"
        )
    ):
        raise Conflit(
            "Une réception de cette commande attend son contrôle : contrôlez-la (ou refusez-la) "
            "avant d'annuler."
        )
    commande.motif_decision = motif
    _passer(db, commande, acteur, ("brouillon", "soumise", "validee", "commandee"), "annulee", motif)
    _commit(db)
    return commande


@transactionnel
def solder(db: Session, acteur: Utilisateur, commande_id: uuid.UUID, motif: str) -> CommandeAchat:
    """Clot une commande partiellement livree : le reliquat n'arrivera pas (ou est abandonne)."""
    commande = charger(db, acteur, commande_id, verrou=True)
    if db.scalar(
        select(ReceptionAchat.id).where(
            ReceptionAchat.commande_id == commande.id, ReceptionAchat.statut == "en_controle"
        )
    ):
        raise Conflit("Une réception de cette commande attend son contrôle : contrôlez-la avant de solder.")
    commande.motif_decision = motif
    _passer(db, commande, acteur, ("partiellement_recue",), "cloturee", motif)
    _commit(db)
    return commande


# --- Reception de la marchandise ------------------------------------------------------------------


def _import_de_la_reception(
    db: Session,
    acteur: Utilisateur,
    commande: CommandeAchat,
    ligne_bobines: LigneCommandeAchat,
    import_id: uuid.UUID,
) -> ImportColisage:
    importation = stock.charger_import(db, acteur, import_id, verrou=True)
    if importation.statut != "brouillon" or importation.rattache_reception:
        raise Conflit("Cette packing list est déjà utilisée ou n'est plus en brouillon.")
    if importation.article_id != ligne_bobines.article_id:
        raise DonneesInvalides("La packing list porte sur un autre article que la ligne de commande.")
    if importation.fournisseur_id != commande.fournisseur_id:
        raise DonneesInvalides("La packing list vient d'un autre fournisseur que la commande.")
    if importation.nb_bloquantes:
        raise DonneesInvalides(
            f"La packing list a {importation.nb_bloquantes} anomalie(s) bloquante(s) : "
            "corrigez-la et refaites l'import avant de réceptionner."
        )
    return importation


@transactionnel
def receptionner(
    db: Session, acteur: Utilisateur, commande_id: uuid.UUID, donnees: dict[str, Any]
) -> ReceptionAchat:
    commande = charger(db, acteur, commande_id, verrou=True)
    if commande.statut not in ETATS_ATTENTE_MARCHANDISE:
        raise Conflit(
            f"La commande {commande.numero} est « {commande.statut} » : elle n'attend pas de marchandise."
        )
    lignes_commande = {ligne.id: ligne for ligne in lignes_de(db, commande.id)}
    articles = {
        a.id: a
        for a in db.scalars(
            select(Article).where(Article.id.in_([ligne.article_id for ligne in lignes_commande.values()]))
        )
    }
    demandees = donnees["lignes"]
    ids = [ligne["ligne_commande_id"] for ligne in demandees]
    if len(set(ids)) != len(ids):
        raise DonneesInvalides("Une ligne de commande ne peut apparaître qu'une fois dans la réception.")
    inconnues = [i for i in ids if i not in lignes_commande]
    if inconnues:
        raise DonneesInvalides("Ligne de commande étrangère à cette commande.")

    bobines = [
        ligne
        for ligne in demandees
        if articles[lignes_commande[ligne["ligne_commande_id"]].article_id].unite_gestion == "rouleau"
    ]
    import_id, importation = donnees.get("import_colisage_id"), None
    if len(bobines) > 1:
        raise DonneesInvalides("Une réception ne porte que sur un seul lot de bobines (une packing list).")
    if bobines and import_id is None:
        raise DonneesInvalides(
            "Les bobines se réceptionnent avec leur packing list : analysez-la d'abord "
            "(POST /api/imports-colisage) puis rattachez-la à la réception."
        )
    if import_id is not None and not bobines:
        raise DonneesInvalides(
            "Une packing list est fournie mais aucune ligne de bobines n'est réceptionnée."
        )
    if bobines:
        ligne_bobines = lignes_commande[bobines[0]["ligne_commande_id"]]
        importation = _import_de_la_reception(db, acteur, commande, ligne_bobines, import_id)

    reception = ReceptionAchat(
        entreprise_id=acteur.entreprise_id,
        numero=prochain_numero(db, acteur.entreprise_id, "REC"),
        commande_id=commande.id,
        import_colisage_id=import_id,
        date_arrivee=donnees["date_arrivee"],
        conteneur_reference=importation.conteneur_reference
        if importation
        else donnees.get("conteneur_reference"),
        numero_facture=donnees.get("numero_facture") or (importation.numero_facture if importation else None),
        commentaire=donnees.get("commentaire"),
        cree_par=acteur.id,
    )
    db.add(reception)
    db.flush()
    for ligne in demandees:
        source = lignes_commande[ligne["ligne_commande_id"]]
        if importation is not None and ligne in bobines:
            quantite = Decimal(importation.nb_lignes)
        elif ligne.get("quantite_recue") is None:
            raise DonneesInvalides(f"Quantité reçue manquante pour {articles[source.article_id].code}.")
        else:
            quantite = ligne["quantite_recue"]
        db.add(
            LigneReception(
                reception_id=reception.id,
                ligne_commande_id=source.id,
                quantite_recue=quantite,
                observation=ligne.get("observation"),
            )
        )
    if importation is not None:
        importation.rattache_reception = True
    _commit(db, "Cette packing list vient d'être rattachée à une autre réception.")
    return reception


def vue_lignes_reception(db: Session, reception: ReceptionAchat) -> list[dict[str, Any]]:
    lignes = list(
        db.scalars(
            select(LigneReception)
            .where(LigneReception.reception_id == reception.id)
            .order_by(LigneReception.id)
        )
    )
    sources = {ligne.id: ligne for ligne in lignes_de(db, reception.commande_id)}
    articles = {
        a.id: a
        for a in db.scalars(select(Article).where(Article.id.in_([s.article_id for s in sources.values()])))
    }
    acceptees = quantites_acceptees(db, reception.commande_id, sauf_reception=reception.id)
    vue = []
    for ligne in lignes:
        source = sources[ligne.ligne_commande_id]
        article = articles[source.article_id]
        vue.append(
            {
                "id": ligne.id,
                "ligne_commande_id": source.id,
                "article_id": article.id,
                "article_code": article.code,
                "article_nom": article.nom,
                "unite": article.unite_gestion,
                "quantite_commandee": source.quantite_commandee,
                "solde_avant": max(
                    source.quantite_commandee - acceptees.get(source.id, Decimal(0)), Decimal(0)
                ),
                "quantite_recue": ligne.quantite_recue,
                "quantite_acceptee": ligne.quantite_acceptee,
                "observation": ligne.observation,
                "motif_ecart": ligne.motif_ecart,
                "bobines_refusees": list(ligne.bobines_refusees or []),
            }
        )
    return vue


def _lisible(valeur: Decimal) -> str:
    """6.000 -> 6 ; 2.500 -> 2.5 (jamais d'exposant, jamais de zeros inutiles)."""
    texte = f"{valeur:f}"
    return texte.rstrip("0").rstrip(".") if "." in texte else texte


def avertissements_reception(
    db: Session, reception: ReceptionAchat, lignes: list[dict[str, Any]]
) -> list[str]:
    """Ce que le controleur doit savoir avant de decider (jamais bloquant en lui-meme)."""
    notes = []
    for ligne in lignes:
        if ligne["quantite_recue"] > ligne["solde_avant"]:
            notes.append(
                f"{ligne['article_code']} : {_lisible(ligne['quantite_recue'])} {ligne['unite']} "
                f"reçu(s) pour un solde de {_lisible(ligne['solde_avant'])} sur la commande."
            )
    if reception.import_colisage_id:
        importation = db.get(ImportColisage, reception.import_colisage_id)
        if importation and importation.nb_avertissements:
            notes.append(
                f"La packing list porte {importation.nb_avertissements} avertissement(s) "
                "(métrage manquant, poids atypique...)."
            )
        attendues = {ligne.id: ligne for ligne in lignes_de(db, reception.commande_id)}
        for ligne in lignes:
            finition = attendues[ligne["ligne_commande_id"]].couleur_finition
            if finition and importation:
                autres = (
                    db.scalar(
                        select(func.count())
                        .select_from(LigneImportColisage)
                        .where(
                            LigneImportColisage.import_id == importation.id,
                            LigneImportColisage.couleur_finition != finition,
                        )
                    )
                    or 0
                )
                if autres:
                    notes.append(
                        f"{autres} bobine(s) de la packing list n'ont pas la finition commandée ({finition})."
                    )
    return notes


# --- Controle de conformite -----------------------------------------------------------------------


def _exiger_ecart_motive(ligne: dict[str, Any], recue: Decimal, acceptee: Decimal, code: str) -> None:
    if acceptee < recue and len((ligne.get("motif_ecart") or "").strip()) < 5:
        raise DonneesInvalides(f"{code} : un écart doit être motivé (5 caractères minimum).")


@transactionnel
def controler(
    db: Session, acteur: Utilisateur, reception_id: uuid.UUID, donnees: dict[str, Any]
) -> ReceptionAchat:
    """Decide de la conformite. Seules les quantites acceptees entrent en stock, en une seule transaction."""
    reception = charger_reception(db, acteur, reception_id, verrou=True)
    if reception.statut != "en_controle":
        raise Conflit(f"Cette réception est déjà contrôlée ({reception.statut}).")
    commande = charger(db, acteur, reception.commande_id, verrou=True)
    decision, commentaire = donnees["decision"], (donnees.get("commentaire") or "").strip()

    recues = {
        ligne.id: ligne
        for ligne in db.scalars(select(LigneReception).where(LigneReception.reception_id == reception.id))
    }
    saisies = {ligne["ligne_reception_id"]: ligne for ligne in donnees["lignes"]}
    if len(saisies) != len(donnees["lignes"]) or set(saisies) != set(recues):
        raise DonneesInvalides(
            "Le contrôle doit porter exactement une fois sur chaque ligne de la réception."
        )
    sources = {ligne.id: ligne for ligne in lignes_de(db, commande.id)}
    articles = {
        a.id: a
        for a in db.scalars(select(Article).where(Article.id.in_([s.article_id for s in sources.values()])))
    }
    importation = (
        db.get(ImportColisage, reception.import_colisage_id) if reception.import_colisage_id else None
    )
    numeros_importes = (
        {ligne.numero_fournisseur for ligne in stock.lignes_import(db, importation)} if importation else set()
    )

    ecart_constate = not donnees["controle_documentaire_ok"]
    exclues: frozenset[str] = frozenset()
    for ligne_id, ligne in recues.items():
        saisie = saisies[ligne_id]
        article = articles[sources[ligne.ligne_commande_id].article_id]
        acceptee = Decimal(0) if decision == "refusee" else saisie["quantite_acceptee"]
        refusees = list(dict.fromkeys(saisie.get("bobines_refusees") or [])) if decision != "refusee" else []
        if article.unite_gestion == "rouleau":
            inconnues = [n for n in refusees if n not in numeros_importes]
            if inconnues:
                raise DonneesInvalides(
                    f"Bobine(s) absente(s) de la packing list : {', '.join(inconnues[:5])}."
                )
            acceptee = Decimal(0) if decision == "refusee" else ligne.quantite_recue - len(refusees)
            exclues = frozenset(refusees)
        elif refusees:
            raise DonneesInvalides(f"{article.code} : les bobines refusées ne s'appliquent qu'aux bobines.")
        if acceptee > ligne.quantite_recue:
            raise DonneesInvalides(
                f"{article.code} : quantité acceptée ({acceptee}) supérieure à la quantité "
                f"reçue ({ligne.quantite_recue})."
            )
        # Seule l'acceptation avec reserves motive chaque ecart ; un refus se motive une fois, par le
        # commentaire, et une acceptation "pure" est refusee plus bas si un ecart existe.
        if decision == "acceptee_avec_reserves":
            _exiger_ecart_motive(saisie, ligne.quantite_recue, acceptee, article.code)
        ecart_constate = ecart_constate or acceptee < ligne.quantite_recue
        ligne.quantite_acceptee, ligne.motif_ecart = acceptee, (saisie.get("motif_ecart") or None)
        ligne.bobines_refusees = refusees

    if decision == "acceptee" and ecart_constate:
        raise DonneesInvalides(
            "Écart constaté (document manquant, quantité ou bobine refusée) : choisissez "
            "« acceptée avec réserves » ou « refusée »."
        )
    if decision == "acceptee_avec_reserves" and not ecart_constate:
        raise DonneesInvalides("Aucun écart constaté : la réception est simplement « acceptée ».")
    if decision != "acceptee" and len(commentaire) < 5:
        raise DonneesInvalides(
            "Une acceptation avec réserves ou un refus exige un commentaire (5 caractères minimum)."
        )

    # Les lignes doivent etre ecrites avant la reception : un declencheur en base refuse de modifier
    # les lignes d'une reception deja decidee.
    db.flush()
    if decision == "refusee":
        if importation:
            stock.abandonner_import(importation)
    else:
        _entrer_en_stock(db, acteur, reception, commande, recues, sources, articles, importation, exclues)

    reception.statut = decision
    reception.controle_documentaire_ok = donnees["controle_documentaire_ok"]
    reception.controle_par, reception.controle_le = acteur.id, maintenant()
    reception.commentaire_controle = commentaire or None
    _recalculer_statut_commande(db, acteur, commande)
    _commit(db, "Contrôle concurrent sur cette réception : réessayez.")
    return reception


def _entrer_en_stock(
    db: Session,
    acteur: Utilisateur,
    reception: ReceptionAchat,
    commande: CommandeAchat,
    recues: dict[uuid.UUID, LigneReception],
    sources: dict[uuid.UUID, LigneCommandeAchat],
    articles: dict[uuid.UUID, Article],
    importation: ImportColisage | None,
    exclues: frozenset[str],
) -> None:
    motif = f"Réception {reception.numero} — commande {commande.numero}"
    for ligne in recues.values():
        article = articles[sources[ligne.ligne_commande_id].article_id]
        if ligne.quantite_acceptee <= 0:
            continue
        if article.unite_gestion == "rouleau":
            lot = stock.executer_import(db, acteur, importation, exclure=exclues)
            reception.lot_id = lot.id
        else:
            stock.enregistrer_mouvement(db, acteur, article, "reception", ligne.quantite_acceptee, motif)
    if importation is not None and importation.statut == "brouillon":
        stock.abandonner_import(importation)  # toutes les bobines ont ete refusees


def _recalculer_statut_commande(db: Session, acteur: Utilisateur, commande: CommandeAchat) -> None:
    db.flush()
    acceptees = quantites_acceptees(db, commande.id)
    lignes = lignes_de(db, commande.id)
    if all(acceptees.get(ligne.id, Decimal(0)) >= ligne.quantite_commandee for ligne in lignes):
        vers = "recue"
    elif any(acceptees.get(ligne.id, Decimal(0)) > 0 for ligne in lignes):
        vers = "partiellement_recue"
    else:
        return
    if vers != commande.statut:
        _passer(db, commande, acteur, ETATS_ATTENTE_MARCHANDISE, vers, "Marchandise acceptée au contrôle")


# --- Catalogue fournisseur --------------------------------------------------------------------------


def _vue_catalogue(entree: ArticleCatalogue, article: Article) -> dict[str, Any]:
    return {**{c.name: getattr(entree, c.name) for c in ArticleCatalogue.__table__.columns},
            "article_code": article.code, "article_nom": article.nom, "unite": article.unite_gestion}


def lister_catalogue(db: Session, acteur: Utilisateur, *, fournisseur_id: uuid.UUID | None,
                     actif: bool | None) -> list[dict[str, Any]]:
    requete = (select(ArticleCatalogue, Article)
               .join(Article, Article.id == ArticleCatalogue.article_id)
               .where(ArticleCatalogue.entreprise_id == acteur.entreprise_id)
               .order_by(ArticleCatalogue.libelle))
    if fournisseur_id is not None:
        requete = requete.where(ArticleCatalogue.fournisseur_id == fournisseur_id)
    if actif is not None:
        requete = requete.where(ArticleCatalogue.actif == actif)
    return [_vue_catalogue(e, a) for e, a in db.execute(requete)]


def _entree_catalogue(db: Session, acteur: Utilisateur, entree_id: uuid.UUID) -> ArticleCatalogue:
    entree = db.scalar(select(ArticleCatalogue).where(
        ArticleCatalogue.entreprise_id == acteur.entreprise_id, ArticleCatalogue.id == entree_id))
    if entree is None:
        raise Introuvable()
    return entree


def _enregistrer_catalogue(db: Session, entree: ArticleCatalogue) -> ArticleCatalogue:
    db.add(entree)
    try:
        db.commit()
    except IntegrityError as erreur:
        db.rollback()
        raise Conflit("Ce code existe déjà pour ce fournisseur.") from erreur
    return entree


def creer_catalogue(db: Session, acteur: Utilisateur, donnees: dict[str, Any]) -> dict[str, Any]:
    _fournisseur_actif(db, acteur, donnees["fournisseur_id"])
    article = referentiel._article_actif(db, acteur, donnees["article_id"], None, "Catalogue")
    if article.niveau_stock == "produit_fini":
        raise DonneesInvalides("Catalogue : un produit fini ne s'achète pas, il se fabrique.")
    entree = _enregistrer_catalogue(db, ArticleCatalogue(entreprise_id=acteur.entreprise_id, **donnees))
    return _vue_catalogue(entree, article)


def modifier_catalogue(db: Session, acteur: Utilisateur, entree_id: uuid.UUID,
                       changements: dict[str, Any]) -> dict[str, Any]:
    entree = _entree_catalogue(db, acteur, entree_id)
    for champ, valeur in changements.items():
        setattr(entree, champ, valeur)
    _enregistrer_catalogue(db, entree)
    return _vue_catalogue(entree, db.get(Article, entree.article_id))
