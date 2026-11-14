"""Sprint 1 : l'application demarre et repond."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_liveness_repond_sans_base_de_donnees():
    reponse = client.get("/healthz")
    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "ok"


def test_readiness_annonce_l_etat_de_la_base():
    """La sonde repond toujours : 200 si la base est joignable, 503 sinon."""
    reponse = client.get("/readyz")
    assert reponse.status_code in (200, 503)
    assert "base_de_donnees" in reponse.json()
