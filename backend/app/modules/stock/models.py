"""Tables du module stock (M04/M05).

Le stock n'est jamais un compteur : c'est la somme des mouvements. Un
mouvement ne se modifie ni ne se supprime (privileges + trigger) ; une erreur
se corrige par un mouvement inverse. Un mouvement qui engage l'usine
(ajustement, sortie exceptionnelle, entree directe...) ne compte qu'une fois
valide par une autre personne que celle qui l'a saisi.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, get_args

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.audit import Audite, maintenant
from app.core.db import Base

TypeMouvement = Literal[
    "reception", "entree", "entree_directe", "retour",
    "consommation", "sortie", "sortie_exceptionnelle", "rebut_destruction",
    "transformation", "ajustement", "inventaire",
    # Saisies manuelles sans circuit de validation (phase de developpement) : voir validations_actives.
    "entree_manuelle", "sortie_manuelle",
]
StatutBobine = Literal["disponible", "entamee_presente", "epuisee"]
CouleurFinition = Literal["jaune_transparent", "transparent_clair", "or_transparent", "kaki_simple",
                          "kaki_imprime"]
CouleurImpression = Literal["rouge", "noir", "bleu"]
StatutImport = Literal["brouillon", "valide", "annule"]

TYPES: tuple[str, ...] = get_args(TypeMouvement)
STATUTS_BOBINE: tuple[str, ...] = get_args(StatutBobine)
FINITIONS: tuple[str, ...] = get_args(CouleurFinition)
COULEURS_IMPRESSION: tuple[str, ...] = get_args(CouleurImpression)
MODULES_IMPRESSION = (45, 48, 70)

# Signe impose par le type : l'API recoit une quantite positive, jamais un signe a deviner.
TYPES_ENTREE = ("reception", "entree", "entree_directe", "retour", "entree_manuelle")
TYPES_SORTIE = ("consommation", "sortie", "sortie_exceptionnelle", "rebut_destruction", "sortie_manuelle")
# Types qui engagent l'usine : comptent seulement une fois valides par une autre personne.
TYPES_A_VALIDER = ("entree_directe", "sortie_exceptionnelle", "rebut_destruction", "ajustement", "inventaire")


def _liste(valeurs: tuple) -> str:
    return ", ".join(repr(v) for v in valeurs)


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _entreprise() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("entreprises.id"), index=True)


def _horodatage() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=maintenant, server_default=func.now())


class Lot(Audite, Base):
    """Un conteneur recu = un lot."""

    __tablename__ = "lots"
    __table_args__ = (UniqueConstraint("entreprise_id", "conteneur_reference"),)

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = _entreprise()
    conteneur_reference: Mapped[str] = mapped_column(String(60))
    # Associe au lot sans jamais remplacer son identifiant.
    numero_facture: Mapped[str | None] = mapped_column(String(60))
    date_reception: Mapped[date] = mapped_column(Date)
    fournisseur_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fournisseurs.id"))
    cree_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    cree_le: Mapped[datetime] = _horodatage()


class Bobine(Audite, Base):
    """Identifiant interne = (lot, numero fournisseur) : deux lots peuvent partager un numero."""

    __tablename__ = "bobines"
    __table_args__ = (
        UniqueConstraint("lot_id", "numero_fournisseur"),
        CheckConstraint(f"statut IN ({_liste(STATUTS_BOBINE)})", name="statut_connu"),
        CheckConstraint(f"couleur_finition IN ({_liste(FINITIONS)})", name="finition_connue"),
        CheckConstraint("couleur_impression IS NULL OR couleur_impression IN "
                        f"({_liste(COULEURS_IMPRESSION)})", name="impression_connue"),
        CheckConstraint(f"module_impression IS NULL OR module_impression IN ({_liste(MODULES_IMPRESSION)})",
                        name="module_connu"),
        CheckConstraint("(couleur_impression IS NULL AND module_impression IS NULL) "
                        "OR couleur_finition = 'kaki_imprime'", name="impression_coherente"),
        CheckConstraint("poids_kg > 0", name="poids_positif"),
        CheckConstraint("metrage_propre IS NULL OR metrage_propre > 0", name="metrage_positif"),
    )

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = _entreprise()
    lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lots.id"), index=True)
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id"), index=True)
    numero_fournisseur: Mapped[str] = mapped_column(String(40))
    poids_kg: Mapped[Decimal] = mapped_column(Numeric(9, 2))
    # Metrage initial, consultable pour l'historique. Jamais presente comme quantite
    # disponible : une bobine entamee n'a pas de metrage restant mesure (decision client).
    metrage_propre: Mapped[Decimal | None] = mapped_column(Numeric(11, 2))
    couleur_finition: Mapped[str] = mapped_column(String(30))
    couleur_impression: Mapped[str | None] = mapped_column(String(10))
    module_impression: Mapped[int | None] = mapped_column(Integer)
    statut: Mapped[str] = mapped_column(String(20), default="disponible", server_default="disponible")
    # Reserve a l'evolution "mesure du metrage restant" : non expose en v1.
    metrage_restant_m: Mapped[Decimal | None] = mapped_column(Numeric(11, 2))
    cree_le: Mapped[datetime] = _horodatage()


class MouvementStock(Audite, Base):
    __tablename__ = "mouvements_stock"
    __table_args__ = (
        CheckConstraint(f"type IN ({_liste(TYPES)})", name="type_connu"),
        CheckConstraint("quantite <> 0", name="quantite_non_nulle"),
        CheckConstraint(f"type NOT IN ({_liste(TYPES_ENTREE)}) OR quantite > 0", name="entree_positive"),
        CheckConstraint(f"type NOT IN ({_liste(TYPES_SORTIE)}) OR quantite < 0", name="sortie_negative"),
        CheckConstraint(f"requiert_validation = (type IN ({_liste(TYPES_A_VALIDER)}))",
                        name="validation_selon_type"),
        CheckConstraint("cout_unitaire_gnf IS NULL OR cout_unitaire_gnf >= 0", name="cout_positif"),
        Index("ix_mouvements_stock_article_cree", "entreprise_id", "article_id", "cree_le"),
    )

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = _entreprise()
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id"))
    type: Mapped[str] = mapped_column(String(25))
    quantite: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unite: Mapped[str] = mapped_column(String(10))
    lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lots.id"))
    bobine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bobines.id"))
    ordre_fabrication_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ordres_fabrication.id"))
    # Prepare la valorisation (CMUP ou autre) sans migration : methode a definir avec le DG.
    cout_unitaire_gnf: Mapped[int | None] = mapped_column(BigInteger)
    requiert_validation: Mapped[bool] = mapped_column(Boolean)
    motif: Mapped[str] = mapped_column(Text)
    piece_justificative_url: Mapped[str | None] = mapped_column(String(500))
    cree_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    cree_le: Mapped[datetime] = _horodatage()


class ValidationMouvement(Audite, Base):
    """Decision sur un mouvement a valider. Une seule par mouvement, jamais modifiee."""

    __tablename__ = "validations_mouvements"
    __table_args__ = (
        CheckConstraint("decision IN ('valide', 'rejete')", name="decision_connue"),
        CheckConstraint("decision = 'valide' OR length(motif) >= 5", name="rejet_motive"),
    )

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = _entreprise()
    mouvement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mouvements_stock.id"), unique=True)
    decision: Mapped[str] = mapped_column(String(10))
    valide_par: Mapped[uuid.UUID] = mapped_column(ForeignKey("utilisateurs.id"))
    # Renseigne quand un delegataire valide au nom du DG : la decision reste imputable.
    delegation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("delegations.id"))
    motif: Mapped[str | None] = mapped_column(Text)
    cree_le: Mapped[datetime] = _horodatage()


class Reservation(Audite, Base):
    """Quantite promise (ordre de fabrication, commande) : sort du disponible sans sortir du physique."""

    __tablename__ = "reservations_stock"
    __table_args__ = (
        CheckConstraint("quantite > 0", name="quantite_positive"),
        CheckConstraint("statut IN ('ouverte', 'levee')", name="statut_connu"),
        CheckConstraint("(statut = 'ouverte') = (levee_le IS NULL)", name="levee_coherente"),
    )

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = _entreprise()
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id"), index=True)
    quantite: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    motif: Mapped[str] = mapped_column(Text)
    ordre_fabrication_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ordres_fabrication.id"),
                                                                   index=True)
    statut: Mapped[str] = mapped_column(String(10), default="ouverte", server_default="ouverte")
    cree_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    cree_le: Mapped[datetime] = _horodatage()
    levee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    levee_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))


class ImportColisage(Audite, Base):
    """Packing list en cours de verification. Rien n'entre en stock avant la validation."""

    __tablename__ = "imports_colisage"
    __table_args__ = (
        CheckConstraint("statut IN ('brouillon', 'valide', 'annule')", name="statut_connu"),
        Index("ix_imports_colisage_entreprise_statut", "entreprise_id", "statut"),
    )
    # Compteurs recalcules a chaque analyse : le journal ne tracerait que du bruit.
    __audit_ignore__ = frozenset({"nb_bloquantes", "nb_avertissements"})

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = _entreprise()
    conteneur_reference: Mapped[str] = mapped_column(String(60))
    numero_facture: Mapped[str | None] = mapped_column(String(60))
    date_reception: Mapped[date] = mapped_column(Date)
    fournisseur_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fournisseurs.id"))
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id"))
    statut: Mapped[str] = mapped_column(String(10), default="brouillon", server_default="brouillon")
    nb_lignes: Mapped[int] = mapped_column(Integer)
    nb_bloquantes: Mapped[int] = mapped_column(Integer)
    nb_avertissements: Mapped[int] = mapped_column(Integer)
    cree_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    cree_le: Mapped[datetime] = _horodatage()
    valide_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    valide_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lots.id"))
    # Rattache a une reception d'achat : seul le controle de conformite de cette reception peut le
    # valider ou l'abandonner, jamais un appel direct (le controle ne doit pas etre contournable).
    rattache_reception: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class LigneImportColisage(Base):
    __tablename__ = "lignes_import_colisage"
    __table_args__ = (UniqueConstraint("import_id", "rang"),)

    id: Mapped[uuid.UUID] = _id()
    import_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("imports_colisage.id"), index=True)
    rang: Mapped[int] = mapped_column(Integer)
    numero_fournisseur: Mapped[str | None] = mapped_column(String(40))
    poids_kg: Mapped[Decimal | None] = mapped_column(Numeric(9, 2))
    metrage_propre: Mapped[Decimal | None] = mapped_column(Numeric(11, 2))
    # Valeur telle que recue du fournisseur (ex. "Golden01"), gardee pour la trace.
    couleur_brute: Mapped[str | None] = mapped_column(String(60))
    couleur_finition: Mapped[str | None] = mapped_column(String(30))
    couleur_impression: Mapped[str | None] = mapped_column(String(10))
    module_impression: Mapped[int | None] = mapped_column(Integer)
    anomalies: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
