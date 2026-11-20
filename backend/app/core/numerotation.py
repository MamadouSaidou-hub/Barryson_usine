"""Numerotation lisible des documents (OF-2026-00001), par entreprise et par annee.

Un seul `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` : l'increment est
atomique, deux requetes simultanees ne peuvent jamais obtenir le meme numero,
sans verrou explicite a gerer.
"""

import uuid
from datetime import date

from sqlalchemy import ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base


class Compteur(Base):
    __tablename__ = "compteurs_numerotation"

    entreprise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entreprises.id"), primary_key=True)
    cle: Mapped[str] = mapped_column(String(20), primary_key=True)
    annee: Mapped[int] = mapped_column(Integer, primary_key=True)
    valeur: Mapped[int] = mapped_column(Integer)


def prochain_numero(db: Session, entreprise_id: uuid.UUID, cle: str, *, largeur: int = 5) -> str:
    annee = date.today().year
    valeur = db.execute(
        text("INSERT INTO compteurs_numerotation (entreprise_id, cle, annee, valeur) "
             "VALUES (:e, :c, :a, 1) "
             "ON CONFLICT (entreprise_id, cle, annee) DO UPDATE "
             "SET valeur = compteurs_numerotation.valeur + 1 RETURNING valeur"),
        {"e": entreprise_id, "c": cle, "a": annee},
    ).scalar_one()
    return f"{cle}-{annee}-{valeur:0{largeur}d}"
