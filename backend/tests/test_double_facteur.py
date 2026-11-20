"""Double authentification (TOTP) pour le DG et l'administrateur."""

import base64
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.audit import JournalAudit, maintenant
from app.core.config import get_settings
from app.modules.identite import double_facteur, service
from tests.conftest import MOT_DE_PASSE

SECRET_RFC = base64.b32encode(b"12345678901234567890").decode()


@pytest.fixture(autouse=True)
def _double_facteur_actif(monkeypatch):
    monkeypatch.setattr(get_settings(), "roles_double_facteur", ["dg", "administrateur"])


def _connexion(client, identifiant, code=None):
    donnees = {"identifiant": identifiant, "mot_de_passe": MOT_DE_PASSE}
    if code:
        donnees["code"] = code
    return client.post("/api/auth/connexion", json=donnees)


def _code_actuel(secret: str, decalage: int = 0) -> str:
    return double_facteur.code_pour_pas(secret, double_facteur.pas_de_temps(maintenant()) + decalage)


def _activer(client, creer_compte, role="dg") -> tuple[str, str]:
    """Cree un compte, le connecte, configure le second facteur. Renvoie (secret, csrf)."""
    creer_compte(role)
    reponse = _connexion(client, f"{role}.test")
    assert reponse.json()["double_facteur_a_configurer"] is True
    csrf = {"X-CSRF-Token": reponse.json()["csrf_token"]}
    secret = client.post("/api/auth/double-facteur/initialiser", headers=csrf).json()["secret"]
    activation = client.post("/api/auth/double-facteur/activer", headers=csrf,
                             json={"code": _code_actuel(secret)})
    assert activation.status_code == 200 and activation.json()["double_facteur_a_configurer"] is False
    return secret, csrf["X-CSRF-Token"]


# --- Algorithme --------------------------------------------------------------


def test_vecteur_officiel_rfc_6238():
    # RFC 6238 annexe B, SHA-1, T = 59 s -> 94287082 (8 chiffres), soit 287082 sur 6 chiffres.
    assert double_facteur.code_pour_pas(SECRET_RFC, 59 // 30) == "287082"
    assert double_facteur.code_pour_pas(SECRET_RFC, 1111111109 // 30) == "081804"


def test_tolerance_d_un_pas_et_anti_rejeu():
    instant = datetime(2026, 11, 20, 8, 0, 15, tzinfo=UTC)
    pas = double_facteur.pas_de_temps(instant)
    precedent = double_facteur.code_pour_pas(SECRET_RFC, pas - 1)
    assert double_facteur.verifier_code(SECRET_RFC, precedent, instant, None) == pas - 1
    assert double_facteur.verifier_code(SECRET_RFC, precedent, instant, pas - 1) is None
    trop_vieux = double_facteur.code_pour_pas(SECRET_RFC, pas - 3)
    assert double_facteur.verifier_code(SECRET_RFC, trop_vieux, instant, None) is None
    assert double_facteur.verifier_code(SECRET_RFC, "12a456", instant, None) is None


def test_secret_chiffre_et_lie_au_compte():
    chiffre = double_facteur.chiffrer(SECRET_RFC, "compte-a")
    assert SECRET_RFC not in chiffre
    assert double_facteur.dechiffrer(chiffre, "compte-a") == SECRET_RFC
    assert double_facteur.dechiffrer(chiffre, "compte-b") is None
    altere = base64.b64encode(base64.b64decode(chiffre)[:-1] + b"\x00").decode()
    assert double_facteur.dechiffrer(altere, "compte-a") is None


# --- Parcours ----------------------------------------------------------------


def test_sans_second_facteur_configure_le_dg_ne_peut_rien_faire(client, creer_compte):
    creer_compte("dg")
    reponse = _connexion(client, "dg.test")
    assert reponse.status_code == 200 and reponse.json()["double_facteur_a_configurer"] is True
    assert client.get("/api/audit").status_code == 403
    assert client.get("/api/auth/moi").status_code == 200


def test_activation_puis_connexion_en_deux_etapes(client, creer_compte, db):
    secret, _ = _activer(client, creer_compte)
    client.cookies.clear()

    etape1 = _connexion(client, "dg.test")
    assert etape1.status_code == 401 and etape1.json()["code_requis"] is True
    assert "set-cookie" not in etape1.headers

    etape2 = _connexion(client, "dg.test", _code_actuel(secret, +1))
    assert etape2.status_code == 200
    assert client.get("/api/audit").status_code == 200

    stocke = db.scalar(select(service.Utilisateur.totp_secret_chiffre).where(
        service.Utilisateur.identifiant == "dg.test"))
    assert secret not in stocke


def test_un_code_rejoue_est_refuse(client, creer_compte):
    secret, _ = _activer(client, creer_compte)
    client.cookies.clear()
    code = _code_actuel(secret, +1)
    assert _connexion(client, "dg.test", code).status_code == 200
    client.cookies.clear()
    assert _connexion(client, "dg.test", code).status_code == 401


def test_les_mauvais_codes_verrouillent_le_compte(client, creer_compte, reglages, monkeypatch):
    monkeypatch.setattr(reglages, "connexion_seuil_echecs_compte", 3)
    secret, _ = _activer(client, creer_compte)
    client.cookies.clear()
    faux = "000000" if _code_actuel(secret) != "000000" else "111111"
    for _ in range(3):
        assert _connexion(client, "dg.test", faux).status_code == 401
    # Meme avec le bon code, le compte est verrouille.
    assert _connexion(client, "dg.test", _code_actuel(secret, +1)).status_code == 401


def test_le_mot_de_passe_reste_verifie_avant_le_code(client, creer_compte):
    secret, _ = _activer(client, creer_compte)
    client.cookies.clear()
    donnees = {"identifiant": "dg.test", "mot_de_passe": "Faux-Faux-Faux-77",
               "code": _code_actuel(secret, +1)}
    reponse = client.post("/api/auth/connexion", json=donnees)
    assert reponse.status_code == 401 and "code_requis" not in reponse.json()


def test_on_ne_reconfigure_pas_un_second_facteur_actif_soi_meme(client, creer_compte):
    _, csrf = _activer(client, creer_compte)
    reponse = client.post("/api/auth/double-facteur/initialiser", headers={"X-CSRF-Token": csrf})
    assert reponse.status_code == 403


def test_reinitialisation_par_un_autre_administrateur(client, creer_compte, db):
    cible = creer_compte("dg")
    cible.double_facteur_actif = True
    cible.totp_secret_chiffre = double_facteur.chiffrer(SECRET_RFC, cible.id)
    db.commit()
    secret, csrf = _activer(client, creer_compte, role="administrateur")
    entetes = {"X-CSRF-Token": csrf}
    def reinitialiser(compte_id):
        return client.post(f"/api/utilisateurs/{compte_id}/reinitialiser-double-facteur", headers=entetes)

    assert reinitialiser(cible.id).status_code == 204
    assert cible.double_facteur_actif is False and cible.totp_secret_chiffre is None
    moi = client.get("/api/auth/moi").json()["utilisateur"]["id"]
    assert reinitialiser(moi).status_code == 403
    actions = set(db.scalars(select(JournalAudit.action)))
    assert "double_facteur.reinitialisation" in actions


def test_le_secret_n_apparait_jamais_dans_le_journal(client, creer_compte, db):
    secret, _ = _activer(client, creer_compte)
    for avant, apres in db.execute(select(JournalAudit.avant, JournalAudit.apres)):
        assert secret not in str(avant) + str(apres)


def test_le_role_n_exigeant_pas_le_second_facteur_n_est_pas_concerne(client, creer_compte):
    creer_compte("comptable")
    reponse = _connexion(client, "comptable.test")
    assert reponse.status_code == 200 and reponse.json()["double_facteur_a_configurer"] is False


def test_derive_d_horloge_au_dela_de_la_tolerance_refusee():
    instant = maintenant()
    il_y_a_5_minutes = double_facteur.pas_de_temps(instant - timedelta(minutes=5))
    code = double_facteur.code_pour_pas(SECRET_RFC, il_y_a_5_minutes)
    assert double_facteur.verifier_code(SECRET_RFC, code, instant, None) is None
