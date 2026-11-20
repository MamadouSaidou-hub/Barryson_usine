"""Tables du module production (M06).

L'ordre de fabrication suit une machine a etats stricte (pas de saut). Chaque
transition est inscrite dans un registre en ajout seul : on sait toujours qui
a fait passer l'ordre d'un etat a l'autre, et quand.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal, get_args

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.audit import Audite, maintenant
from app.core.db import Base
from app.modules.stock import models as _stock  # noqa: F401  (cles etrangeres vers les mouvements)

StatutOF = Literal["brouillon", "soumis", "matieres_validees", "en_cours", "resultat_saisi",
                   "resultat_valide", "cloture", "annule"]
STATUTS: tuple[str, ...] = get_args(StatutOF)
STATUTS_TERMINAUX = ("cloture", "annule")


def _liste(valeurs: tuple) -> str:
    return ", ".join(repr(v) for v in valeurs)


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _horodatage() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=maintenant, server_default=func.now())


class OrdreFabrication(Audite, Base):
    __tablename__ = "ordres_fabrication"
    __table_args__ = (
        UniqueConstraint("entreprise_id", "numero"),
        CheckConstraint(f"statut IN ({_liste(STATUTS)})", name="statut_connu"),
        CheckConstraint("metrage_engage > 0", name="metrage_positif"),
        CheckConstraint("(statut = 'annule') = (motif_annulation IS NOT NULL)", name="annulation_motivee"),
        # Une bobine ne peut servir qu'a un seul ordre non termine a la fois, garanti par la base.
        Index("uq_ordres_fabrication_bobine_active", "bobine_id", unique=True,
              postgresql_where=text("statut NOT IN ('cloture', 'annule')")),
        Index("ix_ordres_fabrication_entreprise_statut", "entreprise_id", "statut"),
    )

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entreprises.id"), index=True)
    numero: Mapped[str] = mapped_column(String(30))
    statut: Mapped[str] = mapped_column(String(20), default="brouillon", server_default="brouillon")
    modele_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modeles_ruban.id"))
    # Version de la fiche en vigueur a la creation : les previsions restent explicables.
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("versions_modeles_ruban.id"))
    bobine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bobines.id"))
    metrage_engage: Mapped[Decimal] = mapped_column(Numeric(11, 2))
    commentaire: Mapped[str | None] = mapped_column(String(500))

    # Prevision figee a la soumission (§6.3).
    tours_prevus: Mapped[int | None] = mapped_column(Integer)
    pieces_theoriques: Mapped[int | None] = mapped_column(Integer)
    cartons_prevus: Mapped[int | None] = mapped_column(Integer)
    pieces_restantes_prevues: Mapped[int | None] = mapped_column(Integer)
    # Avertissements non bloquants (stock de tubes insuffisant, metrage cumule, ...).
    alertes: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")

    # Resultat reel saisi depuis le rapport papier de l'operateur (§6.4).
    tours_totaux: Mapped[int | None] = mapped_column(Integer)
    tours_defectueux: Mapped[int | None] = mapped_column(Integer)
    pieces_defectueuses_supplementaires: Mapped[int | None] = mapped_column(Integer)
    quantite_doctor_rewinder: Mapped[int | None] = mapped_column(Integer)
    pertes_definitives: Mapped[int | None] = mapped_column(Integer)
    bobine_epuisee: Mapped[bool | None] = mapped_column(Boolean)
    resultat_saisi_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    resultat_saisi_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Resultat calcule, fige a la validation avec la version de la formule utilisee.
    pieces_brutes: Mapped[int | None] = mapped_column(Integer)
    pieces_non_conformes: Mapped[int | None] = mapped_column(Integer)
    pieces_conformes: Mapped[int | None] = mapped_column(Integer)
    cartons_obtenus: Mapped[int | None] = mapped_column(Integer)
    pieces_restantes: Mapped[int | None] = mapped_column(Integer)
    ecart_pieces: Mapped[int | None] = mapped_column(Integer)
    ecart_pourcentage: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    rendement: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    version_formule: Mapped[str | None] = mapped_column(String(30))

    motif_annulation: Mapped[str | None] = mapped_column(String(500))
    cree_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    cree_le: Mapped[datetime] = _horodatage()


class TransitionOF(Base):
    """Registre en ajout seul des changements d'etat d'un ordre de fabrication."""

    __tablename__ = "transitions_ordre_fabrication"

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entreprises.id"), index=True)
    ordre_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ordres_fabrication.id"), index=True)
    de_statut: Mapped[str | None] = mapped_column(String(20))
    vers_statut: Mapped[str] = mapped_column(String(20))
    acteur_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    motif: Mapped[str | None] = mapped_column(Text)
    cree_le: Mapped[datetime] = _horodatage()


class UtilisationBobine(Base):
    """Une seance de fabrication sur une bobine : une bobine peut servir a plusieurs ordres."""

    __tablename__ = "bobine_utilisations"

    id: Mapped[uuid.UUID] = _id()
    entreprise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entreprises.id"), index=True)
    bobine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bobines.id"), index=True)
    ordre_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ordres_fabrication.id"), unique=True)
    metrage_engage: Mapped[Decimal] = mapped_column(Numeric(11, 2))
    cree_le: Mapped[datetime] = _horodatage()
