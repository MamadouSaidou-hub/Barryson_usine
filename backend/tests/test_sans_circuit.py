"""Phase de developpement : sans circuit de validation, celui qui saisit peut avancer seul.

Le reglage VALIDATIONS_ACTIVES=false n'existe qu'en developpement : la configuration le refuse ailleurs.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.identite.permissions import a_la_permission, permissions_du_role
from tests.test_achats import _commande, base  # noqa: F401  (fixtures et jeux de donnees des achats)


def test_les_validations_s_arretent_aux_droits_de_saisie(sans_circuit):
    assert a_la_permission("responsable_stock", "achats.valider")
    assert a_la_permission("chef_production", "production.valider")
    assert a_la_permission("chef_production", "doctor_rewinder.valider")
    assert "production.cloturer" in permissions_du_role("chef_production")
    # Ni plus, ni moins que ce qu'on saisit : le comptable ne gagne rien, le chef ne touche pas aux achats.
    assert not a_la_permission("comptable", "achats.valider")
    assert not a_la_permission("chef_production", "achats.valider")


def test_circuit_actif_rien_ne_change():
    assert not a_la_permission("responsable_stock", "achats.valider")
    assert not a_la_permission("chef_production", "production.valider")


def test_une_commande_se_passe_au_fournisseur_sans_validation(sans_circuit, client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    cree = client.post("/api/commandes-achat", headers=entetes, json=_commande(base))
    assert cree.status_code == 201, cree.text
    commandee = client.post(f"/api/commandes-achat/{cree.json()['id']}/commander", headers=entetes)
    assert commandee.status_code == 200, commandee.text
    assert commandee.json()["statut"] == "commandee"


def test_une_commande_exige_toujours_sa_validation_quand_le_circuit_est_actif(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    cree = client.post("/api/commandes-achat", headers=entetes, json=_commande(base))
    refus = client.post(f"/api/commandes-achat/{cree.json()['id']}/commander", headers=entetes)
    assert refus.status_code == 409


def test_une_entree_et_une_sortie_comptent_tout_de_suite(sans_circuit, client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    tube = str(base["tube"].id)

    def solde() -> float:
        lignes = client.get("/api/stock/soldes", headers=entetes, params={"article_id": tube}).json()
        return lignes[0]["physique"] if lignes else 0

    entree = client.post("/api/stock/mouvements", headers=entetes, json={
        "type": "ajustement", "sens": "plus", "article_id": tube, "quantite": "300", "motif": "Comptage : il y en a plus"})
    assert entree.status_code == 201, entree.text
    assert entree.json()["type"] == "entree_manuelle" and entree.json()["statut"] == "valide"
    assert solde() == 300
    sortie = client.post("/api/stock/mouvements", headers=entetes, json={
        "type": "sortie_exceptionnelle", "article_id": tube, "quantite": "120", "motif": "Casse ou perte"})
    assert sortie.status_code == 201, sortie.text
    assert sortie.json()["type"] == "sortie_manuelle" and solde() == 180


def test_la_session_dit_si_les_validations_sont_actives(sans_circuit, client, en_tant_que):
    assert client.get("/api/auth/moi", headers=en_tant_que("dg")).json()["validations_actives"] is False


def test_la_configuration_refuse_de_couper_les_validations_hors_developpement():
    with pytest.raises(ValidationError, match="VALIDATIONS_ACTIVES"):
        Settings(environment="production", validations_actives=False, secret_key="x" * 40,
                 postgres_password="un-mot-de-passe-solide-1", postgres_app_password="autre-mot-de-passe-solide-2",
                 hotes_autorises=["erp.exemple.com"])
