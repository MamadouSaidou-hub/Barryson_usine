"""Regles du module production (M06) : cycle de vie de l'ordre de fabrication.

Chaque transition est une fonction dediee qui verifie l'etat courant, jamais un
changement de statut generique. Le droit de l'appelant est verifie par la couche
routes ; l'etat, les donnees et le stock le sont ici, dans une seule transaction.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import maintenant
from app.core.config import get_settings
from app.core.erreurs import Conflit, DonneesInvalides, Introuvable, OperationInterdite
from app.core.numerotation import prochain_numero
from app.core.transactions import transactionnel
from app.modules.identite.models import Utilisateur
from app.modules.production import calculs
from app.modules.production.calculs import ErreurCalcul, SaisieResultat
from app.modules.production.models import (
    STATUTS_TERMINAUX,
    OrdreFabrication,
    TransitionOF,
    UtilisationBobine,
)
from app.modules.referentiel import service as referentiel
from app.modules.referentiel.models import Article, ModeleRuban, VersionModeleRuban
from app.modules.stock import service as stock
from app.modules.stock.models import Bobine

CHAMPS_SAISIE = ("tours_totaux", "tours_defectueux", "pieces_defectueuses_supplementaires",
                 "quantite_doctor_rewinder", "pertes_definitives")


def _alerte(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


# --- Acces ---------------------------------------------------------------------------------------


def charger(db: Session, acteur: Utilisateur, ordre_id: uuid.UUID, *,
            verrou: bool = False) -> OrdreFabrication:
    requete = select(OrdreFabrication).where(OrdreFabrication.entreprise_id == acteur.entreprise_id,
                                             OrdreFabrication.id == ordre_id)
    ordre = db.scalar(requete.with_for_update() if verrou else requete)
    if ordre is None:
        raise Introuvable()
    return ordre


def version_de(db: Session, ordre: OrdreFabrication) -> VersionModeleRuban:
    return db.scalars(select(VersionModeleRuban).where(VersionModeleRuban.id == ordre.version_id)).one()


def lister(db: Session, acteur: Utilisateur, *, statut: str | None, bobine_id: uuid.UUID | None,
           modele_id: uuid.UUID | None, limite: int = 200) -> list[OrdreFabrication]:
    requete = select(OrdreFabrication).where(OrdreFabrication.entreprise_id == acteur.entreprise_id)
    for colonne, valeur in ((OrdreFabrication.statut, statut), (OrdreFabrication.bobine_id, bobine_id),
                            (OrdreFabrication.modele_id, modele_id)):
        if valeur is not None:
            requete = requete.where(colonne == valeur)
    return list(db.scalars(requete.order_by(OrdreFabrication.cree_le.desc()).limit(limite)))


def transitions(db: Session, ordre: OrdreFabrication) -> list[TransitionOF]:
    return list(db.scalars(select(TransitionOF).where(TransitionOF.ordre_id == ordre.id)
                           .order_by(TransitionOF.cree_le, TransitionOF.id)))


def saisie_de(ordre: OrdreFabrication) -> SaisieResultat | None:
    if ordre.tours_totaux is None:
        return None
    return SaisieResultat(**{champ: getattr(ordre, champ) for champ in CHAMPS_SAISIE})


def resultat_calcule(db: Session, ordre: OrdreFabrication) -> calculs.Resultat | None:
    saisie = saisie_de(ordre)
    if saisie is None:
        return None
    version = version_de(db, ordre)
    try:
        return calculs.calculer_resultat(saisie, version.pieces_par_tour, version.pieces_par_carton,
                                         ordre.pieces_theoriques or 0)
    except ErreurCalcul:
        return None


# --- Machine a etats ------------------------------------------------------------------------------


def _passer(db: Session, ordre: OrdreFabrication, acteur: Utilisateur, attendus: tuple[str, ...], vers: str,
            motif: str | None = None) -> None:
    if ordre.statut not in attendus:
        db.rollback()
        raise Conflit(f"Transition impossible : l'ordre {ordre.numero} est « {ordre.statut} », "
                      f"il doit être « {' ou '.join(attendus)} ».")
    db.add(TransitionOF(entreprise_id=ordre.entreprise_id, ordre_id=ordre.id, de_statut=ordre.statut,
                        vers_statut=vers, acteur_id=acteur.id, motif=motif))
    ordre.statut = vers


def _valider_ou_annuler(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as erreur:
        db.rollback()
        raise Conflit("Modification concurrente de cet ordre : réessayez.") from erreur


# --- Creation et prevision -----------------------------------------------------------------------------


def _contexte_fabrication(db: Session, acteur: Utilisateur, modele_id: uuid.UUID, bobine_id: uuid.UUID,
                          metrage_engage: Decimal) -> tuple[ModeleRuban, VersionModeleRuban, Bobine]:
    modele = referentiel.charger_ou_invalide(db, ModeleRuban, acteur, modele_id, "Modèle")
    if not modele.actif:
        raise DonneesInvalides(f"Le modèle {modele.code} est désactivé.")
    version = referentiel.version_courante(db, modele.id)
    requis = (("moule", version.moule_id), ("produit fini", version.article_produit_fini_id),
              ("tube papier", version.article_tube_id))
    manquants = [nom for nom, valeur in requis if valeur is None]
    if manquants:
        raise DonneesInvalides(f"Fiche du modèle {modele.code} incomplète : {', '.join(manquants)} à "
                               "renseigner avant de lancer un ordre (nouvelle version de la fiche).")
    bobine = db.scalar(select(Bobine).where(Bobine.entreprise_id == acteur.entreprise_id,
                                            Bobine.id == bobine_id))
    if bobine is None:
        raise DonneesInvalides("Bobine introuvable.")
    if bobine.statut == "epuisee":
        raise DonneesInvalides(f"La bobine {bobine.numero_fournisseur} est épuisée.")
    if bobine.metrage_propre is None:
        raise DonneesInvalides(f"La bobine {bobine.numero_fournisseur} n'a pas de métrage propre : aucune "
                               "prévision fiable n'est possible tant qu'il n'est pas renseigné.")
    if metrage_engage > bobine.metrage_propre:
        raise DonneesInvalides(f"Le métrage engagé ({metrage_engage} m) dépasse le métrage propre de la "
                               f"bobine ({bobine.metrage_propre} m).")
    if metrage_engage < version.longueur_rouleau_m:
        raise DonneesInvalides(f"Le métrage engagé ({metrage_engage} m) ne permet pas un seul tour complet "
                               f"({version.longueur_rouleau_m} m).")
    return modele, version, bobine


def _ordre_actif_de(db: Session, bobine_id: uuid.UUID) -> OrdreFabrication | None:
    return db.scalar(select(OrdreFabrication).where(OrdreFabrication.bobine_id == bobine_id,
                                                    OrdreFabrication.statut.not_in(STATUTS_TERMINAUX)))


def _alertes_metrage(db: Session, bobine: Bobine, metrage_engage: Decimal,
                     ordre_id: uuid.UUID | None) -> list[dict[str, str]]:
    deja = db.scalar(select(func.coalesce(func.sum(UtilisationBobine.metrage_engage), 0))
                     .join(OrdreFabrication, OrdreFabrication.id == UtilisationBobine.ordre_id)
                     .where(UtilisationBobine.bobine_id == bobine.id, OrdreFabrication.statut != "annule",
                            OrdreFabrication.id != ordre_id)) or Decimal(0)
    if deja + metrage_engage > bobine.metrage_propre:
        return [_alerte("metrage_cumule",
                        f"Les séances précédentes ({deja} m) et celle-ci ({metrage_engage} m) dépassent le "
                        f"métrage propre initial ({bobine.metrage_propre} m). Le restant réel de la bobine "
                        "n'est pas mesuré : vérifiez à l'atelier.")]
    return []


def previsualiser(db: Session, acteur: Utilisateur, modele_id: uuid.UUID, bobine_id: uuid.UUID,
                  metrage_engage: Decimal) -> dict[str, Any]:
    _, version, bobine = _contexte_fabrication(db, acteur, modele_id, bobine_id, metrage_engage)
    prevision = calculs.prevoir(metrage_engage, version.longueur_rouleau_m, version.pieces_par_tour,
                                version.pieces_par_carton)
    return {"metrage_engage": metrage_engage, "longueur_rouleau_m": version.longueur_rouleau_m,
            "pieces_par_tour": version.pieces_par_tour, "pieces_par_carton": version.pieces_par_carton,
            "tours_complets": prevision.tours_complets, "pieces_theoriques": prevision.pieces_theoriques,
            "cartons_complets": prevision.cartons_complets, "pieces_restantes": prevision.pieces_restantes,
            "alertes": _alertes_metrage(db, bobine, metrage_engage, None)}


@transactionnel
def creer(db: Session, acteur: Utilisateur, donnees: dict[str, Any]) -> OrdreFabrication:
    modele, version, bobine = _contexte_fabrication(db, acteur, donnees["modele_id"], donnees["bobine_id"],
                                                    donnees["metrage_engage"])
    actif = _ordre_actif_de(db, bobine.id)
    if actif is not None:
        raise Conflit(f"La bobine {bobine.numero_fournisseur} est déjà engagée dans l'ordre {actif.numero}.")
    ordre = OrdreFabrication(
        entreprise_id=acteur.entreprise_id, numero=prochain_numero(db, acteur.entreprise_id, "OF"),
        modele_id=modele.id, version_id=version.id, bobine_id=bobine.id,
        metrage_engage=donnees["metrage_engage"], commentaire=donnees.get("commentaire"), cree_par=acteur.id)
    db.add(ordre)
    try:
        # L'insertion peut echouer ici : l'index partiel refuse une seconde fabrication active sur la
        # bobine meme si deux requetes ont passe la verification ci-dessus en meme temps.
        db.flush()
        db.add(TransitionOF(entreprise_id=ordre.entreprise_id, ordre_id=ordre.id, de_statut=None,
                            vers_statut="brouillon", acteur_id=acteur.id))
        db.commit()
    except IntegrityError as erreur:
        db.rollback()
        raise Conflit("Cette bobine vient d'être engagée dans un autre ordre.") from erreur
    return ordre


@transactionnel
def modifier_brouillon(db: Session, acteur: Utilisateur, ordre_id: uuid.UUID,
                       changements: dict[str, Any]) -> OrdreFabrication:
    ordre = charger(db, acteur, ordre_id, verrou=True)
    if ordre.statut != "brouillon":
        db.rollback()
        raise Conflit("Seul un ordre en brouillon peut être modifié.")
    if "metrage_engage" in changements:
        _contexte_fabrication(db, acteur, ordre.modele_id, ordre.bobine_id, changements["metrage_engage"])
    for champ, valeur in changements.items():
        setattr(ordre, champ, valeur)
    db.commit()
    return ordre


# --- Transitions ----------------------------------------------------------------------------------------


@transactionnel
def soumettre(db: Session, acteur: Utilisateur, ordre_id: uuid.UUID) -> OrdreFabrication:
    ordre = charger(db, acteur, ordre_id, verrou=True)
    _passer(db, ordre, acteur, ("brouillon",), "soumis")
    _, version, bobine = _contexte_fabrication(db, acteur, ordre.modele_id, ordre.bobine_id,
                                               ordre.metrage_engage)
    prevision = calculs.prevoir(ordre.metrage_engage, version.longueur_rouleau_m, version.pieces_par_tour,
                                version.pieces_par_carton)
    ordre.tours_prevus, ordre.pieces_theoriques = prevision.tours_complets, prevision.pieces_theoriques
    ordre.cartons_prevus = prevision.cartons_complets
    ordre.pieces_restantes_prevues = prevision.pieces_restantes
    alertes = _alertes_metrage(db, bobine, ordre.metrage_engage, ordre.id)
    # Demande de matieres : un tube par piece. Reserve si le stock le permet, avertit sinon.
    besoin = Decimal(prevision.pieces_theoriques)
    if not stock.reserver_pour_ordre(db, acteur, version.article_tube_id, besoin, ordre.id,
                                     f"Tubes pour l'ordre {ordre.numero}"):
        alertes.append(_alerte("tubes_insuffisants",
                               f"Stock de tubes disponible inférieur aux {besoin} nécessaires : "
                               "la sortie créera un stock négatif à régulariser."))
    ordre.alertes = alertes
    _valider_ou_annuler(db)
    return ordre


@transactionnel
def valider_matieres(db: Session, acteur: Utilisateur, ordre_id: uuid.UUID) -> OrdreFabrication:
    """Sortie des matieres vers la production : tubes pour toutes les pieces prevues."""
    ordre = charger(db, acteur, ordre_id, verrou=True)
    _passer(db, ordre, acteur, ("soumis",), "matieres_validees")
    version = version_de(db, ordre)
    tube = db.scalars(select(Article).where(Article.id == version.article_tube_id)).one()
    stock.lever_reservations_ordre(db, acteur, ordre.id)
    stock.enregistrer_mouvement(db, acteur, tube, "consommation", Decimal(ordre.pieces_theoriques),
                                f"Sortie vers l'ordre {ordre.numero}", ordre_fabrication_id=ordre.id)
    db.add(UtilisationBobine(entreprise_id=ordre.entreprise_id, bobine_id=ordre.bobine_id, ordre_id=ordre.id,
                             metrage_engage=ordre.metrage_engage))
    _valider_ou_annuler(db)
    return ordre


@transactionnel
def demarrer(db: Session, acteur: Utilisateur, ordre_id: uuid.UUID) -> OrdreFabrication:
    ordre = charger(db, acteur, ordre_id, verrou=True)
    _passer(db, ordre, acteur, ("matieres_validees",), "en_cours")
    _valider_ou_annuler(db)
    return ordre


@transactionnel
def saisir_resultat(db: Session, acteur: Utilisateur, ordre_id: uuid.UUID,
                    donnees: dict[str, Any]) -> OrdreFabrication:
    ordre = charger(db, acteur, ordre_id, verrou=True)
    correction = ordre.statut == "resultat_saisi"
    _passer(db, ordre, acteur, ("en_cours", "resultat_saisi"), "resultat_saisi",
            "Correction de la saisie" if correction else None)
    version = version_de(db, ordre)
    saisie = SaisieResultat(**{champ: donnees[champ] for champ in CHAMPS_SAISIE})
    try:
        calculs.calculer_resultat(saisie, version.pieces_par_tour, version.pieces_par_carton,
                                  ordre.pieces_theoriques or 0)
    except ErreurCalcul as erreur:
        db.rollback()
        raise DonneesInvalides(str(erreur)) from erreur
    for champ in CHAMPS_SAISIE:
        setattr(ordre, champ, donnees[champ])
    ordre.bobine_epuisee = donnees["bobine_epuisee"]
    ordre.resultat_saisi_par, ordre.resultat_saisi_le = acteur.id, maintenant()
    alertes = [a for a in ordre.alertes if a["code"] != "tours_superieurs_prevision"]
    if saisie.tours_totaux > (ordre.tours_prevus or 0):
        alertes.append(_alerte("tours_superieurs_prevision",
                               f"{saisie.tours_totaux} tours saisis pour {ordre.tours_prevus} prévus : "
                               "vérifiez le rapport de l'opérateur."))
    ordre.alertes = alertes
    _valider_ou_annuler(db)
    return ordre


@transactionnel
def valider_resultat(db: Session, acteur: Utilisateur, ordre_id: uuid.UUID) -> OrdreFabrication:
    ordre = charger(db, acteur, ordre_id, verrou=True)
    if ordre.statut != "resultat_saisi":
        db.rollback()
        raise Conflit(f"Transition impossible : l'ordre {ordre.numero} est « {ordre.statut} », "
                      "il doit être « resultat_saisi ».")
    if get_settings().separer_saisie_validation_resultat and ordre.resultat_saisi_par == acteur.id:
        db.rollback()
        raise OperationInterdite("La validation doit être faite par une autre personne que la saisie.")
    resultat = resultat_calcule(db, ordre)
    if resultat is None:
        db.rollback()
        raise DonneesInvalides("Résultat illisible : saisissez-le de nouveau.")
    if not resultat.coherent:
        db.rollback()
        sens = ("pièces non traitées : au moins une pièce non conforme n'est ni au Doctor Rewinder ni perdue"
                if resultat.ecart_comptage > 0 else
                "double comptage : Doctor Rewinder et pertes dépassent les pièces non conformes")
        raise DonneesInvalides(
            f"Contrôle de cohérence refusé — {sens}. Non conformes : {resultat.pieces_non_conformes} ; "
            f"Doctor Rewinder + pertes : {resultat.pieces_non_conformes - resultat.ecart_comptage} "
            f"(écart {resultat.ecart_comptage:+d}).")
    _passer(db, ordre, acteur, ("resultat_saisi",), "resultat_valide")
    ordre.pieces_brutes, ordre.pieces_non_conformes = resultat.pieces_brutes, resultat.pieces_non_conformes
    ordre.pieces_conformes, ordre.cartons_obtenus = resultat.pieces_conformes, resultat.cartons_complets
    ordre.pieces_restantes, ordre.ecart_pieces = resultat.pieces_restantes, resultat.ecart_pieces
    ordre.ecart_pourcentage, ordre.rendement = resultat.ecart_pourcentage, resultat.rendement
    ordre.version_formule = calculs.VERSION_FORMULE
    _valider_ou_annuler(db)
    return ordre


@transactionnel
def cloturer(db: Session, acteur: Utilisateur, ordre_id: uuid.UUID) -> OrdreFabrication:
    """Genere l'entree des produits finis (jamais saisie a la main) et regularise matieres et bobine."""
    ordre = charger(db, acteur, ordre_id, verrou=True)
    _passer(db, ordre, acteur, ("resultat_valide",), "cloture")
    version = version_de(db, ordre)
    produit = db.scalars(select(Article).where(Article.id == version.article_produit_fini_id)).one()
    tube = db.scalars(select(Article).where(Article.id == version.article_tube_id)).one()
    bobine = db.scalars(select(Bobine).where(Bobine.id == ordre.bobine_id)).one()
    motif = f"Fabrication de l'ordre {ordre.numero}"

    # Produits finis : en cartons complets (les pieces restantes restent un reliquat de l'ordre) ou en
    # pieces selon l'unite de gestion de l'article.
    quantite = ordre.pieces_conformes if produit.unite_gestion == "piece" else ordre.cartons_obtenus
    if quantite:
        stock.enregistrer_mouvement(db, acteur, produit, "entree", Decimal(quantite), motif,
                                    ordre_fabrication_id=ordre.id)
    # Tubes : chaque piece produite en a consomme un ; on corrige l'ecart avec la sortie prevue.
    ecart_tubes = ordre.pieces_brutes - ordre.pieces_theoriques
    if ecart_tubes < 0:
        stock.enregistrer_mouvement(db, acteur, tube, "retour", Decimal(-ecart_tubes),
                                    f"Tubes non utilisés — {motif}", ordre_fabrication_id=ordre.id)
    elif ecart_tubes > 0:
        stock.enregistrer_mouvement(db, acteur, tube, "consommation", Decimal(ecart_tubes),
                                    f"Tubes supplémentaires — {motif}", ordre_fabrication_id=ordre.id)
    # Bobine : epuisee (sortie du stock) ou entamee et toujours presente, sans metrage restant presume.
    if ordre.bobine_epuisee:
        jumbo = db.scalars(select(Article).where(Article.id == bobine.article_id)).one()
        stock.enregistrer_mouvement(db, acteur, jumbo, "consommation", Decimal(1),
                                    f"Bobine épuisée — {motif}", lot_id=bobine.lot_id, bobine_id=bobine.id,
                                    ordre_fabrication_id=ordre.id)
        bobine.statut = "epuisee"
    else:
        bobine.statut = "entamee_presente"
    _valider_ou_annuler(db)
    return ordre


@transactionnel
def annuler(db: Session, acteur: Utilisateur, ordre_id: uuid.UUID, motif: str) -> OrdreFabrication:
    ordre = charger(db, acteur, ordre_id, verrou=True)
    etat_avant = ordre.statut
    _passer(db, ordre, acteur, ("brouillon", "soumis", "matieres_validees", "en_cours", "resultat_saisi",
                                "resultat_valide"), "annule", motif)
    ordre.motif_annulation = motif
    stock.lever_reservations_ordre(db, acteur, ordre.id)
    if etat_avant not in ("brouillon", "soumis"):
        # Les tubes etaient sortis : on les remet en stock, trace par un mouvement de retour.
        version = version_de(db, ordre)
        tube = db.scalars(select(Article).where(Article.id == version.article_tube_id)).one()
        stock.enregistrer_mouvement(db, acteur, tube, "retour", Decimal(ordre.pieces_theoriques),
                                    f"Annulation de l'ordre {ordre.numero} : {motif}",
                                    ordre_fabrication_id=ordre.id)
    _valider_ou_annuler(db)
    return ordre
