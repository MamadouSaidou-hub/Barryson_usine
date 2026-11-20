"""Acces a la base de donnees : moteur, session et classe de base des modeles."""

from collections.abc import Generator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# pool_pre_ping : verifie la connexion avant usage, indispensable quand le
# reseau est instable (coupures frequentes a Conakry).
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Classe de base de tous les modeles ORM du projet."""

    # Noms de contraintes deterministes : les migrations autogenerees restent
    # stables et une contrainte se retrouve par son nom en cas d'erreur.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def get_db() -> Generator[Session, None, None]:
    """Dependance FastAPI : fournit une session par requete, toujours refermee."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
