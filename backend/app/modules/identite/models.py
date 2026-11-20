"""Tables du module identite."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.audit import Audite, maintenant
from app.core.db import Base
from app.modules.identite.permissions import ROLES

_ROLES_SQL = ", ".join(f"'{r}'" for r in ROLES)


def _horodatage(**kwargs) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=maintenant, server_default=func.now(), **kwargs)


class Entreprise(Audite, Base):
    __tablename__ = "entreprises"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(String(200), unique=True)
    cree_le: Mapped[datetime] = _horodatage()

    def entreprise_audit(self) -> uuid.UUID:
        return self.id


class Utilisateur(Audite, Base):
    __tablename__ = "utilisateurs"
    __table_args__ = (
        CheckConstraint(f"role IN ({_ROLES_SQL})", name="role_connu"),
        CheckConstraint("echecs_consecutifs >= 0", name="echecs_positifs"),
    )
    __audit_ignore__ = frozenset({"echecs_consecutifs", "verrouille_jusqu_a", "derniere_connexion_le",
                                  "totp_dernier_pas"})
    __audit_masque__ = frozenset({"mot_de_passe_hash", "totp_secret_chiffre"})

    # UUID plutot qu'entier : un identifiant ne se devine pas en incrementant.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entreprise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entreprises.id"), index=True)
    identifiant: Mapped[str] = mapped_column(String(50), unique=True)
    nom: Mapped[str] = mapped_column(String(150))
    role: Mapped[str] = mapped_column(String(30))
    mot_de_passe_hash: Mapped[str] = mapped_column(String(255))
    actif: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    doit_changer_mot_de_passe: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    echecs_consecutifs: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    verrouille_jusqu_a: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mot_de_passe_modifie_le: Mapped[datetime] = _horodatage()
    derniere_connexion_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cree_le: Mapped[datetime] = _horodatage()
    cree_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    # Double authentification : secret chiffre, jamais en clair.
    totp_secret_chiffre: Mapped[str | None] = mapped_column(String(200))
    double_facteur_actif: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    totp_dernier_pas: Mapped[int | None] = mapped_column(BigInteger)


class SessionUtilisateur(Base):
    """Session cote serveur : seul le hash du jeton est stocke, jamais le jeton."""

    __tablename__ = "sessions"
    __table_args__ = (Index("ix_sessions_utilisateur_actives", "utilisateur_id", "revoquee_le"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    utilisateur_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("utilisateurs.id"))
    entreprise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entreprises.id"))
    jeton_hash: Mapped[str] = mapped_column(String(64), unique=True)
    cree_le: Mapped[datetime] = _horodatage()
    derniere_activite_le: Mapped[datetime] = _horodatage()
    expire_le: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoquee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(255))


class TentativeConnexion(Base):
    """Registre en ajout seul des tentatives : sert au limiteur par adresse IP."""

    __tablename__ = "tentatives_connexion"
    __table_args__ = (Index("ix_tentatives_connexion_ip_horodatage", "ip", "horodatage"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    horodatage: Mapped[datetime] = _horodatage()
    identifiant: Mapped[str] = mapped_column(String(150))
    ip: Mapped[str | None] = mapped_column(String(45))
    reussie: Mapped[bool] = mapped_column(Boolean)
    motif: Mapped[str] = mapped_column(String(30))
