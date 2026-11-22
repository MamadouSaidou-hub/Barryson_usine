"""Regles du module stock (M04/M05).

Les types de mouvement produits par d'autres modules (consommation, sortie,
entree de fabrication, retour) n'ont pas de porte d'entree HTTP : ils
s'enregistrent par `enregistrer_mouvement`, appelee par la production et les
ventes dans leur propre transaction.
"""

import uuid
from collections import Counter
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import journaliser, maintenant
from app.core.config import get_settings
from app.core.erreurs import Conflit, DonneesInvalides, Introuvable, OperationInterdite
from app.modules.identite import delegations
from app.modules.identite.models import Utilisateur
from app.modules.identite.permissions import ConflitDeSeparation, exiger_valideur_distinct
from app.modules.referentiel import service as referentiel
from app.modules.referentiel.models import Article, Fournisseur
from app.modules.stock.models import (
    TYPES_A_VALIDER,
    TYPES_ENTREE,
    TYPES_SORTIE,
    Bobine,
    ImportColisage,
    LigneImportColisage,
    Lot,
    MouvementStock,
    Reservation,
    ValidationMouvement,
)

PERMISSION_VALIDATION = {
    "entree_directe": "stock.valider_entree_directe",
    "ajustement": "stock.valider_ajustement",
    "inventaire": "stock.valider_ajustement",
    "sortie_exceptionnelle": "stock.valider_sortie_exceptionnelle",
    "rebut_destruction": "stock.valider_sortie_exceptionnelle",
}
# Une bobine pesant plus de 10 % d'ecart a la mediane du lot merite un second regard.
ECART_POIDS_ATYPIQUE = Decimal("0.10")
MIN_LIGNES_POUR_MEDIANE = 10


# --- Articles ------------------------------------------------------------------------


def _article_actif(db: Session, acteur: Utilisateur, article_id: uuid.UUID, *, niveau: str | None = None,
                   verrou: bool = False) -> Article:
    requete = select(Article).where(Article.entreprise_id == acteur.entreprise_id, Article.id == article_id)
    article = db.scalar(requete.with_for_update() if verrou else requete)
    if article is None:
        raise DonneesInvalides("Article introuvable.")
    if not article.actif:
        raise DonneesInvalides(f"L'article {article.code} est désactivé.")
    if niveau is not None and article.niveau_stock != niveau:
        raise DonneesInvalides(f"L'article {article.code} n'est pas du niveau « {niveau} ».")
    return article


def _article_bobine(db: Session, acteur: Utilisateur, article_id: uuid.UUID) -> Article:
    article = _article_actif(db, acteur, article_id, niveau="semi_fini")
    if article.unite_gestion != "rouleau":
        raise DonneesInvalides(f"L'article {article.code} doit se gérer au rouleau pour recevoir "
                               "des bobines.")
    return article


def _fournisseur_actif(db: Session, acteur: Utilisateur, fournisseur_id: uuid.UUID) -> Fournisseur:
    fournisseur = referentiel.charger_ou_invalide(db, Fournisseur, acteur, fournisseur_id, "Fournisseur")
    if not fournisseur.actif:
        raise DonneesInvalides(f"Le fournisseur {fournisseur.code} est désactivé.")
    return fournisseur


# --- Mouvements ------------------------------------------------------------------------


def enregistrer_mouvement(db: Session, acteur: Utilisateur | None, article: Article, type_: str,
                          quantite: Decimal, motif: str, *, lot_id: uuid.UUID | None = None,
                          bobine_id: uuid.UUID | None = None, ordre_fabrication_id: uuid.UUID | None = None,
                          cout_unitaire_gnf: int | None = None,
                          piece_justificative_url: str | None = None) -> MouvementStock:
    """Ajoute un mouvement (sans commit). `quantite` est toujours positive : le sens vient du type,
    sauf ajustement et inventaire dont la quantite est deja signee par l'appelant."""
    if type_ in TYPES_ENTREE:
        signee = abs(quantite)
    elif type_ in TYPES_SORTIE:
        signee = -abs(quantite)
    else:
        signee = quantite
    mouvement = MouvementStock(
        entreprise_id=article.entreprise_id, article_id=article.id, type=type_, quantite=signee,
        unite=article.unite_gestion, lot_id=lot_id, bobine_id=bobine_id,
        ordre_fabrication_id=ordre_fabrication_id, cout_unitaire_gnf=cout_unitaire_gnf,
        requiert_validation=type_ in TYPES_A_VALIDER, motif=motif,
        piece_justificative_url=piece_justificative_url, cree_par=acteur.id if acteur else None,
    )
    db.add(mouvement)
    return mouvement


def creer_mouvement_manuel(db: Session, acteur: Utilisateur, donnees: dict[str, Any]) -> MouvementStock:
    type_ = donnees["type"]
    if not get_settings().validations_actives:
        # Sans circuit : une entree ou une sortie se saisit et compte tout de suite, sans seconde personne.
        entree = type_ == "entree_directe" or (type_ == "ajustement" and donnees["sens"] == "plus")
        article = _article_actif(db, acteur, donnees["article_id"], niveau=None)
        type_manuel = "entree_manuelle" if entree else "sortie_manuelle"
        mouvement = enregistrer_mouvement(
            db, acteur, article, type_manuel, donnees["quantite"], donnees["motif"],
            piece_justificative_url=donnees.get("piece_justificative_url"))
        db.commit()
        return mouvement
    # Entree directe : uniquement des produits finis (cartons deja presents ou ecart d'inventaire).
    article = _article_actif(db, acteur, donnees["article_id"],
                             niveau="produit_fini" if type_ == "entree_directe" else None)
    quantite = donnees["quantite"]
    if type_ == "ajustement" and donnees["sens"] == "moins":
        quantite = -quantite
    mouvement = enregistrer_mouvement(db, acteur, article, type_, quantite, donnees["motif"],
                                      piece_justificative_url=donnees.get("piece_justificative_url"))
    db.commit()
    return mouvement


def valider_mouvement(db: Session, acteur: Utilisateur, mouvement_id: uuid.UUID, decision: str,
                      motif: str | None) -> tuple[MouvementStock, ValidationMouvement]:
    # Pas de verrou de ligne : le registre est en ajout seul, l'API n'a pas le droit UPDATE dessus
    # (PostgreSQL l'exige pour FOR UPDATE). L'unicite de la validation garantit l'exclusion mutuelle.
    mouvement = db.scalar(select(MouvementStock).where(
        MouvementStock.entreprise_id == acteur.entreprise_id, MouvementStock.id == mouvement_id))
    if mouvement is None:
        raise Introuvable()
    permission = PERMISSION_VALIDATION.get(mouvement.type)
    if permission is None:
        db.rollback()
        raise DonneesInvalides("Ce mouvement ne nécessite aucune validation.")
    autorise, delegation_id = delegations.droit(db, acteur, permission)
    if not autorise:
        journaliser(db, "acces.refuse", apres={"permission": permission, "mouvement": str(mouvement_id)})
        db.commit()
        raise OperationInterdite("Accès refusé.")
    try:
        exiger_valideur_distinct(mouvement.cree_par, acteur.id)
    except ConflitDeSeparation as erreur:
        journaliser(db, "validation.refusee_meme_personne", cible_type="mouvements_stock",
                    cible_id=mouvement.id)
        db.commit()
        raise OperationInterdite(str(erreur)) from erreur
    if db.scalar(select(ValidationMouvement.id).where(ValidationMouvement.mouvement_id == mouvement.id)):
        db.rollback()
        raise Conflit("Ce mouvement a déjà été traité.")
    validation = ValidationMouvement(entreprise_id=acteur.entreprise_id, mouvement_id=mouvement.id,
                                     decision=decision, valide_par=acteur.id, motif=motif,
                                     delegation_id=delegation_id)
    db.add(validation)
    try:
        db.commit()
    except IntegrityError as erreur:
        db.rollback()
        raise Conflit("Ce mouvement a déjà été traité.") from erreur
    return mouvement, validation


def lister_mouvements(db: Session, acteur: Utilisateur, *, article_id: uuid.UUID | None = None,
                      type_: str | None = None, statut: str | None = None, avant: Any = None,
                      limite: int = 50) -> list[tuple[MouvementStock, ValidationMouvement | None]]:
    requete = (select(MouvementStock, ValidationMouvement)
               .outerjoin(ValidationMouvement, ValidationMouvement.mouvement_id == MouvementStock.id)
               .where(MouvementStock.entreprise_id == acteur.entreprise_id))
    if article_id is not None:
        requete = requete.where(MouvementStock.article_id == article_id)
    if type_ is not None:
        requete = requete.where(MouvementStock.type == type_)
    if statut == "valide":
        requete = requete.where(or_(MouvementStock.requiert_validation.is_(False),
                                    ValidationMouvement.decision == "valide"))
    elif statut == "rejete":
        requete = requete.where(ValidationMouvement.decision == "rejete")
    elif statut == "en_attente":
        requete = requete.where(MouvementStock.requiert_validation.is_(True),
                                ValidationMouvement.id.is_(None))
    if avant is not None:
        requete = requete.where(MouvementStock.cree_le < avant)
    return [(m, v) for m, v in db.execute(requete.order_by(MouvementStock.cree_le.desc()).limit(limite))]


def statut_mouvement(mouvement: MouvementStock, validation: ValidationMouvement | None) -> str:
    if not mouvement.requiert_validation:
        return "valide"
    return validation.decision if validation else "en_attente"


# --- Soldes et reservations --------------------------------------------------------------------


def soldes(db: Session, acteur: Utilisateur, *, niveau: str | None = None,
           article_id: uuid.UUID | None = None, sous_seuil: bool = False) -> list[dict[str, Any]]:
    e = acteur.entreprise_id
    physique = dict(db.execute(
        select(MouvementStock.article_id, func.sum(MouvementStock.quantite))
        .outerjoin(ValidationMouvement, ValidationMouvement.mouvement_id == MouvementStock.id)
        .where(MouvementStock.entreprise_id == e,
               or_(MouvementStock.requiert_validation.is_(False), ValidationMouvement.decision == "valide"))
        .group_by(MouvementStock.article_id)).all())
    reserve = dict(db.execute(
        select(Reservation.article_id, func.sum(Reservation.quantite))
        .where(Reservation.entreprise_id == e, Reservation.statut == "ouverte")
        .group_by(Reservation.article_id)).all())
    attente = dict(db.execute(
        select(MouvementStock.article_id, func.count())
        .outerjoin(ValidationMouvement, ValidationMouvement.mouvement_id == MouvementStock.id)
        .where(MouvementStock.entreprise_id == e, MouvementStock.requiert_validation.is_(True),
               ValidationMouvement.id.is_(None))
        .group_by(MouvementStock.article_id)).all())

    requete = select(Article).where(Article.entreprise_id == e)
    if niveau:
        requete = requete.where(Article.niveau_stock == niveau)
    if article_id:
        requete = requete.where(Article.id == article_id)
    resultat = []
    for article in db.scalars(requete.order_by(Article.code)):
        phys = physique.get(article.id, Decimal(0))
        if not article.actif and phys == 0:
            continue
        res = reserve.get(article.id, Decimal(0))
        ligne = {
            "article_id": article.id, "code": article.code, "nom": article.nom,
            "niveau_stock": article.niveau_stock, "unite": article.unite_gestion, "physique": phys,
            "reserve": res, "disponible": phys - res, "negatif": phys < 0,
            "sous_seuil_min": article.seuil_min is not None and phys - res < article.seuil_min,
            "en_attente_validation": attente.get(article.id, 0),
        }
        if not sous_seuil or ligne["sous_seuil_min"]:
            resultat.append(ligne)
    return resultat


def creer_reservation(db: Session, acteur: Utilisateur, donnees: dict[str, Any]) -> Reservation:
    # Verrou sur l'article : deux reservations simultanees ne peuvent pas promettre le meme stock.
    article = _article_actif(db, acteur, donnees["article_id"], verrou=True)
    ligne = soldes(db, acteur, article_id=article.id)[0]
    if donnees["quantite"] > ligne["disponible"]:
        db.rollback()
        raise Conflit(f"Stock disponible insuffisant : {ligne['disponible']} {article.unite_gestion} "
                      f"disponible(s), {donnees['quantite']} demandé(s).")
    reservation = Reservation(entreprise_id=acteur.entreprise_id, cree_par=acteur.id, **donnees)
    db.add(reservation)
    db.commit()
    return reservation


def reserver_pour_ordre(db: Session, acteur: Utilisateur, article_id: uuid.UUID, quantite: Decimal,
                        ordre_id: uuid.UUID, motif: str) -> bool:
    """Reserve pour un ordre de fabrication si le disponible le permet, sans commit.

    Renvoie False (sans rien reserver) si le stock ne suffit pas : l'appelant en fait un
    avertissement, le stock negatif n'etant jamais bloquant (decision 0003).
    """
    article = _article_actif(db, acteur, article_id, verrou=True)
    if quantite > soldes(db, acteur, article_id=article.id)[0]["disponible"]:
        return False
    db.add(Reservation(entreprise_id=acteur.entreprise_id, article_id=article.id, quantite=quantite,
                       motif=motif, ordre_fabrication_id=ordre_id, cree_par=acteur.id))
    return True


def lever_reservations_ordre(db: Session, acteur: Utilisateur, ordre_id: uuid.UUID) -> int:
    """Leve les reservations ouvertes d'un ordre (matieres sorties ou ordre annule), sans commit."""
    ouvertes = db.scalars(select(Reservation).where(
        Reservation.entreprise_id == acteur.entreprise_id, Reservation.ordre_fabrication_id == ordre_id,
        Reservation.statut == "ouverte")).all()
    for reservation in ouvertes:
        reservation.statut, reservation.levee_le, reservation.levee_par = "levee", maintenant(), acteur.id
    return len(ouvertes)


def lever_reservation(db: Session, acteur: Utilisateur, reservation_id: uuid.UUID) -> Reservation:
    reservation = db.scalar(select(Reservation).where(
        Reservation.entreprise_id == acteur.entreprise_id, Reservation.id == reservation_id
    ).with_for_update())
    if reservation is None:
        raise Introuvable()
    if reservation.statut == "levee":
        db.rollback()
        raise Conflit("Cette réservation est déjà levée.")
    reservation.statut, reservation.levee_le, reservation.levee_par = "levee", maintenant(), acteur.id
    db.commit()
    return reservation


def lister_reservations(db: Session, acteur: Utilisateur, statut: str | None,
                        article_id: uuid.UUID | None) -> list[Reservation]:
    requete = select(Reservation).where(Reservation.entreprise_id == acteur.entreprise_id)
    if statut:
        requete = requete.where(Reservation.statut == statut)
    if article_id:
        requete = requete.where(Reservation.article_id == article_id)
    return list(db.scalars(requete.order_by(Reservation.cree_le.desc()).limit(500)))


# --- Lots et bobines ------------------------------------------------------------------------------


def _inserer_reception(db: Session, acteur: Utilisateur, entete: dict[str, Any], article: Article,
                       bobines: list[dict[str, Any]]) -> Lot:
    """Cree le lot, ses bobines et un mouvement de reception par bobine. Sans commit."""
    lot = Lot(entreprise_id=acteur.entreprise_id, conteneur_reference=entete["conteneur_reference"],
              numero_facture=entete.get("numero_facture"), date_reception=entete["date_reception"],
              fournisseur_id=entete["fournisseur_id"], cree_par=acteur.id)
    db.add(lot)
    db.flush()
    for ligne in bobines:
        bobine = Bobine(entreprise_id=acteur.entreprise_id, lot_id=lot.id, article_id=article.id,
                        numero_fournisseur=ligne["numero_fournisseur"], poids_kg=ligne["poids_kg"],
                        metrage_propre=ligne.get("metrage_propre"),
                        couleur_finition=ligne["couleur_finition"],
                        couleur_impression=ligne.get("couleur_impression"),
                        module_impression=ligne.get("module_impression"))
        db.add(bobine)
        db.flush()
        enregistrer_mouvement(db, acteur, article, "reception", Decimal(1),
                              f"Réception du conteneur {lot.conteneur_reference}", lot_id=lot.id,
                              bobine_id=bobine.id)
    return lot


def _verifier_lot_inedit(db: Session, acteur: Utilisateur, reference: str) -> None:
    if db.scalar(select(Lot.id).where(Lot.entreprise_id == acteur.entreprise_id,
                                      Lot.conteneur_reference == reference)):
        raise Conflit(f"Le conteneur {reference} a déjà été reçu.")


def creer_reception(db: Session, acteur: Utilisateur, donnees: dict[str, Any]) -> Lot:
    article = _article_bobine(db, acteur, donnees["article_id"])
    _fournisseur_actif(db, acteur, donnees["fournisseur_id"])
    _verifier_lot_inedit(db, acteur, donnees["conteneur_reference"])
    numeros = [b["numero_fournisseur"] for b in donnees["bobines"]]
    doublons = sorted(n for n, c in Counter(numeros).items() if c > 1)
    if doublons:
        raise DonneesInvalides(f"Numéros de bobine en double dans ce conteneur : {', '.join(doublons[:10])}.")
    for ligne in donnees["bobines"]:
        if (ligne.get("couleur_impression") or ligne.get("module_impression")) and \
                ligne["couleur_finition"] != "kaki_imprime":
            raise DonneesInvalides(f"Bobine {ligne['numero_fournisseur']} : couleur et module d'impression "
                                   "réservés à la finition kaki imprimé.")
    try:
        lot = _inserer_reception(db, acteur, donnees, article, donnees["bobines"])
        db.commit()
    except IntegrityError as erreur:
        db.rollback()
        raise Conflit("Réception concurrente sur ce conteneur : réessayez.") from erreur
    return lot


def lister_lots(db: Session, acteur: Utilisateur) -> list[tuple[Lot, int]]:
    requete = (select(Lot, func.count(Bobine.id)).outerjoin(Bobine, Bobine.lot_id == Lot.id)
               .where(Lot.entreprise_id == acteur.entreprise_id).group_by(Lot.id)
               .order_by(Lot.date_reception.desc(), Lot.cree_le.desc()).limit(500))
    return [(lot, nb) for lot, nb in db.execute(requete)]


def charger_lot(db: Session, acteur: Utilisateur, lot_id: uuid.UUID) -> tuple[Lot, int]:
    ligne = db.execute(select(Lot, func.count(Bobine.id)).outerjoin(Bobine, Bobine.lot_id == Lot.id)
                       .where(Lot.entreprise_id == acteur.entreprise_id, Lot.id == lot_id)
                       .group_by(Lot.id)).first()
    if ligne is None:
        raise Introuvable()
    return ligne[0], ligne[1]


def lister_bobines(db: Session, acteur: Utilisateur, *, lot_id: uuid.UUID | None, statut: str | None,
                   couleur: str | None, limite: int = 500) -> list[Bobine]:
    requete = select(Bobine).where(Bobine.entreprise_id == acteur.entreprise_id)
    filtres = ((Bobine.lot_id, lot_id), (Bobine.statut, statut), (Bobine.couleur_finition, couleur))
    for colonne, valeur in filtres:
        if valeur is not None:
            requete = requete.where(colonne == valeur)
    return list(db.scalars(requete.order_by(Bobine.lot_id, Bobine.numero_fournisseur).limit(limite)))


# --- Import de packing list (apercu, anomalies, validation) -------------------------------------


def _anomalie(niveau: str, code: str, message: str) -> dict[str, str]:
    return {"niveau": niveau, "code": code, "message": message}


def analyser_lignes(lignes: list[dict[str, Any]]) -> list[list[dict[str, str]]]:
    """Controles de coherence d'un packing list. Fonction pure : testable sans base de donnees.

    Bloquantes : empechent la validation. Avertissements : a lire, n'empechent rien (un metrage
    manquant est courant : la bobine ne servira a aucune prevision tant qu'il n'est pas complete).
    """
    comptes = Counter(ligne.get("numero_fournisseur") for ligne in lignes if ligne.get("numero_fournisseur"))
    poids = sorted(ligne["poids_kg"] for ligne in lignes if ligne.get("poids_kg"))
    mediane = poids[len(poids) // 2] if len(poids) >= MIN_LIGNES_POUR_MEDIANE else None
    resultat = []
    for ligne in lignes:
        anomalies = []
        numero = ligne.get("numero_fournisseur")
        if not numero:
            anomalies.append(_anomalie("bloquante", "numero_manquant", "Numéro de bobine absent."))
        elif comptes[numero] > 1:
            anomalies.append(_anomalie("bloquante", "doublon_numero",
                                       f"Le numéro {numero} apparaît {comptes[numero]} fois "
                                       "dans ce conteneur."))
        if not ligne.get("poids_kg"):
            anomalies.append(_anomalie("bloquante", "poids_manquant", "Poids absent."))
        elif mediane and abs(ligne["poids_kg"] - mediane) > mediane * ECART_POIDS_ATYPIQUE:
            anomalies.append(_anomalie("avertissement", "poids_atypique",
                                       f"Poids {ligne['poids_kg']} kg très éloigné de la médiane "
                                       f"({mediane} kg)."))
        if not ligne.get("couleur_finition"):
            brute = ligne.get("couleur_brute") or "?"
            anomalies.append(_anomalie("bloquante", "finition_non_reconnue",
                                       f"Finition « {brute} » non associée à une finition connue."))
        elif (ligne.get("couleur_impression") or ligne.get("module_impression")) and \
                ligne["couleur_finition"] != "kaki_imprime":
            anomalies.append(_anomalie("bloquante", "impression_incoherente",
                                       "Couleur ou module d'impression sur une bobine non imprimée."))
        if not ligne.get("metrage_propre"):
            anomalies.append(_anomalie("avertissement", "metrage_manquant",
                                       "Métrage propre absent : aucune prévision de fabrication possible "
                                       "sur cette bobine tant qu'il n'est pas renseigné."))
        resultat.append(anomalies)
    return resultat


def _compter(anomalies: list[list[dict[str, str]]], niveau: str) -> int:
    return sum(1 for ligne in anomalies for a in ligne if a["niveau"] == niveau)


def creer_import(db: Session, acteur: Utilisateur, donnees: dict[str, Any]) -> ImportColisage:
    _article_bobine(db, acteur, donnees["article_id"])
    _fournisseur_actif(db, acteur, donnees["fournisseur_id"])
    _verifier_lot_inedit(db, acteur, donnees["conteneur_reference"])
    if db.scalar(select(ImportColisage.id).where(
            ImportColisage.entreprise_id == acteur.entreprise_id, ImportColisage.statut == "brouillon",
            ImportColisage.conteneur_reference == donnees["conteneur_reference"])):
        raise Conflit("Un import est déjà en cours pour ce conteneur : validez-le ou annulez-le d'abord.")
    lignes = donnees.pop("lignes")
    anomalies = analyser_lignes(lignes)
    importation = ImportColisage(
        entreprise_id=acteur.entreprise_id, cree_par=acteur.id, nb_lignes=len(lignes),
        nb_bloquantes=_compter(anomalies, "bloquante"),
        nb_avertissements=_compter(anomalies, "avertissement"),
        **donnees)
    db.add(importation)
    db.flush()
    db.add_all(LigneImportColisage(import_id=importation.id, rang=rang, anomalies=anom, **ligne)
               for rang, (ligne, anom) in enumerate(zip(lignes, anomalies, strict=True), start=1))
    db.commit()
    return importation


def charger_import(db: Session, acteur: Utilisateur, import_id: uuid.UUID, *,
                   verrou: bool = False) -> ImportColisage:
    requete = select(ImportColisage).where(ImportColisage.entreprise_id == acteur.entreprise_id,
                                           ImportColisage.id == import_id)
    importation = db.scalar(requete.with_for_update() if verrou else requete)
    if importation is None:
        raise Introuvable()
    return importation


def lignes_import(db: Session, importation: ImportColisage) -> list[LigneImportColisage]:
    return list(db.scalars(select(LigneImportColisage).where(LigneImportColisage.import_id == importation.id)
                           .order_by(LigneImportColisage.rang)))


def lister_imports(db: Session, acteur: Utilisateur, statut: str | None) -> list[ImportColisage]:
    requete = select(ImportColisage).where(ImportColisage.entreprise_id == acteur.entreprise_id)
    if statut:
        requete = requete.where(ImportColisage.statut == statut)
    return list(db.scalars(requete.order_by(ImportColisage.cree_le.desc()).limit(200)))


def _refuser_si_rattache(importation: ImportColisage) -> None:
    if importation.rattache_reception:
        raise Conflit("Cet import est rattaché à une réception d'achat : il se valide par le contrôle de "
                      "conformité de cette réception.")


def annuler_import(db: Session, acteur: Utilisateur, import_id: uuid.UUID) -> ImportColisage:
    importation = charger_import(db, acteur, import_id, verrou=True)
    try:
        _refuser_si_rattache(importation)
        if importation.statut != "brouillon":
            raise Conflit(f"Import déjà {importation.statut}.")
        importation.statut = "annule"
        db.commit()
    except Exception:
        db.rollback()
        raise
    return importation


def abandonner_import(importation: ImportColisage) -> None:
    """Reception refusee au controle : rien n'entre en stock, le conteneur pourra etre re-importe."""
    importation.statut = "annule"


def executer_import(db: Session, acteur: Utilisateur, importation: ImportColisage, *,
                    exclure: frozenset[str] = frozenset()) -> Lot:
    """Cree lot, bobines et receptions depuis un apercu, sans verrou ni commit (a la charge de l'appelant).

    `exclure` : numeros de bobines refusees au controle de conformite ; elles n'entrent pas en stock.
    """
    if importation.statut != "brouillon":
        raise Conflit(f"Import déjà {importation.statut}.")
    if importation.nb_bloquantes:
        raise DonneesInvalides(f"{importation.nb_bloquantes} anomalie(s) bloquante(s) : corrigez la "
                               "packing list et refaites l'import.")
    article = _article_bobine(db, acteur, importation.article_id)
    _fournisseur_actif(db, acteur, importation.fournisseur_id)
    _verifier_lot_inedit(db, acteur, importation.conteneur_reference)
    colonnes = ("numero_fournisseur", "poids_kg", "metrage_propre", "couleur_finition", "couleur_impression",
                "module_impression")
    bobines = [{c: getattr(ligne, c) for c in colonnes} for ligne in lignes_import(db, importation)
               if ligne.numero_fournisseur not in exclure]
    if not bobines:
        raise DonneesInvalides("Toutes les bobines sont refusées : refusez la réception plutôt que de "
                               "l'accepter.")
    entete = {"conteneur_reference": importation.conteneur_reference,
              "numero_facture": importation.numero_facture, "date_reception": importation.date_reception,
              "fournisseur_id": importation.fournisseur_id}
    lot = _inserer_reception(db, acteur, entete, article, bobines)
    importation.statut, importation.valide_par = "valide", acteur.id
    importation.valide_le, importation.lot_id = maintenant(), lot.id
    return lot


def valider_import(db: Session, acteur: Utilisateur, import_id: uuid.UUID) -> ImportColisage:
    """Transforme l'apercu en lot, bobines et mouvements de reception, en une seule transaction."""
    importation = charger_import(db, acteur, import_id, verrou=True)
    try:
        _refuser_si_rattache(importation)
        executer_import(db, acteur, importation)
        db.commit()
    except IntegrityError as erreur:
        db.rollback()
        raise Conflit("Réception concurrente sur ce conteneur : réessayez.") from erreur
    except Exception:
        db.rollback()
        raise
    return importation
