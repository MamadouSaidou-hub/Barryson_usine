"""En-tetes de securite, filtrage du nom d'hote, taille des requetes."""

from app.core.config import get_settings


def test_entetes_de_securite_sur_toutes_les_reponses(client):
    for chemin in ("/healthz", "/api/auth/moi", "/api/inexistant"):
        entetes = client.get(chemin).headers
        assert entetes["x-content-type-options"] == "nosniff", chemin
        assert entetes["x-frame-options"] == "DENY", chemin
        assert entetes["referrer-policy"] == "no-referrer", chemin
        assert "server" not in entetes, chemin


def test_l_api_n_est_jamais_mise_en_cache(client):
    entetes = client.get("/api/auth/moi").headers
    assert entetes["cache-control"] == "no-store"
    assert "default-src 'none'" in entetes["content-security-policy"]


def test_nom_d_hote_inattendu_refuse(client):
    assert client.get("/healthz", headers={"Host": "site-pirate.example"}).status_code == 400


def test_requete_trop_volumineuse_annoncee_refusee(client):
    enorme = "x" * (get_settings().taille_max_requete_octets + 1)
    reponse = client.post("/api/auth/connexion", content=enorme, headers={"Content-Type": "application/json"})
    assert reponse.status_code == 413
    assert reponse.headers["x-content-type-options"] == "nosniff"


def test_requete_trop_volumineuse_envoyee_par_morceaux_refusee(client):
    taille = get_settings().taille_max_requete_octets

    def morceaux():
        for _ in range(taille // 65536 + 2):
            yield b"x" * 65536

    entetes = {"Content-Type": "application/json"}
    reponse = client.post("/api/auth/connexion", content=morceaux(), headers=entetes)
    assert reponse.status_code == 413


def test_content_length_invalide_refuse(client):
    reponse = client.post("/api/auth/connexion", content="{}",
                          headers={"Content-Type": "application/json", "Content-Length": "-1"})
    assert reponse.status_code in (400, 413)
