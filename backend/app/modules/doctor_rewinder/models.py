"""Table des encours Doctor Rewinder (M07).

Un encours n'est ni une perte definitive ni un produit fini disponible : c'est un etat intermediaire,
modelise par une table dediee (jamais par un statut sur le produit fini). Il nait a la cloture de l'ordre de
fabrication qui a envoye des pieces a rectifier, puis est traite (recupere / non recuperable) et valide.
"""

import uuid
from datetime import date, datetime
from typing import Literal, get_args

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.audit import Audite, maintenant
from app.core.db import Base
from app.modules.production import models as _production  # noqa: F401  (cles etrangeres vers l'ordre)

StatutEncours = Literal["en_cours", "a_valider", "traite"]
STATUTS: tuple[str, ...] = get_args(StatutEncours)


class EncoursDoctorRewinder(Audite, Base):
    __tablename__ = "encours_doctor_rewinder"
    __table_args__ = (
        CheckConstraint("statut IN ('en_cours', 'a_valider', 'traite')", name="statut_connu"),
        CheckConstraint("quantite_envoyee > 0", name="envoi_positif"),
        CheckConstraint("quantite_recuperee IS NULL OR quantite_recuperee >= 0", name="recuperee_positive"),
        CheckConstraint("quantite_non_recuperable IS NULL OR quantite_non_recuperable >= 0",
                        name="non_recuperable_positive"),
        # Tout ce qui est parti doit revenir : recupere ou perdu, jamais « disparu ».
        CheckConstraint("quantite_recuperee IS NULL OR quantite_non_recuperable IS NULL "
                        "OR quantite_recuperee + quantite_non_recuperable = quantite_envoyee",
                        name="envoi_integralement_traite"),
        CheckConstraint("(statut = 'en_cours') = (quantite_recuperee IS NULL)", name="traitement_coherent"),
        CheckConstraint("(statut = 'traite') = (valide_par IS NOT NULL)", name="validation_tracee"),
        Index("ix_encours_doctor_rewinder_entreprise_statut", "entreprise_id", "statut"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entreprise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entreprises.id"), index=True)
    # Un seul dossier par ordre : les pieces envoyees sont celles du resultat valide de cet ordre.
    ordre_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ordres_fabrication.id"), unique=True)
    bobine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bobines.id"), index=True)
    modele_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modeles_ruban.id"))
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id"))
    # Pieces par carton de la version de fiche de l'ordre, figees : le calcul reste explicable.
    pieces_par_carton: Mapped[int] = mapped_column(Integer)
    metrage: Mapped[float] = mapped_column(Numeric(11, 2))
    quantite_envoyee: Mapped[int] = mapped_column(Integer)
    date_envoi: Mapped[date] = mapped_column(Date)
    statut: Mapped[str] = mapped_column(String(12), default="en_cours", server_default="en_cours")

    quantite_recuperee: Mapped[int | None] = mapped_column(Integer)
    quantite_non_recuperable: Mapped[int | None] = mapped_column(Integer)
    commentaire: Mapped[str | None] = mapped_column(String(500))
    traite_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    date_traitement: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valide_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    valide_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Entree en stock des pieces recuperees, creee a la validation seulement.
    mouvement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("mouvements_stock.id"))
    # Pieces recuperees qui ne font pas un carton complet (article gere au carton) : visibles, pas perdues.
    pieces_reliquat: Mapped[int | None] = mapped_column(Integer)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=maintenant,
                                              server_default=func.now())
