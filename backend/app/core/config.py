"""Configuration de l'application, lue depuis les variables d'environnement.

Aucun secret n'est ecrit en dur : tout vient de l'environnement (fichier .env
en developpement, variables du serveur en production). Hors developpement,
l'application refuse de demarrer avec une valeur par defaut non securisee.
"""

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CLE_SECRETE_DEV = "developpement-uniquement-cle-non-secrete"
MOT_DE_PASSE_DB_DEV = "changeme"
MOT_DE_PASSE_APP_DEV = "changeme_app"
ROLES_DOUBLE_FACTEUR_MINIMUM = frozenset({"dg", "administrateur"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Barryson ERP"
    environment: str = "development"  # development | staging | production

    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_db: str = "barryson"
    # Proprietaire des tables : utilise uniquement par les migrations.
    postgres_user: str = "barryson"
    postgres_password: str = MOT_DE_PASSE_DB_DEV
    # Compte de l'API : lecture/ecriture, jamais proprietaire. Ne peut ni modifier
    # ni supprimer le journal d'audit, ni toucher aux triggers ou au schema.
    postgres_app_user: str = "barryson_app"
    postgres_app_password: str = MOT_DE_PASSE_APP_DEV

    # Requetes plus grosses refusees avant lecture (protection memoire).
    taille_max_requete_octets: int = 1_048_576
    # Niveau 1 du stock : prevu dans le schema, inactif tant que l'usine achete
    # tout sous forme de semi-finis (reunion usine du 2026-11-19).
    niveau_matiere_premiere_actif: bool = False
    # Roles tenus de valider un code a usage unique a la connexion.
    roles_double_facteur: list[str] = sorted(ROLES_DOUBLE_FACTEUR_MINIMUM)

    # Sert a deriver les jetons CSRF. 32 caracteres minimum hors developpement.
    secret_key: str = CLE_SECRETE_DEV
    # Noms d'hote acceptes (en-tete Host). Format JSON : '["erp.exemple.com"]'.
    hotes_autorises: list[str] = ["localhost", "127.0.0.1", "testserver"]

    session_inactivite_minutes: int = 120
    session_duree_max_heures: int = 12
    sessions_max_par_utilisateur: int = 5

    connexion_seuil_echecs_compte: int = 5
    connexion_verrouillage_minutes: int = 15
    connexion_max_echecs_ip: int = 20
    connexion_fenetre_ip_minutes: int = 15

    @model_validator(mode="after")
    def _refuser_valeurs_par_defaut_hors_dev(self) -> "Settings":
        if self.environment not in ("development", "staging", "production"):
            raise ValueError(f"ENVIRONMENT inconnu : {self.environment!r}")
        if self.environment == "development":
            return self
        erreurs = []
        if self.secret_key == CLE_SECRETE_DEV or len(self.secret_key) < 32:
            erreurs.append("SECRET_KEY doit etre definie (32 caracteres minimum)")
        if self.postgres_password == MOT_DE_PASSE_DB_DEV:
            erreurs.append("POSTGRES_PASSWORD ne doit pas garder sa valeur par defaut")
        if self.postgres_app_password in (MOT_DE_PASSE_APP_DEV, self.postgres_password):
            erreurs.append("POSTGRES_APP_PASSWORD doit etre propre au compte applicatif")
        if self.postgres_app_user == self.postgres_user:
            erreurs.append("POSTGRES_APP_USER doit differer du proprietaire des tables")
        if not ROLES_DOUBLE_FACTEUR_MINIMUM <= set(self.roles_double_facteur):
            erreurs.append("le second facteur est obligatoire pour le DG et l'administrateur")
        if "testserver" in self.hotes_autorises:
            erreurs.append("HOTES_AUTORISES doit lister les vrais noms de domaine")
        if erreurs:
            raise ValueError("Configuration non securisee : " + " ; ".join(erreurs))
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cookie_securise(self) -> bool:
        """Cookie transmis uniquement en HTTPS partout sauf en developpement local."""
        return self.environment != "development"

    @property
    def nom_cookie_session(self) -> str:
        # Le prefixe __Host- impose Secure, Path=/ et l'absence de Domain : le
        # cookie ne peut pas etre pose ni ecrase par un sous-domaine.
        return "__Host-barryson_session" if self.cookie_securise else "barryson_session"

    @property
    def docs_publiques(self) -> bool:
        """La description de l'API n'est publiee qu'en developpement local."""
        return self.environment == "development"

    def _url(self, utilisateur: str, mot_de_passe: str) -> str:
        # Encodage : tolere les caracteres speciaux dans les identifiants.
        # gssencmode=disable : libpq n'emploie jamais Kerberos/GSSAPI (inutile ici), ce qui
        # rend inatteignable le code des bibliotheques krb5 et leurs failles non corrigees.
        return (
            f"postgresql+psycopg://{quote_plus(utilisateur)}:{quote_plus(mot_de_passe)}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}?gssencmode=disable"
        )

    @property
    def database_url(self) -> str:
        """Connexion de l'API, avec le compte a moindre privilege."""
        return self._url(self.postgres_app_user, self.postgres_app_password)

    @property
    def database_url_proprietaire(self) -> str:
        """Connexion des migrations, avec le proprietaire du schema."""
        return self._url(self.postgres_user, self.postgres_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()
