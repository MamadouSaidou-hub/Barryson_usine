"""Regles du Doctor Rewinder (M07) : envoi, traitement, validation.

Un encours est ouvert par la cloture de l'ordre de fabrication (jamais saisi a la main). Le chef de production
declare ce qui a ete recupere et ce qui est definitivement perdu ; une autre personne (DG ou son delegataire)
valide, et c'est cette validation seule qui fait entrer les pieces recuperees en stock de produits finis.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import maintenant
from app.core.config import get_settings
from app.core.erreurs import Conflit, DonneesInvalides, Introuvable, OperationInterdite
from app.core.transactions import transactionnel
from app.modules.doctor_rewinder.models import EncoursDoctorRewinder
from app.modules.identite.models import Utilisateur
from app.modules.production.models import OrdreFabrication
from app.modules.referentiel.models import Article
from app.modules.stock import service as stock


def charger(db: Session, acteur: Utilisateur, encours_id: uuid.UUID, *,
            verrou: bool = False) -> EncoursDoctorRewinder:
    requete = select(EncoursDoctorRewinder).where(EncoursDoctorRewinder.entreprise_id == acteur.entreprise_id,
                                                  EncoursDoctorRewinder.id == encours_id)
    encours = db.scalar(requete.with_for_update() if verrou else requete)
    if encours is None:
        raise Introuvable()
    return encours


def lister(db: Session, acteur: Utilisateur, *, statut: str | None, ordre_id: uuid.UUID | None,
           limite: int = 200) -> list[EncoursDoctorRewinder]:
    requete = select(EncoursDoctorRewinder).where(EncoursDoctorRewinder.entreprise_id == acteur.entreprise_id)
    if statut is not None:
        requete = requete.where(EncoursDoctorRewinder.statut == statut)
    if ordre_id is not None:
        requete = requete.where(EncoursDoctorRewinder.ordre_id == ordre_id)
    return list(db.scalars(requete.order_by(EncoursDoctorRewinder.date_envoi, EncoursDoctorRewinder.cree_le)
                           .limit(limite)))


def ouvrir_pour_ordre(db: Session, ordre: OrdreFabrication, article_id: uuid.UUID,
                      pieces_par_carton: int) -> EncoursDoctorRewinder | None:
    """Appele par la cloture de l'ordre (meme transaction, sans commit). Rien a ouvrir si rien n'est parti."""
    envoyees = ordre.quantite_doctor_rewinder or 0
    if envoyees <= 0:
        return None
    encours = EncoursDoctorRewinder(
        entreprise_id=ordre.entreprise_id, ordre_id=ordre.id, bobine_id=ordre.bobine_id,
        modele_id=ordre.modele_id, article_id=article_id, pieces_par_carton=pieces_par_carton,
        metrage=ordre.metrage_engage, quantite_envoyee=envoyees,
        date_envoi=(ordre.resultat_saisi_le or maintenant()).date())
    db.add(encours)
    return encours


@transactionnel
def traiter(db: Session, acteur: Utilisateur, encours_id: uuid.UUID,
            donnees: dict[str, Any]) -> EncoursDoctorRewinder:
    """Declare le retour du Doctor Rewinder : recupere + non recuperable = tout ce qui avait ete envoye."""
    encours = charger(db, acteur, encours_id, verrou=True)
    if encours.statut == "traite":
        db.rollback()
        raise Conflit("Cet encours est déjà validé : le traitement ne se modifie plus.")
    recuperee, perdue = donnees["quantite_recuperee"], donnees["quantite_non_recuperable"]
    if recuperee + perdue != encours.quantite_envoyee:
        db.rollback()
        raise DonneesInvalides(
            f"{encours.quantite_envoyee} pièces avaient été envoyées : récupérées ({recuperee}) + non "
            f"récupérables ({perdue}) = {recuperee + perdue}. Toute pièce envoyée doit être comptée.")
    encours.quantite_recuperee, encours.quantite_non_recuperable = recuperee, perdue
    encours.commentaire = donnees.get("commentaire")
    encours.traite_par, encours.date_traitement = acteur.id, maintenant()
    encours.statut = "a_valider"
    db.commit()
    return encours


@transactionnel
def valider(db: Session, acteur: Utilisateur, encours_id: uuid.UUID) -> EncoursDoctorRewinder:
    """Valide le traitement : les pieces recuperees entrent en stock, les autres sont perdues."""
    encours = charger(db, acteur, encours_id, verrou=True)
    if encours.statut != "a_valider":
        db.rollback()
        raise Conflit(f"Validation impossible : l'encours est « {encours.statut} », "
                      "il doit être « a_valider ».")
    if get_settings().validations_actives and encours.traite_par == acteur.id:
        db.rollback()
        raise OperationInterdite("La validation doit être faite par une autre personne que celle qui a "
                                 "déclaré le traitement.")
    article = db.scalars(select(Article).where(Article.id == encours.article_id)).one()
    ordre = db.scalars(select(OrdreFabrication).where(OrdreFabrication.id == encours.ordre_id)).one()
    recuperee = encours.quantite_recuperee or 0
    if article.unite_gestion == "piece":
        quantite, reliquat = recuperee, 0
    else:
        quantite, reliquat = divmod(recuperee, encours.pieces_par_carton)
    if quantite:
        mouvement = stock.enregistrer_mouvement(
            db, acteur, article, "entree", Decimal(quantite),
            f"Pièces récupérées au Doctor Rewinder — ordre {ordre.numero}", ordre_fabrication_id=ordre.id)
        db.flush()
        encours.mouvement_id = mouvement.id
    encours.pieces_reliquat = reliquat
    encours.valide_par, encours.valide_le = acteur.id, maintenant()
    encours.statut = "traite"
    db.commit()
    return encours


@transactionnel
def renvoyer(db: Session, acteur: Utilisateur, encours_id: uuid.UUID, motif: str) -> EncoursDoctorRewinder:
    """Refuse un traitement declare (chiffres a revoir) : l'encours retourne a son auteur, motif conserve."""
    encours = charger(db, acteur, encours_id, verrou=True)
    if encours.statut != "a_valider":
        db.rollback()
        raise Conflit(f"Renvoi impossible : l'encours est « {encours.statut} », il doit être « a_valider ».")
    encours.quantite_recuperee = encours.quantite_non_recuperable = None
    encours.commentaire = f"Renvoyé : {motif}"
    encours.traite_par = encours.date_traitement = None
    encours.statut = "en_cours"
    db.commit()
    return encours


def indicateurs(db: Session, acteur: Utilisateur) -> dict[str, Any]:
    """Les indicateurs du cockpit (§7) ; chacun porte l'identifiant de quoi descendre jusqu'au detail."""
    base = EncoursDoctorRewinder.entreprise_id == acteur.entreprise_id
    ouverts = EncoursDoctorRewinder.statut != "traite"
    nombre_ouverts, pieces_ouvertes = db.execute(
        select(func.count(), func.coalesce(func.sum(EncoursDoctorRewinder.quantite_envoyee), 0))
        .where(base, ouverts)).one()
    envoyees, recuperees = db.execute(
        select(func.coalesce(func.sum(EncoursDoctorRewinder.quantite_envoyee), 0),
               func.coalesce(func.sum(EncoursDoctorRewinder.quantite_recuperee), 0))
        .where(base, EncoursDoctorRewinder.statut == "traite")).one()
    traites = list(db.scalars(select(EncoursDoctorRewinder)
                              .where(base, EncoursDoctorRewinder.statut == "traite")))
    delais = [(t.valide_le.date() - t.date_envoi).days for t in traites if t.valide_le]
    plus_ancien = db.scalar(
        select(EncoursDoctorRewinder).where(base, ouverts)
        .order_by(EncoursDoctorRewinder.date_envoi, EncoursDoctorRewinder.cree_le).limit(1))
    return {
        "encours_ouverts": nombre_ouverts, "pieces_en_cours": pieces_ouvertes,
        "a_valider": db.scalar(select(func.count()).where(base, EncoursDoctorRewinder.statut == "a_valider")),
        "pieces_envoyees_traitees": envoyees, "pieces_recuperees": recuperees,
        "taux_recuperation": (Decimal(recuperees) / Decimal(envoyees)) if envoyees else None,
        "delai_moyen_jours": (Decimal(sum(delais)) / Decimal(len(delais))) if delais else None,
        "anciennete_max_jours": (date.today() - plus_ancien.date_envoi).days if plus_ancien else None,
        "plus_ancien_id": plus_ancien.id if plus_ancien else None,
    }
