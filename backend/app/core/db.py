"""Acces a la base de donnees : moteur, session et classe de base des modeles."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# pool_pre_ping : verifie la connexion avant usage, indispensable quand le
# reseau est instable (coupures frequentes a Conakry).
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Classe de base de tous les modeles ORM du projet."""


def get_db() -> Generator[Session, None, None]:
    """Dependance FastAPI : fournit une session par requete, toujours refermee."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
