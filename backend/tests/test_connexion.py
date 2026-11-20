"""Connexion, sessions, CSRF, verrouillage : chemin normal et tentatives d'attaque."""

from datetime import timedelta

from sqlalchemy import func, select, text

from app.core.audit import maintenant
from app.modules.identite import service
from app.modules.identite.models import SessionUtilisateur, TentativeConnexion
from tests.conftest import MOT_DE_PASSE, se_connecter

COOKIE = "barryson_session"


def _connexion(client, identifiant, mot_de_passe=MOT_DE_PASSE):
    return client.post("/api/auth/connexion", json={"identifiant": identifiant, "mot_de_passe": mot_de_passe})


def test_connexion_pose_un_cookie_httponly_strict(client, creer_compte):
    creer_compte("chef_production")
    reponse = _connexion(client, "chef-production.test")
    assert reponse.status_code == 200
    cookie = reponse.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    corps = reponse.json()
    assert corps["utilisateur"]["role"] == "chef_production"
    assert "production.valider" in corps["permissions"]
    assert "mot_de_passe_hash" not in str(corps) and COOKIE not in str(corps)
    assert client.get("/api/auth/moi").json()["csrf_token"] == corps["csrf_token"]


def test_le_jeton_n_est_jamais_stocke_en_clair(client, creer_compte, db):
    creer_compte("dg")
    _connexion(client, "dg.test")
    jeton = client.cookies.get(COOKIE)
    stocke = db.scalar(select(SessionUtilisateur.jeton_hash))
    assert stocke == service.hacher_jeton(jeton) and stocke != jeton


def test_identifiant_inconnu_et_mauvais_mot_de_passe_sont_indiscernables(client, creer_compte):
    creer_compte("dg")
    inconnu = _connexion(client, "personne.inconnue")
    mauvais = _connexion(client, "dg.test", "Mauvais-Mot-De-Passe-1")
    assert inconnu.status_code == mauvais.status_code == 401
    assert inconnu.json() == mauvais.json()


def test_identifiant_insensible_a_la_casse_et_aux_espaces(client, creer_compte):
    creer_compte("dg")
    assert _connexion(client, "  DG.Test ").status_code == 200


def test_verrouillage_apres_echecs_meme_avec_le_bon_mot_de_passe(client, creer_compte, reglages, monkeypatch):
    monkeypatch.setattr(reglages, "connexion_seuil_echecs_compte", 3)
    u = creer_compte("comptable")
    for _ in range(3):
        assert _connexion(client, "comptable.test", "Mauvais-Mot-De-Passe-1").status_code == 401
    assert u.verrouille_jusqu_a is not None
    bloque = _connexion(client, "comptable.test")
    assert bloque.status_code == 401
    # Le message ne revele pas le verrouillage a un attaquant.
    assert bloque.json() == _connexion(client, "inconnu.total").json()


def test_le_verrouillage_expire(client, creer_compte, db):
    u = creer_compte("comptable")
    u.echecs_consecutifs, u.verrouille_jusqu_a = 9, maintenant() - timedelta(seconds=1)
    db.commit()
    assert _connexion(client, "comptable.test").status_code == 200
    assert u.echecs_consecutifs == 0 and u.verrouille_jusqu_a is None


def test_limite_par_adresse_ip_contre_le_balayage_de_comptes(client, reglages, monkeypatch):
    monkeypatch.setattr(reglages, "connexion_max_echecs_ip", 4)
    for i in range(4):
        assert _connexion(client, f"essai{i}", "Mauvais-Mot-De-Passe-1").status_code == 401
    assert _connexion(client, "essai-suivant", "Mauvais-Mot-De-Passe-1").status_code == 429


def test_compte_desactive_refuse(client, creer_compte):
    creer_compte("dg", actif=False)
    assert _connexion(client, "dg.test").status_code == 401


def test_chaque_tentative_est_enregistree(client, creer_compte, db):
    creer_compte("dg")
    _connexion(client, "dg.test", "Mauvais-Mot-De-Passe-1")
    _connexion(client, "dg.test")
    motifs = db.scalars(select(TentativeConnexion.motif).order_by(TentativeConnexion.id)).all()
    assert motifs == ["mot_de_passe_incorrect", "ok"]


def test_le_mot_de_passe_n_apparait_nulle_part_en_base(client, creer_compte, db):
    creer_compte("dg")
    _connexion(client, "dg.test", "Secret-Tape-Par-Erreur-42")
    _connexion(client, "dg.test")
    for table in ("journal_audit", "tentatives_connexion", "sessions", "utilisateurs"):
        contenu = db.execute(text(f"SELECT CAST(t AS text) FROM {table} t")).scalars().all()
        assert not any("Secret-Tape-Par-Erreur" in c or MOT_DE_PASSE in c for c in contenu), table


def test_requete_non_json_refusee_contre_le_csrf_de_connexion(client, creer_compte):
    creer_compte("dg")
    reponse = client.post("/api/auth/connexion", content='{"identifiant":"dg.test","mot_de_passe":"x"}',
                          headers={"Content-Type": "text/plain"})
    assert reponse.status_code == 422


def test_champ_inattendu_refuse(client):
    reponse = client.post("/api/auth/connexion",
                          json={"identifiant": "a", "mot_de_passe": "b", "role": "dg"})
    assert reponse.status_code == 422


def test_sans_session_401(client):
    assert client.get("/api/auth/moi").status_code == 401
    client.cookies.set(COOKIE, "jeton-forge-par-un-attaquant")
    assert client.get("/api/auth/moi").status_code == 401


def test_ecriture_sans_jeton_csrf_refusee(client, creer_compte):
    creer_compte("dg")
    se_connecter(client, "dg.test")
    assert client.post("/api/auth/deconnexion").status_code == 403
    assert client.post("/api/auth/deconnexion", headers={"X-CSRF-Token": "faux"}).status_code == 403
    assert client.get("/api/auth/moi").status_code == 200


def test_deconnexion_revoque_la_session_cote_serveur(client, creer_compte):
    creer_compte("dg")
    csrf = se_connecter(client, "dg.test")
    jeton = client.cookies.get(COOKIE)
    assert client.post("/api/auth/deconnexion", headers={"X-CSRF-Token": csrf}).status_code == 204
    # Rejouer le cookie vole apres deconnexion ne sert a rien.
    client.cookies.set(COOKIE, jeton)
    assert client.get("/api/auth/moi").status_code == 401


def test_session_expiree_par_inactivite(client, creer_compte, db, reglages):
    creer_compte("dg")
    se_connecter(client, "dg.test")
    session = db.scalar(select(SessionUtilisateur))
    session.derniere_activite_le = maintenant() - timedelta(minutes=reglages.session_inactivite_minutes + 1)
    db.commit()
    assert client.get("/api/auth/moi").status_code == 401


def test_session_expiree_par_duree_maximale(client, creer_compte, db):
    creer_compte("dg")
    se_connecter(client, "dg.test")
    session = db.scalar(select(SessionUtilisateur))
    session.expire_le = maintenant() - timedelta(seconds=1)
    db.commit()
    assert client.get("/api/auth/moi").status_code == 401


def test_nombre_de_sessions_simultanees_limite(db, creer_compte, reglages, monkeypatch):
    monkeypatch.setattr(reglages, "sessions_max_par_utilisateur", 3)
    u = creer_compte("dg")
    for _ in range(5):
        service.connecter(db, "dg.test", MOT_DE_PASSE, ip="10.0.0.1", user_agent=None)
    actives = db.scalar(select(func.count()).select_from(SessionUtilisateur).where(
        SessionUtilisateur.utilisateur_id == u.id, SessionUtilisateur.revoquee_le.is_(None)))
    assert actives == 3


def test_mot_de_passe_temporaire_bloque_tout_sauf_le_changement(client, creer_compte):
    creer_compte("administrateur", doit_changer=True)
    csrf = se_connecter(client, "administrateur.test")
    assert client.get("/api/auth/moi").json()["utilisateur"]["doit_changer_mot_de_passe"] is True
    assert client.get("/api/utilisateurs").status_code == 403

    ancien_jeton = client.cookies.get(COOKIE)
    reponse = client.post("/api/auth/mot-de-passe", headers={"X-CSRF-Token": csrf},
                          json={"actuel": MOT_DE_PASSE, "nouveau": "Grenier-Lampe-Orage-58"})
    assert reponse.status_code == 200
    assert client.cookies.get(COOKIE) != ancien_jeton
    assert client.get("/api/utilisateurs").status_code == 200

    # L'ancienne session est morte, l'ancien mot de passe aussi.
    client.cookies.set(COOKIE, ancien_jeton)
    assert client.get("/api/auth/moi").status_code == 401
    assert _connexion(client, "administrateur.test").status_code == 401
    assert _connexion(client, "administrateur.test", "Grenier-Lampe-Orage-58").status_code == 200


def test_session_volee_ne_permet_pas_de_deviner_le_mot_de_passe(client, creer_compte, reglages, monkeypatch):
    monkeypatch.setattr(reglages, "connexion_seuil_echecs_compte", 3)
    u = creer_compte("comptable")
    csrf = se_connecter(client, "comptable.test")
    essai = {"actuel": "Devinette-Numero-01", "nouveau": "Grenier-Lampe-Orage-58"}

    def tenter():
        return client.post("/api/auth/mot-de-passe", headers={"X-CSRF-Token": csrf}, json=essai).status_code

    assert [tenter(), tenter()] == [400, 400]
    # Au seuil : compte verrouille et session coupee.
    assert tenter() == 401
    assert client.get("/api/auth/moi").status_code == 401
    assert u.verrouille_jusqu_a is not None
    assert _connexion(client, "comptable.test").status_code == 401


def test_changement_refuse_si_mot_de_passe_actuel_faux_ou_faible(client, creer_compte):
    creer_compte("dg")
    csrf = se_connecter(client, "dg.test")
    entetes = {"X-CSRF-Token": csrf}
    faux = client.post("/api/auth/mot-de-passe", headers=entetes,
                       json={"actuel": "Pas-Le-Bon-Du-Tout-1", "nouveau": "Grenier-Lampe-Orage-58"})
    assert faux.status_code == 400
    faible = client.post("/api/auth/mot-de-passe", headers=entetes,
                         json={"actuel": MOT_DE_PASSE, "nouveau": "court"})
    assert faible.status_code == 400
    identique = client.post("/api/auth/mot-de-passe", headers=entetes,
                            json={"actuel": MOT_DE_PASSE, "nouveau": MOT_DE_PASSE})
    assert identique.status_code == 400
