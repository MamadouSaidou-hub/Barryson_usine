"""Configuration de l'application, lue depuis les variables d'environnement.

Aucun secret n'est ecrit en dur : tout vient de l'environnement (fichier .env
en developpement, variables du serveur en production).
"""

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Barryson ERP"
    environment: str = "development"  # development | staging | production

    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_user: str = "barryson"
    postgres_password: str = "changeme"
    postgres_db: str = "barryson"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def database_url(self) -> str:
        """URL SQLAlchemy. Le mot de passe est encode pour tolerer les caracteres speciaux."""
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql+psycopg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
