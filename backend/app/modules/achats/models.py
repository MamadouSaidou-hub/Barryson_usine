"""Tables du module achats (M03) : de la commande au fournisseur jusqu'a l'entree en stock controlee.

Circuit : commande preparee (brouillon) -> soumise au DG -> validee -> passee au fournisseur ->
marchandise arrivee (reception) -> controle de conformite -> entree en stock des seules quantites acceptees.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, get_args

from sqlalchemy import (
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
from app.modules.production import models as _production  # noqa: F401  (ordre de creation des tables)
from app.modules.stock.models import FINITIONS

StatutCommande = Literal[
    "brouillon",
    "soumise",
    "validee",
    "refusee",
    "commandee",
    "partiellement_recue",
    "recue",
    "cloturee",
    "annulee",
]
StatutReception = Literal["en_controle", "acceptee", "acceptee_avec_reserves", "refusee"]
Devise = Literal["USD", "EUR", "CNY", "GNF"]

STATUTS_COMMANDE: tuple[str, ...] = get_args(StatutCommande)
STATUTS_RECEPTION: tuple[str, ...] = get_args(StatutReception)
DEVISES: tuple[str, ...] = get_args(Devise)
# Une commande dans ces etats attend encore de la marchandise.
ETATS_ATTENTE_MARCHANDISE = ("commandee", "partiellement_recue")


def _liste(valeurs: tuple) -> str:
    return ", ".join(repr(v) for v in valeurs)


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _horodatage() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=maintenant, server_default=func.now())


class CommandeAchat(Audite, Base):
    __tablename__ = "commandes_achat"
    __table_args__ = (
        UniqueConstraint("entreprise_id", "numero"),
        CheckConstraint(f"statut IN ({_liste(STATUTS_COMMANDE)})", name="statut_connu"),
        CheckConstraint(f"devise IN ({_liste(DEVISES)})", name="devise_connue"),
        # Separation initiateur / valideur imposee par la base elle-meme.
        CheckConstraint("valide_par IS NULL OR valide_par <> cree_par", name="valideur_distinct"),
        CheckConstraint(
            "statut NOT IN ('refusee', 'annulee', 'cloturee') OR motif_decision IS NOT NULL",
            name="decision_motivee",
        ),
        Index("ix_commandes_achat_entreprise_statut", "entreprise_id", "statut"),
    )

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entreprises.id"), index=True)
    numero: Mapped[str] = mapped_column(String(30))
    fournisseur_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fournisseurs.id"))
    statut: Mapped[str] = mapped_column(String(25), default="brouillon", server_default="brouillon")
    devise: Mapped[str] = mapped_column(String(3))
    date_arrivee_prevue: Mapped[date | None] = mapped_column(Date)
    # Numero de proforma / bon de commande cote fournisseur.
    reference_fournisseur: Mapped[str | None] = mapped_column(String(80))
    commentaire: Mapped[str | None] = mapped_column(String(500))
    cree_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    cree_le: Mapped[datetime] = _horodatage()
    valide_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    valide_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    commandee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Motif d'un refus, d'une annulation ou du solde d'une commande partiellement livree.
    motif_decision: Mapped[str | None] = mapped_column(String(500))


class LigneCommandeAchat(Base):
    """Figee des la soumission : un declencheur en base refuse toute modification hors brouillon."""

    __tablename__ = "lignes_commande_achat"
    __table_args__ = (
        UniqueConstraint("commande_id", "rang"),
        UniqueConstraint(
            "commande_id",
            "article_id",
            "couleur_finition",
            name="uq_lignes_commande_achat_article",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("quantite_commandee > 0", name="quantite_positive"),
        CheckConstraint("prix_unitaire IS NULL OR prix_unitaire >= 0", name="prix_positif"),
        CheckConstraint(
            f"couleur_finition IS NULL OR couleur_finition IN ({_liste(FINITIONS)})", name="finition_connue"
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    commande_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("commandes_achat.id"), index=True)
    rang: Mapped[int] = mapped_column(Integer)
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id"))
    quantite_commandee: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    # Dans la devise de la commande ; facultatif (les prix peuvent n'etre connus qu'a la facture).
    prix_unitaire: Mapped[Decimal | None] = mapped_column(Numeric(16, 4))
    # Pour les bobines : finition attendue, comparee a la packing list a la reception.
    couleur_finition: Mapped[str | None] = mapped_column(String(30))


class TransitionCommande(Base):
    """Registre en ajout seul des changements d'etat d'une commande."""

    __tablename__ = "transitions_commande_achat"

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entreprises.id"), index=True)
    commande_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("commandes_achat.id"), index=True)
    de_statut: Mapped[str | None] = mapped_column(String(25))
    vers_statut: Mapped[str] = mapped_column(String(25))
    acteur_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    motif: Mapped[str | None] = mapped_column(Text)
    cree_le: Mapped[datetime] = _horodatage()


class ReceptionAchat(Audite, Base):
    """Une livraison (souvent un conteneur) arrivee pour une commande, en attente de controle."""

    __tablename__ = "receptions_achat"
    __table_args__ = (
        UniqueConstraint("entreprise_id", "numero"),
        CheckConstraint(f"statut IN ({_liste(STATUTS_RECEPTION)})", name="statut_connu"),
        CheckConstraint("(statut = 'en_controle') = (controle_par IS NULL)", name="controle_coherent"),
        Index("ix_receptions_achat_commande", "commande_id"),
    )

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entreprises.id"), index=True)
    numero: Mapped[str] = mapped_column(String(30))
    commande_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("commandes_achat.id"))
    # Packing list rattachee (conteneur de bobines) : une seule reception par import.
    import_colisage_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("imports_colisage.id"), unique=True
    )
    conteneur_reference: Mapped[str | None] = mapped_column(String(60))
    numero_facture: Mapped[str | None] = mapped_column(String(60))
    date_arrivee: Mapped[date] = mapped_column(Date)
    statut: Mapped[str] = mapped_column(String(25), default="en_controle", server_default="en_controle")
    commentaire: Mapped[str | None] = mapped_column(String(500))
    cree_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    cree_le: Mapped[datetime] = _horodatage()
    # Controle de conformite : documentaire (facture, packing list...) puis quantitatif.
    controle_documentaire_ok: Mapped[bool | None] = mapped_column()
    controle_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    controle_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    commentaire_controle: Mapped[str | None] = mapped_column(String(500))
    lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lots.id"))


class LigneReception(Base):
    __tablename__ = "lignes_reception_achat"
    __table_args__ = (
        UniqueConstraint("reception_id", "ligne_commande_id"),
        CheckConstraint("quantite_recue > 0", name="recue_positive"),
        CheckConstraint(
            "quantite_acceptee IS NULL OR (quantite_acceptee >= 0 AND quantite_acceptee <= quantite_recue)",
            name="acceptee_bornee",
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    reception_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("receptions_achat.id"), index=True)
    ligne_commande_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lignes_commande_achat.id"))
    quantite_recue: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    observation: Mapped[str | None] = mapped_column(String(300))
    # Renseignes au controle.
    quantite_acceptee: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    motif_ecart: Mapped[str | None] = mapped_column(String(300))
    # Numeros des bobines refusees (colis endommage...) : elles n'entrent pas en stock.
    bobines_refusees: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
