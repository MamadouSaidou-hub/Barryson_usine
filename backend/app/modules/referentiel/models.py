"""Tables du module referentiel (M02).

Aucune de ces lignes ne se supprime : elles se desactivent (`actif`). Un
article, un client ou un moule reference par un mouvement de stock ou une
vente doit rester lisible pour toujours. La migration retire DELETE au
compte de l'API.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal, get_args

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.audit import Audite, maintenant
from app.core.db import Base

NiveauStock = Literal["matiere_premiere", "semi_fini", "produit_fini"]
Unite = Literal["kg", "m", "rouleau", "piece", "panier", "carton"]
FamilleRuban = Literal["bopp", "pvc_electrique", "masquage"]
TypeClient = Literal["entreprise_partenaire", "revendeur", "boutique", "autre"]

NIVEAUX: tuple[str, ...] = get_args(NiveauStock)
UNITES: tuple[str, ...] = get_args(Unite)
FAMILLES: tuple[str, ...] = get_args(FamilleRuban)
TYPES_CLIENT: tuple[str, ...] = get_args(TypeClient)


def _dans(colonne: str, valeurs: tuple[str, ...]) -> str:
    return f"{colonne} IN ({', '.join(repr(v) for v in valeurs)})"


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _entreprise() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("entreprises.id"), index=True)


def _horodatage() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=maintenant, server_default=func.now())


def _actif() -> Mapped[bool]:
    return mapped_column(Boolean, default=True, server_default="true")


class Article(Audite, Base):
    """Tout ce qui se compte en stock. Un article appartient a un seul niveau, pour toujours."""

    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("entreprise_id", "code"),
        CheckConstraint(_dans("niveau_stock", NIVEAUX), name="niveau_connu"),
        CheckConstraint(_dans("unite_gestion", UNITES), name="unite_connue"),
        CheckConstraint("seuil_min IS NULL OR seuil_min >= 0", name="seuil_min_positif"),
        CheckConstraint("seuil_min IS NULL OR seuil_max IS NULL OR seuil_min <= seuil_max",
                        name="seuils_ordonnes"),
    )

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = _entreprise()
    code: Mapped[str] = mapped_column(String(40))
    nom: Mapped[str] = mapped_column(String(150))
    niveau_stock: Mapped[str] = mapped_column(String(20))
    unite_gestion: Mapped[str] = mapped_column(String(10))
    seuil_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    seuil_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    actif: Mapped[bool] = _actif()
    cree_le: Mapped[datetime] = _horodatage()


class ConversionUnite(Audite, Base):
    """Facteur de conversion, general (article_id nul) ou propre a un article."""

    __tablename__ = "conversions_unites"
    __table_args__ = (
        # NULLS NOT DISTINCT : deux conversions generales (article nul) identiques sont un doublon.
        UniqueConstraint("entreprise_id", "article_id", "unite_source", "unite_cible",
                         name="uq_conversions_unites_cle", postgresql_nulls_not_distinct=True),
        CheckConstraint(_dans("unite_source", UNITES), name="source_connue"),
        CheckConstraint(_dans("unite_cible", UNITES), name="cible_connue"),
        CheckConstraint("unite_source <> unite_cible", name="unites_distinctes"),
        CheckConstraint("facteur > 0", name="facteur_positif"),
    )

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = _entreprise()
    article_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("articles.id"))
    unite_source: Mapped[str] = mapped_column(String(10))
    unite_cible: Mapped[str] = mapped_column(String(10))
    facteur: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    actif: Mapped[bool] = _actif()
    cree_le: Mapped[datetime] = _horodatage()


class Moule(Audite, Base):
    __tablename__ = "moules"
    __table_args__ = (UniqueConstraint("entreprise_id", "code"),)

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = _entreprise()
    code: Mapped[str] = mapped_column(String(40))
    nom: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)
    actif: Mapped[bool] = _actif()
    cree_le: Mapped[datetime] = _horodatage()


class LargeurReference(Audite, Base):
    """Nombre de pieces obtenues par tour pour une largeur de bande (donnee usine, pas du code)."""

    __tablename__ = "largeurs_reference"
    __table_args__ = (
        UniqueConstraint("entreprise_id", "largeur_mm"),
        CheckConstraint("largeur_mm > 0", name="largeur_positive"),
        CheckConstraint("pieces_par_tour > 0", name="pieces_positives"),
    )

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = _entreprise()
    largeur_mm: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    pieces_par_tour: Mapped[int] = mapped_column(Integer)
    cree_le: Mapped[datetime] = _horodatage()


class ReferenceConditionnement(Audite, Base):
    """Pieces par carton connues pour une famille, une largeur et une longueur."""

    __tablename__ = "references_conditionnement"
    __table_args__ = (
        UniqueConstraint("entreprise_id", "famille", "largeur_mm", "longueur_m",
                         name="uq_references_conditionnement_cle"),
        CheckConstraint(_dans("famille", FAMILLES), name="famille_connue"),
        CheckConstraint("largeur_mm > 0 AND longueur_m > 0", name="dimensions_positives"),
        CheckConstraint("pieces_par_carton > 0", name="pieces_positives"),
    )

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = _entreprise()
    famille: Mapped[str] = mapped_column(String(20))
    largeur_mm: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    longueur_m: Mapped[Decimal] = mapped_column(Numeric(9, 3))
    pieces_par_carton: Mapped[int] = mapped_column(Integer)
    cree_le: Mapped[datetime] = _horodatage()


class ModeleRuban(Audite, Base):
    """Identite stable d'un modele (ex. BSG 30). Ses caracteristiques vivent dans ses versions."""

    __tablename__ = "modeles_ruban"
    __table_args__ = (
        UniqueConstraint("entreprise_id", "code"),
        CheckConstraint(_dans("famille", FAMILLES), name="famille_connue"),
    )

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = _entreprise()
    code: Mapped[str] = mapped_column(String(40))
    nom: Mapped[str] = mapped_column(String(150))
    famille: Mapped[str] = mapped_column(String(20))
    actif: Mapped[bool] = _actif()
    cree_le: Mapped[datetime] = _horodatage()


class VersionModeleRuban(Audite, Base):
    """Caracteristiques d'un modele a une date. Jamais modifiee : on cree la version suivante.

    Un ordre de fabrication reste lie a la version en vigueur a sa creation,
    donc ses previsions restent explicables meme apres un changement de fiche.
    """

    __tablename__ = "versions_modeles_ruban"
    __table_args__ = (
        UniqueConstraint("modele_id", "numero"),
        CheckConstraint("numero >= 1", name="numero_positif"),
        CheckConstraint("largeur_mm > 0 AND longueur_rouleau_m > 0", name="dimensions_positives"),
        CheckConstraint("pieces_par_tour > 0 AND pieces_par_carton > 0", name="pieces_positives"),
    )

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = _entreprise()
    modele_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modeles_ruban.id"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    largeur_mm: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    longueur_rouleau_m: Mapped[Decimal] = mapped_column(Numeric(9, 3))
    pieces_par_tour: Mapped[int] = mapped_column(Integer)
    pieces_par_carton: Mapped[int] = mapped_column(Integer)
    moule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("moules.id"))
    # Produit fini fabrique et tube papier consomme : encore inconnus pour certains
    # modeles (nomenclature attendue du client) ; exiges au lancement d'un ordre.
    article_produit_fini_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("articles.id"))
    article_tube_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("articles.id"))
    motif: Mapped[str] = mapped_column(String(300))
    cree_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    cree_le: Mapped[datetime] = _horodatage()


class Client(Audite, Base):
    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("entreprise_id", "code"),
        CheckConstraint(_dans("type_client", TYPES_CLIENT), name="type_connu"),
        CheckConstraint("plafond_encours_gnf IS NULL OR plafond_encours_gnf >= 0", name="plafond_positif"),
        CheckConstraint("delai_paiement_jours IS NULL OR delai_paiement_jours >= 0", name="delai_positif"),
    )

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = _entreprise()
    code: Mapped[str] = mapped_column(String(40))
    nom: Mapped[str] = mapped_column(String(200))
    type_client: Mapped[str] = mapped_column(String(30))
    telephone: Mapped[str | None] = mapped_column(String(40))
    adresse: Mapped[str | None] = mapped_column(String(300))
    zone: Mapped[str | None] = mapped_column(String(100))
    # Montants en GNF : entiers, la monnaie n'a pas de subdivision en usage.
    plafond_encours_gnf: Mapped[int | None] = mapped_column(BigInteger)
    delai_paiement_jours: Mapped[int | None] = mapped_column(Integer)
    actif: Mapped[bool] = _actif()
    cree_le: Mapped[datetime] = _horodatage()


class Fournisseur(Audite, Base):
    __tablename__ = "fournisseurs"
    __table_args__ = (
        UniqueConstraint("entreprise_id", "code"),
        CheckConstraint("delai_livraison_jours IS NULL OR delai_livraison_jours >= 0", name="delai_positif"),
    )

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = _entreprise()
    code: Mapped[str] = mapped_column(String(40))
    nom: Mapped[str] = mapped_column(String(200))
    pays: Mapped[str | None] = mapped_column(String(80))
    telephone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(200))
    adresse: Mapped[str | None] = mapped_column(String(300))
    conditions_paiement: Mapped[str | None] = mapped_column(String(300))
    delai_livraison_jours: Mapped[int | None] = mapped_column(Integer)
    actif: Mapped[bool] = _actif()
    cree_le: Mapped[datetime] = _horodatage()
