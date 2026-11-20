"""Referentiel (M02) : droits par profil, regles metier, versionnement, protections en base."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.audit import JournalAudit
from app.core.config import get_settings
from app.modules.identite.models import Entreprise
from app.modules.identite.permissions import ROLES, a_la_permission
from app.modules.referentiel import service
from app.modules.referentiel.models import Article, LargeurReference, VersionModeleRuban
from tests.conftest import se_connecter


@pytest.fixture
def en_tant_que(client, creer_compte):
    crees: set[str] = set()

    def _connecter(role: str) -> dict:
        if role not in crees:
            creer_compte(role)
            crees.add(role)
        client.cookies.clear()
        return {"X-CSRF-Token": se_connecter(client, f"{role.replace('_', '-')}.test")}

    return _connecter


@pytest.fixture
def references(db, entreprise):
    db.info.update(acteur_id=None, entreprise_id=entreprise.id)
    service.charger_references_connues(db, entreprise.id)


def _creer(client, entetes, chemin, donnees, attendu=201):
    reponse = client.post(chemin, headers=entetes, json=donnees)
    assert reponse.status_code == attendu, reponse.text
    return reponse.json()


# --- Chaque route applique la bonne permission, pour chacun des 7 profils ------

RESSOURCES = [
    ("/api/articles", "referentiels.consulter", "referentiels.saisir",
     lambda i: {"code": f"ART-{i}", "nom": "Bobine BOPP jumbo", "niveau_stock": "semi_fini",
                "unite_gestion": "rouleau"}),
    ("/api/moules", "modeles.consulter", "modeles.saisir",
     lambda i: {"code": f"MOULE-{i}", "nom": "Moule 45 mm"}),
    ("/api/clients", "clients.consulter", "clients.saisir",
     lambda i: {"code": f"CLI-{i}", "nom": "Quincaillerie Madina", "type_client": "boutique"}),
    ("/api/fournisseurs", "achats.consulter", "achats.saisir",
     lambda i: {"code": f"FOU-{i}", "nom": "Fournisseur jumbo Chine", "pays": "Chine"}),
    ("/api/references/largeurs", "modeles.consulter", "modeles.saisir",
     lambda i: {"largeur_mm": 30 + i, "pieces_par_tour": 40}),
]


@pytest.mark.parametrize("role", ROLES)
def test_droits_de_lecture_et_d_ecriture_par_profil(client, en_tant_que, role):
    entetes = en_tant_que(role)
    for i, (chemin, lecture, ecriture, donnees) in enumerate(RESSOURCES):
        attendu_lecture = 200 if a_la_permission(role, lecture) else 403
        assert client.get(chemin).status_code == attendu_lecture, (role, chemin)
        attendu_ecriture = 201 if a_la_permission(role, ecriture) else 403
        reponse = client.post(chemin, headers=entetes, json=donnees(i))
        assert reponse.status_code == attendu_ecriture, (role, chemin, reponse.text)


def test_le_dg_consulte_tout_mais_ne_saisit_pas_le_referentiel(client, en_tant_que):
    entetes = en_tant_que("dg")
    for chemin, *_ in RESSOURCES:
        assert client.get(chemin).status_code == 200
    assert client.post("/api/articles", headers=entetes, json=RESSOURCES[0][3](0)).status_code == 403


def test_sans_session_tout_est_refuse(client):
    for chemin, *_ in RESSOURCES:
        assert client.get(chemin).status_code == 401


def test_aucune_suppression_possible_par_l_api(client, en_tant_que):
    entetes = en_tant_que("responsable_stock")
    article = _creer(client, entetes, "/api/articles", RESSOURCES[0][3](0))
    assert client.delete(f"/api/articles/{article['id']}", headers=entetes).status_code == 405


# --- Articles ----------------------------------------------------------------


def test_creation_article_code_normalise_et_trace(client, en_tant_que, db):
    entetes = en_tant_que("responsable_stock")
    article = _creer(client, entetes, "/api/articles", {
        "code": "  tube-papier-45 ", "nom": "Tube papier 45 mm", "niveau_stock": "semi_fini",
        "unite_gestion": "piece", "seuil_min": "500", "seuil_max": 5000})
    assert article["code"] == "TUBE-PAPIER-45"
    assert article["seuil_min"] == 500.0
    entree = db.scalar(select(JournalAudit).where(JournalAudit.action == "articles.creation",
                                                  JournalAudit.cible_id == article["id"]))
    assert entree.acteur_id is not None and entree.apres["code"] == "TUBE-PAPIER-45"


def test_code_article_en_double(client, en_tant_que):
    entetes = en_tant_que("responsable_stock")
    _creer(client, entetes, "/api/articles", RESSOURCES[0][3](1))
    _creer(client, entetes, "/api/articles", RESSOURCES[0][3](1), attendu=409)


def test_niveau_matiere_premiere_inactif_par_defaut(client, en_tant_que, monkeypatch):
    entetes = en_tant_que("responsable_stock")
    donnees = {"code": "PAPIER-GG", "nom": "Papier gris-gris", "niveau_stock": "matiere_premiere",
               "unite_gestion": "kg"}
    reponse = client.post("/api/articles", headers=entetes, json=donnees)
    assert reponse.status_code == 403 and "matière première" in reponse.json()["detail"]
    # Le schema le prevoit : il suffit de l'activer si la fabrication reprend.
    monkeypatch.setattr(get_settings(), "niveau_matiere_premiere_actif", True)
    _creer(client, entetes, "/api/articles", donnees)


def test_niveau_et_unite_ne_se_modifient_jamais(client, en_tant_que):
    entetes = en_tant_que("responsable_stock")
    article = _creer(client, entetes, "/api/articles", RESSOURCES[0][3](2))
    for changement in ({"niveau_stock": "produit_fini"}, {"unite_gestion": "kg"}, {"code": "AUTRE"}):
        reponse = client.patch(f"/api/articles/{article['id']}", headers=entetes, json=changement)
        assert reponse.status_code == 422, changement


def test_modification_partielle_et_regles_de_seuils(client, en_tant_que):
    entetes = en_tant_que("responsable_stock")
    donnees = {**RESSOURCES[0][3](3), "seuil_min": 10, "seuil_max": 50}
    article = _creer(client, entetes, "/api/articles", donnees)
    chemin = f"/api/articles/{article['id']}"
    assert client.patch(chemin, headers=entetes, json={"seuil_min": 80}).status_code == 400
    assert client.patch(chemin, headers=entetes, json={"nom": None}).status_code == 422
    modifie = client.patch(chemin, headers=entetes, json={"seuil_max": None, "actif": False}).json()
    assert modifie["seuil_max"] is None and modifie["seuil_min"] == 10.0 and modifie["actif"] is False
    assert [a["code"] for a in client.get("/api/articles", params={"actif": "false"}).json()] == ["ART-3"]


def test_recherche_et_filtre_par_niveau(client, en_tant_que):
    entetes = en_tant_que("responsable_stock")
    _creer(client, entetes, "/api/articles", {"code": "BSG30-CARTON", "nom": "BSG 30 (90 pièces)",
                                              "niveau_stock": "produit_fini", "unite_gestion": "carton"})
    _creer(client, entetes, "/api/articles", RESSOURCES[0][3](4))
    assert [a["code"] for a in client.get("/api/articles", params={"niveau": "produit_fini"}).json()] == [
        "BSG30-CARTON"]
    assert len(client.get("/api/articles", params={"recherche": "bsg 30"}).json()) == 1
    # Un % saisi est cherche tel quel, pas comme joker.
    assert client.get("/api/articles", params={"recherche": "%"}).json() == []
    assert client.get("/api/articles", params={"niveau": "inconnu"}).status_code == 422


def test_isolation_entre_entreprises(client, en_tant_que, db):
    autre = Entreprise(nom="Autre usine")
    db.add(autre)
    db.flush()
    etranger = Article(entreprise_id=autre.id, code="SECRET", nom="Article d'une autre usine",
                       niveau_stock="semi_fini", unite_gestion="kg")
    db.add(etranger)
    db.commit()
    entetes = en_tant_que("responsable_stock")
    assert "SECRET" not in [a["code"] for a in client.get("/api/articles").json()]
    assert client.get(f"/api/articles/{etranger.id}").status_code == 404
    pirate = client.patch(f"/api/articles/{etranger.id}", headers=entetes, json={"nom": "Pirate"})
    assert pirate.status_code == 404
    # Meme code dans une autre entreprise : autorise, les catalogues sont independants.
    _creer(client, entetes, "/api/articles", {**RESSOURCES[0][3](0), "code": "SECRET"})


# --- Conversions d'unites ----------------------------------------------------


def test_conversions(client, en_tant_que):
    entetes = en_tant_que("responsable_stock")
    article = _creer(client, entetes, "/api/articles", RESSOURCES[0][3](5))
    generale = {"unite_source": "carton", "unite_cible": "piece", "facteur": 90}
    _creer(client, entetes, "/api/conversions-unites", generale)
    _creer(client, entetes, "/api/conversions-unites", generale, attendu=409)
    propre = {**generale, "article_id": article["id"], "facteur": 72}
    _creer(client, entetes, "/api/conversions-unites", propre)
    _creer(client, entetes, "/api/conversions-unites", {**generale, "unite_cible": "carton"}, attendu=400)
    _creer(client, entetes, "/api/conversions-unites", {**generale, "facteur": 0}, attendu=422)


# --- Modeles de ruban : references usine et versionnement ---------------------


def _articles_production(client, entetes_stock):
    pf = _creer(client, entetes_stock, "/api/articles", {"code": "BSG30", "nom": "BSG 30 45mm x 25m",
                                                         "niveau_stock": "produit_fini",
                                                         "unite_gestion": "carton"})
    tube = _creer(client, entetes_stock, "/api/articles", {"code": "TUBE-45", "nom": "Tube papier 45 mm",
                                                           "niveau_stock": "semi_fini",
                                                           "unite_gestion": "piece"})
    return pf, tube


def test_bsg30_deduit_ses_pieces_des_references_usine(client, en_tant_que, references):
    entetes = en_tant_que("chef_production")
    modele = _creer(client, entetes, "/api/modeles-ruban", {
        "code": "BSG-30", "nom": "BSG 30", "famille": "bopp", "largeur_mm": 45, "longueur_rouleau_m": 25})
    version = modele["version_courante"]
    assert (version["numero"], version["pieces_par_tour"], version["pieces_par_carton"]) == (1, 28, 90)
    assert modele["complet"] is False


def test_conditionnement_inconnu_refuse_avec_explication(client, en_tant_que, references):
    entetes = en_tant_que("chef_production")
    reponse = client.post("/api/modeles-ruban", headers=entetes, json={
        "code": "BOPP-70-120", "nom": "BOPP 70 x 120", "famille": "bopp", "largeur_mm": 70,
        "longueur_rouleau_m": 120})
    assert reponse.status_code == 400 and "carton" in reponse.json()["detail"]
    # Aucune fiche orpheline laissee derriere.
    assert client.get("/api/modeles-ruban").json() == []
    # Valeur fournie explicitement : accepte.
    _creer(client, entetes, "/api/modeles-ruban", {
        "code": "BOPP-70-120", "nom": "BOPP 70 x 120", "famille": "bopp", "largeur_mm": 70,
        "longueur_rouleau_m": 120, "pieces_par_carton": 24})


def test_chaque_evolution_cree_une_version_et_fige_la_precedente(client, en_tant_que, references, db):
    pf, tube = _articles_production(client, en_tant_que("responsable_stock"))
    entetes = en_tant_que("chef_production")
    moule = _creer(client, entetes, "/api/moules", {"code": "M45", "nom": "Moule 45"})
    modele = _creer(client, entetes, "/api/modeles-ruban", {
        "code": "BSG-30", "nom": "BSG 30", "famille": "bopp", "largeur_mm": 45, "longueur_rouleau_m": 25})
    chemin = f"/api/modeles-ruban/{modele['id']}/versions"

    v2 = _creer(client, entetes, chemin, {"motif": "Nomenclature transmise par le DG",
                                          "moule_id": moule["id"], "article_produit_fini_id": pf["id"],
                                          "article_tube_id": tube["id"]})
    assert v2["version_courante"]["numero"] == 2 and v2["complet"] is True
    assert v2["version_courante"]["pieces_par_carton"] == 90  # repris de la version 1

    v3 = _creer(client, entetes, chemin, {"motif": "Passage au rouleau de 50 m", "longueur_rouleau_m": 50})
    assert (v3["version_courante"]["numero"], v3["version_courante"]["pieces_par_carton"]) == (3, 72)
    assert v3["version_courante"]["moule_id"] == moule["id"]

    historique = client.get(chemin).json()
    assert [v["numero"] for v in historique] == [3, 2, 1]
    assert historique[2]["longueur_rouleau_m"] == 25.0 and historique[2]["moule_id"] is None
    assert db.scalar(select(JournalAudit).where(JournalAudit.action == "versions_modeles_ruban.creation",
                                                JournalAudit.cible_id == historique[0]["id"])) is not None


def test_coherence_des_articles_lies_a_un_modele(client, en_tant_que, references):
    pf, tube = _articles_production(client, en_tant_que("responsable_stock"))
    entetes = en_tant_que("chef_production")
    base = {"code": "BSG-30", "nom": "BSG 30", "famille": "bopp", "largeur_mm": 45, "longueur_rouleau_m": 25}
    # Un produit fini ne peut pas servir de tube, ni l'inverse.
    assert client.post("/api/modeles-ruban", headers=entetes,
                       json={**base, "article_tube_id": pf["id"]}).status_code == 400
    assert client.post("/api/modeles-ruban", headers=entetes,
                       json={**base, "article_produit_fini_id": tube["id"]}).status_code == 400
    modele = _creer(client, entetes, "/api/modeles-ruban", base)
    _creer(client, entetes, "/api/modeles-ruban", base, attendu=409)

    client.patch(f"/api/modeles-ruban/{modele['id']}", headers=entetes, json={"actif": False})
    reponse = client.post(f"/api/modeles-ruban/{modele['id']}/versions", headers=entetes,
                          json={"motif": "Essai sur modele inactif", "longueur_rouleau_m": 50})
    assert reponse.status_code == 403
    assert client.post(f"/api/modeles-ruban/{modele['id']}/versions", headers=entetes,
                       json={"motif": "x"}).status_code == 422


# --- Protections en base de donnees ------------------------------------------


@pytest.mark.parametrize("requete", [
    "DELETE FROM articles", "DELETE FROM clients", "DELETE FROM fournisseurs", "DELETE FROM moules",
    "DELETE FROM modeles_ruban", "UPDATE versions_modeles_ruban SET pieces_par_carton = 1",
    "DELETE FROM versions_modeles_ruban", "TRUNCATE articles",
])
def test_le_compte_applicatif_ne_peut_ni_supprimer_ni_reecrire_l_historique(db, requete):
    with pytest.raises(DBAPIError, match="permission denied"), db.begin_nested():
        db.execute(text(requete))


def test_meme_le_proprietaire_ne_reecrit_pas_une_version(db_proprietaire):
    e = Entreprise(nom="Usine proprietaire")
    db_proprietaire.add(e)
    db_proprietaire.flush()
    db_proprietaire.info.update(entreprise_id=e.id)
    service.charger_references_connues(db_proprietaire, e.id)

    class Acteur:
        id = None
        entreprise_id = e.id

    donnees = {"code": "BSG-30", "nom": "BSG 30", "famille": "bopp", "largeur_mm": 45,
               "longueur_rouleau_m": 25}
    modele = service.creer_modele(db_proprietaire, Acteur, donnees)
    version = db_proprietaire.scalar(select(VersionModeleRuban)
                                     .where(VersionModeleRuban.modele_id == modele.id))
    with pytest.raises(DBAPIError, match="ajout seul"), db_proprietaire.begin_nested():
        db_proprietaire.execute(text(f"UPDATE versions_modeles_ruban SET pieces_par_carton = 1 "
                                     f"WHERE id = '{version.id}'"))


# --- Donnees de reference ------------------------------------------------------


def test_chargement_des_references_idempotent_et_non_destructif(db, entreprise):
    db.info.update(acteur_id=None, entreprise_id=entreprise.id)
    assert service.charger_references_connues(db, entreprise.id) == {"largeurs": 4, "conditionnements": 5}
    reference = db.scalar(select(LargeurReference).where(LargeurReference.largeur_mm == 45))
    reference.pieces_par_tour = 27  # corrige par l'usine
    db.commit()
    assert service.charger_references_connues(db, entreprise.id) == {"largeurs": 0, "conditionnements": 0}
    db.refresh(reference)
    assert reference.pieces_par_tour == 27


# --- Clients et fournisseurs -------------------------------------------------


def test_clients_et_fournisseurs_valident_leurs_donnees(client, en_tant_que):
    entetes = en_tant_que("directeur_commercial")
    base = {"code": "CLI-1", "nom": "Entreprise partenaire SA", "type_client": "entreprise_partenaire"}
    for invalide in ({"telephone": "appelez-moi"}, {"plafond_encours_gnf": -1}, {"type_client": "commercial"},
                     {"delai_paiement_jours": 400}):
        assert client.post("/api/clients", headers=entetes, json={**base, **invalide}).status_code == 422
    cree = _creer(client, entetes, "/api/clients", {**base, "telephone": "+224 620 00 00 00",
                                                    "plafond_encours_gnf": 50_000_000})
    assert cree["plafond_encours_gnf"] == 50_000_000

    entetes = en_tant_que("responsable_stock")
    assert client.post("/api/fournisseurs", headers=entetes,
                       json={"code": "F1", "nom": "Fournisseur", "email": "pas-un-email"}).status_code == 422
    _creer(client, entetes, "/api/fournisseurs", {"code": "F1", "nom": "Fournisseur jumbo",
                                                  "email": "ventes@exemple.cn", "delai_livraison_jours": 45})
