"""Administration des comptes : droits serveur, auto-protection, isolation par entreprise."""

from sqlalchemy import select

from app.core.audit import JournalAudit
from app.modules.identite.models import Entreprise, SessionUtilisateur
from tests.conftest import se_connecter


def _admin(client, creer_compte) -> dict:
    creer_compte("administrateur")
    return {"X-CSRF-Token": se_connecter(client, "administrateur.test")}


def test_creation_d_un_compte_avec_mot_de_passe_temporaire(client, creer_compte, db):
    entetes = _admin(client, creer_compte)
    donnees = {"identifiant": "m.camara", "nom": "Mariama Camara", "role": "chef_production"}
    reponse = client.post("/api/utilisateurs", headers=entetes, json=donnees)
    assert reponse.status_code == 201
    corps = reponse.json()
    assert corps["utilisateur"]["doit_changer_mot_de_passe"] is True
    assert len(corps["mot_de_passe_temporaire"]) >= 16
    assert "hash" not in str(corps)

    entree = db.scalar(select(JournalAudit).where(JournalAudit.action == "utilisateurs.creation",
                                                  JournalAudit.cible_id == corps["utilisateur"]["id"]))
    assert entree.apres["role"] == "chef_production"
    assert entree.apres["mot_de_passe_hash"] == "***"
    assert entree.acteur_id is not None


def test_seul_l_administrateur_gere_les_comptes(client, creer_compte, db):
    creer_compte("dg")
    csrf = se_connecter(client, "dg.test")
    reponse = client.post("/api/utilisateurs", headers={"X-CSRF-Token": csrf},
                          json={"identifiant": "pirate", "nom": "Compte Pirate", "role": "administrateur"})
    assert reponse.status_code == 403
    refus = db.scalar(select(JournalAudit).where(JournalAudit.action == "acces.refuse"))
    assert refus.apres["permission"] == "utilisateurs.gerer"


def test_tous_les_roles_non_admin_sont_refuses(client, creer_compte):
    roles = ("chef_production", "directeur_commercial", "responsable_stock", "comptable", "responsable_rh")
    for role in roles:
        creer_compte(role)
        csrf = se_connecter(client, f"{role.replace('_', '-')}.test")
        assert client.get("/api/utilisateurs").status_code == 403, role
        assert client.post("/api/utilisateurs", headers={"X-CSRF-Token": csrf},
                           json={"identifiant": "x.y.z", "nom": "X Y", "role": "dg"}).status_code == 403, role


def test_sans_session_401(client):
    assert client.get("/api/utilisateurs").status_code == 401


def test_identifiant_en_double_409(client, creer_compte):
    entetes = _admin(client, creer_compte)
    donnees = {"identifiant": "m.camara", "nom": "Mariama Camara", "role": "comptable"}
    assert client.post("/api/utilisateurs", headers=entetes, json=donnees).status_code == 201
    assert client.post("/api/utilisateurs", headers=entetes, json=donnees).status_code == 409


def test_entrees_invalides_ou_champs_en_trop_refuses(client, creer_compte):
    entetes = _admin(client, creer_compte)
    for donnees in (
        {"identifiant": "m.camara", "nom": "Mariama", "role": "commercial"},
        {"identifiant": "M Camara!", "nom": "Mariama", "role": "comptable"},
        {"identifiant": "m.camara", "nom": "Mariama", "role": "comptable", "mot_de_passe_hash": "x"},
        {"identifiant": "m.camara", "nom": "Mariama", "role": "comptable", "actif": False},
    ):
        assert client.post("/api/utilisateurs", headers=entetes, json=donnees).status_code == 422, donnees


def test_l_administrateur_ne_peut_ni_se_promouvoir_ni_se_desactiver(client, creer_compte):
    entetes = _admin(client, creer_compte)
    moi = client.get("/api/auth/moi").json()["utilisateur"]["id"]
    assert client.patch(f"/api/utilisateurs/{moi}", headers=entetes, json={"role": "dg"}).status_code == 403
    assert client.patch(f"/api/utilisateurs/{moi}", headers=entetes, json={"actif": False}).status_code == 403
    assert client.post(f"/api/utilisateurs/{moi}/reinitialiser-mot-de-passe",
                       headers=entetes).status_code == 403
    renommage = client.patch(f"/api/utilisateurs/{moi}", headers=entetes, json={"nom": "Nouveau Nom"})
    assert renommage.status_code == 200


def test_changement_de_role_coupe_les_sessions_immediatement(client, creer_compte, db):
    cible = creer_compte("chef_production")
    from app.modules.identite import service
    service.connecter(db, "chef-production.test", "Cheval-Correct-Agrafe-91", ip="10.0.0.2", user_agent=None)
    entetes = _admin(client, creer_compte)
    reponse = client.patch(f"/api/utilisateurs/{cible.id}", headers=entetes, json={"role": "comptable"})
    assert reponse.status_code == 200
    actives = db.scalars(select(SessionUtilisateur).where(SessionUtilisateur.utilisateur_id == cible.id,
                                                          SessionUtilisateur.revoquee_le.is_(None))).all()
    assert actives == []
    modif = db.scalar(select(JournalAudit).where(JournalAudit.action == "utilisateurs.modification"))
    assert modif.avant == {"role": "chef_production"} and modif.apres == {"role": "comptable"}


def test_reinitialisation_du_mot_de_passe(client, creer_compte):
    cible = creer_compte("comptable")
    entetes = _admin(client, creer_compte)
    reponse = client.post(f"/api/utilisateurs/{cible.id}/reinitialiser-mot-de-passe", headers=entetes)
    assert reponse.status_code == 200
    temporaire = reponse.json()["mot_de_passe_temporaire"]
    client.cookies.clear()
    corps = client.post("/api/auth/connexion",
                        json={"identifiant": "comptable.test", "mot_de_passe": temporaire}).json()
    assert corps["utilisateur"]["doit_changer_mot_de_passe"] is True


def test_isolation_entre_entreprises(client, creer_compte, db):
    autre = Entreprise(nom="Autre usine")
    db.add(autre)
    db.flush()
    etranger = creer_compte("dg", "dg.autre", entreprise_id=autre.id)
    entetes = _admin(client, creer_compte)
    identifiants = [u["identifiant"] for u in client.get("/api/utilisateurs").json()]
    assert "dg.autre" not in identifiants
    # Introuvable plutot qu'interdit : on ne confirme meme pas l'existence du compte.
    assert client.patch(f"/api/utilisateurs/{etranger.id}", headers=entetes,
                        json={"actif": False}).status_code == 404


def test_identifiant_de_compte_non_devinable(client, creer_compte):
    entetes = _admin(client, creer_compte)
    assert client.patch("/api/utilisateurs/1", headers=entetes, json={"nom": "Xx Yy"}).status_code == 422
