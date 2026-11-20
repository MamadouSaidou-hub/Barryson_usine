"""Regles du module referentiel (M02).

Toute lecture passe par `_de_l_entreprise` : c'est le point de passage unique
du filtrage par entreprise (decision 0002). Un objet d'une autre entreprise
est introuvable, jamais simplement interdit.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import maintenant
from app.core.config import get_settings
from app.core.erreurs import Conflit, DonneesInvalides, Introuvable, OperationInterdite
from app.modules.identite.models import Utilisateur
from app.modules.referentiel.models import (
    Article,
    ConversionUnite,
    LargeurReference,
    ModeleRuban,
    Moule,
    ReferenceConditionnement,
    VersionModeleRuban,
)

# Reprise des donnees usine connues (cahier des charges officiel et fiche de synthese).
LARGEURS_CONNUES = {Decimal("45"): 28, Decimal("48"): 26, Decimal("55"): 23, Decimal("70"): 18}
CONDITIONNEMENTS_CONNUS = [
    ("bopp", Decimal("45"), Decimal("25"), 90),
    ("bopp", Decimal("45"), Decimal("50"), 72),
    ("bopp", Decimal("45"), Decimal("100"), 72),
    ("bopp", Decimal("48"), Decimal("200"), 36),
    ("bopp", Decimal("55"), Decimal("150"), 36),
]


# --- Mecanique commune ---------------------------------------------------------


def _de_l_entreprise[T](modele: type[T], entreprise_id: uuid.UUID) -> Select:
    return select(modele).where(modele.entreprise_id == entreprise_id)


def charger[T](db: Session, modele: type[T], acteur: Utilisateur, objet_id: uuid.UUID) -> T:
    objet = db.scalar(_de_l_entreprise(modele, acteur.entreprise_id).where(modele.id == objet_id))
    if objet is None:
        raise Introuvable()
    return objet


def lister[T](db: Session, modele: type[T], acteur: Utilisateur, *, actif: bool | None = None,
           recherche: str | None = None, tri: Any = None, **egalites: Any) -> list[T]:
    requete = _de_l_entreprise(modele, acteur.entreprise_id)
    if actif is not None and hasattr(modele, "actif"):
        requete = requete.where(modele.actif.is_(actif))
    for champ, valeur in egalites.items():
        if valeur is not None:
            requete = requete.where(getattr(modele, champ) == valeur)
    if recherche:
        # % et _ saisis par l'utilisateur sont cherches tels quels, pas comme jokers.
        texte = recherche.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        motif = f"%{texte}%"
        requete = requete.where(or_(modele.code.ilike(motif, escape="\\"),
                                    modele.nom.ilike(motif, escape="\\")))
    ordre = tri if isinstance(tri, tuple) else (tri if tri is not None else modele.code,)
    return list(db.scalars(requete.order_by(*ordre).limit(500)))


def _enregistrer(db: Session, objet: Any, message_doublon: str) -> Any:
    db.add(objet)
    try:
        db.commit()
    except IntegrityError as erreur:
        db.rollback()
        raise Conflit(message_doublon) from erreur
    return objet


def _appliquer(db: Session, objet: Any, changements: dict[str, Any],
               message_doublon: str = "Doublon.") -> Any:
    for champ, valeur in changements.items():
        setattr(objet, champ, valeur)
    return _enregistrer(db, objet, message_doublon)


def _verifier_seuils(seuil_min: Decimal | None, seuil_max: Decimal | None) -> None:
    if seuil_min is not None and seuil_max is not None and seuil_min > seuil_max:
        raise DonneesInvalides("Le seuil minimum ne peut pas dépasser le seuil maximum.")


# --- Articles ----------------------------------------------------------------


def creer_article(db: Session, acteur: Utilisateur, donnees: dict[str, Any]) -> Article:
    if donnees["niveau_stock"] == "matiere_premiere" and not get_settings().niveau_matiere_premiere_actif:
        raise OperationInterdite(
            "Le niveau matière première n'est pas activé : l'usine achète aujourd'hui tout sous forme de "
            "semi-finis. Il sera activé si une fabrication à partir de matière première reprend."
        )
    _verifier_seuils(donnees.get("seuil_min"), donnees.get("seuil_max"))
    article = Article(entreprise_id=acteur.entreprise_id, **donnees)
    return _enregistrer(db, article, "Un article porte déjà ce code.")


def modifier_article(db: Session, acteur: Utilisateur, article_id: uuid.UUID,
                     changements: dict[str, Any]) -> Article:
    article = charger(db, Article, acteur, article_id)
    _verifier_seuils(changements.get("seuil_min", article.seuil_min),
                     changements.get("seuil_max", article.seuil_max))
    return _appliquer(db, article, changements)


def _article_actif(db: Session, acteur: Utilisateur, article_id: uuid.UUID, niveau: str | None,
                   role: str) -> Article:
    try:
        article = charger(db, Article, acteur, article_id)
    except Introuvable as erreur:
        raise DonneesInvalides(f"{role} : article introuvable.") from erreur
    if not article.actif:
        raise DonneesInvalides(f"{role} : l'article {article.code} est désactivé.")
    if niveau is not None and article.niveau_stock != niveau:
        raise DonneesInvalides(f"{role} : l'article {article.code} n'est pas du niveau « {niveau} ».")
    return article


# --- Conversions d'unites ----------------------------------------------------


def creer_conversion(db: Session, acteur: Utilisateur, donnees: dict[str, Any]) -> ConversionUnite:
    if donnees["unite_source"] == donnees["unite_cible"]:
        raise DonneesInvalides("Les unités source et cible doivent différer.")
    if donnees.get("article_id") is not None:
        _article_actif(db, acteur, donnees["article_id"], None, "Conversion")
    conversion = ConversionUnite(entreprise_id=acteur.entreprise_id, **donnees)
    return _enregistrer(db, conversion, "Cette conversion existe déjà.")


def modifier_conversion(db: Session, acteur: Utilisateur, conversion_id: uuid.UUID,
                        changements: dict[str, Any]) -> ConversionUnite:
    return _appliquer(db, charger(db, ConversionUnite, acteur, conversion_id), changements)


# --- Moules, clients, fournisseurs -------------------------------------------


def creer_simple[T](db: Session, acteur: Utilisateur, modele: type[T], donnees: dict[str, Any]) -> T:
    objet = modele(entreprise_id=acteur.entreprise_id, **donnees)
    return _enregistrer(db, objet, "Ce code est déjà utilisé.")


def modifier_simple[T](db: Session, acteur: Utilisateur, modele: type[T], objet_id: uuid.UUID,
                    changements: dict[str, Any]) -> T:
    return _appliquer(db, charger(db, modele, acteur, objet_id), changements)


# --- References de production ------------------------------------------------


def creer_largeur(db: Session, acteur: Utilisateur, donnees: dict[str, Any]) -> LargeurReference:
    reference = LargeurReference(entreprise_id=acteur.entreprise_id, **donnees)
    return _enregistrer(db, reference, "Cette largeur est déjà référencée.")


def creer_conditionnement(db: Session, acteur: Utilisateur,
                          donnees: dict[str, Any]) -> ReferenceConditionnement:
    reference = ReferenceConditionnement(entreprise_id=acteur.entreprise_id, **donnees)
    return _enregistrer(db, reference, "Ce conditionnement est déjà référencé.")


def pieces_par_tour_de_reference(db: Session, entreprise_id: uuid.UUID, largeur_mm: Decimal) -> int | None:
    return db.scalar(select(LargeurReference.pieces_par_tour).where(
        LargeurReference.entreprise_id == entreprise_id, LargeurReference.largeur_mm == largeur_mm))


def pieces_par_carton_de_reference(db: Session, entreprise_id: uuid.UUID, famille: str, largeur_mm: Decimal,
                                   longueur_m: Decimal) -> int | None:
    return db.scalar(select(ReferenceConditionnement.pieces_par_carton).where(
        ReferenceConditionnement.entreprise_id == entreprise_id,
        ReferenceConditionnement.famille == famille,
        ReferenceConditionnement.largeur_mm == largeur_mm,
        ReferenceConditionnement.longueur_m == longueur_m,
    ))


# --- Modeles de ruban (versionnes) ------------------------------------------


def version_courante(db: Session, modele_id: uuid.UUID) -> VersionModeleRuban:
    return db.scalars(select(VersionModeleRuban).where(VersionModeleRuban.modele_id == modele_id)
                      .order_by(VersionModeleRuban.numero.desc()).limit(1)).one()


def historique(db: Session, acteur: Utilisateur, modele_id: uuid.UUID) -> list[VersionModeleRuban]:
    charger(db, ModeleRuban, acteur, modele_id)
    return list(db.scalars(select(VersionModeleRuban).where(VersionModeleRuban.modele_id == modele_id)
                           .order_by(VersionModeleRuban.numero.desc())))


def est_complet(version: VersionModeleRuban) -> bool:
    return None not in (version.moule_id, version.article_produit_fini_id, version.article_tube_id)


def _construire_version(db: Session, acteur: Utilisateur, modele: ModeleRuban, numero: int,
                        caracteristiques: dict[str, Any], motif: str) -> VersionModeleRuban:
    largeur, longueur = caracteristiques["largeur_mm"], caracteristiques["longueur_rouleau_m"]

    pieces_par_tour = caracteristiques.get("pieces_par_tour") or pieces_par_tour_de_reference(
        db, acteur.entreprise_id, largeur)
    if pieces_par_tour is None:
        raise DonneesInvalides(f"Pièces par tour inconnues pour {largeur} mm : renseignez-les ou ajoutez "
                               "cette largeur aux références.")
    pieces_par_carton = caracteristiques.get("pieces_par_carton") or pieces_par_carton_de_reference(
        db, acteur.entreprise_id, modele.famille, largeur, longueur)
    if pieces_par_carton is None:
        raise DonneesInvalides(f"Pièces par carton inconnues pour {modele.famille} {largeur} mm × "
                               f"{longueur} m : "
                               "renseignez-les ou ajoutez ce conditionnement aux références.")

    if caracteristiques.get("moule_id") is not None:
        moule = charger_ou_invalide(db, Moule, acteur, caracteristiques["moule_id"], "Moule")
        if not moule.actif:
            raise DonneesInvalides(f"Le moule {moule.code} est désactivé.")
    if caracteristiques.get("article_produit_fini_id") is not None:
        _article_actif(db, acteur, caracteristiques["article_produit_fini_id"], "produit_fini",
                       "Produit fini")
    if caracteristiques.get("article_tube_id") is not None:
        _article_actif(db, acteur, caracteristiques["article_tube_id"], "semi_fini", "Tube papier")

    return VersionModeleRuban(
        entreprise_id=acteur.entreprise_id,
        modele_id=modele.id,
        numero=numero,
        largeur_mm=largeur,
        longueur_rouleau_m=longueur,
        pieces_par_tour=pieces_par_tour,
        pieces_par_carton=pieces_par_carton,
        moule_id=caracteristiques.get("moule_id"),
        article_produit_fini_id=caracteristiques.get("article_produit_fini_id"),
        article_tube_id=caracteristiques.get("article_tube_id"),
        motif=motif,
        cree_par=acteur.id,
        cree_le=maintenant(),
    )


def charger_ou_invalide[T](db: Session, modele: type[T], acteur: Utilisateur, objet_id: uuid.UUID,
                           role: str) -> T:
    try:
        return charger(db, modele, acteur, objet_id)
    except Introuvable as erreur:
        raise DonneesInvalides(f"{role} introuvable.") from erreur


def creer_modele(db: Session, acteur: Utilisateur, donnees: dict[str, Any]) -> ModeleRuban:
    identite = {k: donnees.pop(k) for k in ("code", "nom", "famille")}
    if db.scalar(_de_l_entreprise(ModeleRuban, acteur.entreprise_id)
                 .where(ModeleRuban.code == identite["code"])) is not None:
        raise Conflit("Un modèle porte déjà ce code.")
    modele = ModeleRuban(entreprise_id=acteur.entreprise_id, **identite)
    db.add(modele)
    db.flush()
    try:
        db.add(_construire_version(db, acteur, modele, 1, donnees, "Création du modèle"))
    except Exception:
        db.rollback()  # pas de fiche sans version
        raise
    return _enregistrer(db, modele, "Un modèle porte déjà ce code.")


def nouvelle_version(db: Session, acteur: Utilisateur, modele_id: uuid.UUID,
                     donnees: dict[str, Any]) -> ModeleRuban:
    """Toute evolution d'une fiche cree une version : les precedentes restent intactes."""
    modele = db.scalar(_de_l_entreprise(ModeleRuban, acteur.entreprise_id)
                       .where(ModeleRuban.id == modele_id).with_for_update())
    if modele is None:
        raise Introuvable()
    if not modele.actif:
        db.rollback()
        raise OperationInterdite("Modèle désactivé : réactivez-le avant de le faire évoluer.")
    courante = version_courante(db, modele.id)
    motif = donnees.pop("motif")
    caracteristiques = {
        champ: donnees[champ] if champ in donnees else getattr(courante, champ)
        for champ in ("largeur_mm", "longueur_rouleau_m", "moule_id", "article_produit_fini_id",
                      "article_tube_id")
    }
    # Pieces : recalculees depuis les references si les dimensions changent sans valeur fournie.
    dimensions_changees = any(caracteristiques[c] != getattr(courante, c)
                              for c in ("largeur_mm", "longueur_rouleau_m"))
    for champ in ("pieces_par_tour", "pieces_par_carton"):
        if champ in donnees and donnees[champ] is not None:
            caracteristiques[champ] = donnees[champ]
        elif not dimensions_changees:
            caracteristiques[champ] = getattr(courante, champ)
    try:
        db.add(_construire_version(db, acteur, modele, courante.numero + 1, caracteristiques, motif))
    except Exception:
        db.rollback()  # libere aussi le verrou pose sur le modele
        raise
    return _enregistrer(db, modele, "Version concurrente : réessayez.")


def modifier_modele(db: Session, acteur: Utilisateur, modele_id: uuid.UUID,
                    changements: dict[str, Any]) -> ModeleRuban:
    return _appliquer(db, charger(db, ModeleRuban, acteur, modele_id), changements)


# --- Donnees de reference de l'usine -----------------------------------------


def charger_references_connues(db: Session, entreprise_id: uuid.UUID) -> dict[str, int]:
    """Charge les largeurs et conditionnements connus. Idempotent : n'ecrase jamais une valeur existante."""
    ajouts = {"largeurs": 0, "conditionnements": 0}
    for largeur, pieces in LARGEURS_CONNUES.items():
        if pieces_par_tour_de_reference(db, entreprise_id, largeur) is None:
            db.add(LargeurReference(entreprise_id=entreprise_id, largeur_mm=largeur, pieces_par_tour=pieces))
            ajouts["largeurs"] += 1
    for famille, largeur, longueur, pieces in CONDITIONNEMENTS_CONNUS:
        if pieces_par_carton_de_reference(db, entreprise_id, famille, largeur, longueur) is None:
            db.add(ReferenceConditionnement(entreprise_id=entreprise_id, famille=famille, largeur_mm=largeur,
                                            longueur_m=longueur, pieces_par_carton=pieces))
            ajouts["conditionnements"] += 1
    db.commit()
    return ajouts

