"""Fixtures communes.

Chaque test tourne dans une transaction annulee a la fin : les `commit()` du
code applicatif deviennent des points de sauvegarde, rien n'est conserve.
"""

from collections.abc import Callable, Iterator
from functools import lru_cache

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.audit import maintenant
from app.core.config import get_settings
from app.core.db import engine, get_db
from app.main import app
from app.modules.identite import mots_de_passe
from app.modules.identite.models import Entreprise, Utilisateur

MOT_DE_PASSE = "Cheval-Correct-Agrafe-91"


@lru_cache(maxsize=1)
def hash_de_test() -> str:
    return mots_de_passe.hacher(MOT_DE_PASSE)


def _session_annulee(moteur) -> Iterator[Session]:
    connexion = moteur.connect()
    transaction = connexion.begin()
    session = Session(bind=connexion, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connexion.close()


@pytest.fixture
def db() -> Iterator[Session]:
    """Session avec le compte applicatif a moindre privilege, comme l'API en production."""
    yield from _session_annulee(engine)


@pytest.fixture(scope="session")
def moteur_proprietaire():
    moteur = create_engine(get_settings().database_url_proprietaire)
    yield moteur
    moteur.dispose()


@pytest.fixture
def db_proprietaire(moteur_proprietaire) -> Iterator[Session]:
    """Session du proprietaire du schema : simule un attaquant ayant obtenu ces acces."""
    yield from _session_annulee(moteur_proprietaire)


@pytest.fixture(autouse=True)
def _sans_double_facteur_par_defaut(monkeypatch: pytest.MonkeyPatch) -> None:
    # Les tests dedies (test_double_facteur.py) le reactivent ; les autres testent autre chose.
    monkeypatch.setattr(get_settings(), "roles_double_facteur", [])


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    def _get_db() -> Iterator[Session]:
        # La session est partagee entre requetes d'un meme test : on repart d'un contexte vierge.
        for cle in ("acteur_id", "entreprise_id", "ip"):
            db.info.pop(cle, None)
        yield db

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def reglages():
    """Reglages partages ; a modifier via monkeypatch.setattr pour qu'ils soient restaures."""
    return get_settings()


@pytest.fixture
def entreprise(db: Session) -> Entreprise:
    e = Entreprise(nom="Usine de test")
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def creer_compte(db: Session, entreprise: Entreprise) -> Callable[..., Utilisateur]:
    def _creer(role: str, identifiant: str | None = None, *, doit_changer: bool = False,
               actif: bool = True, entreprise_id=None) -> Utilisateur:
        instant = maintenant()
        u = Utilisateur(
            entreprise_id=entreprise_id or entreprise.id,
            identifiant=identifiant or f"{role.replace('_', '-')}.test",
            nom=f"Personne {role}",
            role=role,
            mot_de_passe_hash=hash_de_test(),
            actif=actif,
            doit_changer_mot_de_passe=doit_changer,
            mot_de_passe_modifie_le=instant,
            cree_le=instant,
        )
        db.add(u)
        db.commit()
        return u

    return _creer


def se_connecter(client: TestClient, identifiant: str, mot_de_passe: str = MOT_DE_PASSE) -> str:
    """Ouvre une session et renvoie le jeton CSRF a mettre dans les requetes d'ecriture."""
    donnees = {"identifiant": identifiant, "mot_de_passe": mot_de_passe}
    reponse = client.post("/api/auth/connexion", json=donnees)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()["csrf_token"]
