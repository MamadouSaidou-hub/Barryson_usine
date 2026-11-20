"""Stock (M04/M05) : registre de mouvements, validations, reservations, lots et bobines."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.audit import JournalAudit
from app.modules.identite.models import Entreprise
from app.modules.identite.permissions import ROLES, a_la_permission
from app.modules.referentiel.models import Article, Fournisseur
from app.modules.stock import service
from app.modules.stock.models import Bobine, Lot, MouvementStock
from tests.conftest import se_connecter


@pytest.fixture
def base(db, entreprise):
    """Un jumbo BOPP (semi-fini, au rouleau), un produit fini (carton) et un fournisseur."""
    db.info.update(acteur_id=None, entreprise_id=entreprise.id)
    jumbo = Article(entreprise_id=entreprise.id, code="JUMBO-GOLD", nom="Jumbo BOPP gold", niveau_stock="semi_fini",
                    unite_gestion="rouleau", seuil_min=Decimal(10))
    produit = Article(entreprise_id=entreprise.id, code="BSG30", nom="BSG 30", niveau_stock="produit_fini",
                      unite_gestion="carton")
    tube = Article(entreprise_id=entreprise.id, code="TUBE-45", nom="Tube papier", niveau_stock="semi_fini",
                   unite_gestion="piece")
    fournisseur = Fournisseur(entreprise_id=entreprise.id, code="CHINE-1", nom="Fournisseur jumbo")
    db.add_all([jumbo, produit, tube, fournisseur])
    db.commit()
    return {"jumbo": jumbo, "produit": produit, "tube": tube, "fournisseur": fournisseur}


def _bobines(n: int, depart: int = 1, **extra) -> list[dict]:
    return [{"numero_fournisseur": str(depart + i), "poids_kg": 251 + i % 5, "metrage_propre": 4000 + i,
             "couleur_finition": "or_transparent", **extra} for i in range(n)]


def _reception(base, reference="CONT-001", bobines=None, **extra) -> dict:
    return {"conteneur_reference": reference, "date_reception": str(date.today()),
            "fournisseur_id": str(base["fournisseur"].id), "article_id": str(base["jumbo"].id),
            "bobines": bobines if bobines is not None else _bobines(3), **extra}


def _solde(client, article) -> dict:
    return client.get("/api/stock/soldes", params={"article_id": str(article.id)}).json()[0]


# --- Droits : chaque route, chaque profil -------------------------------------------------


@pytest.mark.parametrize("role", ROLES)
def test_droits_de_lecture_et_de_saisie_par_profil(client, en_tant_que, base, role):
    entetes = en_tant_que(role)
    lecture = a_la_permission(role, "stock.consulter")
    for chemin in ("/api/stock/soldes", "/api/stock/mouvements", "/api/stock/reservations", "/api/lots",
                   "/api/bobines", "/api/imports-colisage"):
        assert client.get(chemin).status_code == (200 if lecture else 403), (role, chemin)
    saisie = a_la_permission(role, "stock.saisir")
    attendu = 201 if saisie else 403
    reponses = [
        client.post("/api/receptions", headers=entetes, json=_reception(base, f"C-{role}")),
        client.post("/api/stock/reservations", headers=entetes,
                    json={"article_id": str(base["jumbo"].id), "quantite": 1, "motif": "Essai droits"}),
        client.post("/api/stock/mouvements", headers=entetes,
                    json={"type": "ajustement", "sens": "plus", "article_id": str(base["tube"].id),
                          "quantite": 5, "motif": "Essai droits"}),
    ]
    codes = [r.status_code for r in reponses]
    assert codes[0] == attendu and codes[2] == attendu, (role, codes)
    # Une reservation exige du stock disponible : 409 est alors une reponse metier, pas un refus de droit.
    assert codes[1] == 403 if not saisie else codes[1] in (201, 409)


def test_sans_session_tout_est_refuse(client):
    for chemin in ("/api/stock/soldes", "/api/lots", "/api/bobines", "/api/imports-colisage"):
        assert client.get(chemin).status_code == 401


def test_les_types_produits_par_d_autres_modules_ne_passent_pas_par_l_api(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    for type_ in ("reception", "entree", "consommation", "sortie", "retour", "inventaire", "transformation"):
        reponse = client.post("/api/stock/mouvements", headers=entetes,
                              json={"type": type_, "article_id": str(base["jumbo"].id), "quantite": 5,
                                    "motif": "Tentative de forcer"})
        assert reponse.status_code == 422, type_
    assert client.delete("/api/stock/mouvements/x", headers=entetes).status_code in (404, 405)


# --- Reception de conteneur ----------------------------------------------------------------


def test_reception_cree_lot_bobines_et_mouvements(client, en_tant_que, base, db):
    entetes = en_tant_que("responsable_stock")
    lot = client.post("/api/receptions", headers=entetes, json=_reception(base, numero_facture="FAC-77"))
    assert lot.status_code == 201 and lot.json()["nb_bobines"] == 3
    solde = _solde(client, base["jumbo"])
    assert (solde["physique"], solde["disponible"], solde["negatif"]) == (3.0, 3.0, False)
    assert solde["sous_seuil_min"] is True  # seuil minimum 10
    bobines = client.get("/api/bobines", params={"lot_id": lot.json()["id"]}).json()
    assert [b["numero_fournisseur"] for b in bobines] == ["1", "2", "3"]
    assert all(b["statut"] == "disponible" for b in bobines)
    types = {m["type"] for m in client.get("/api/stock/mouvements").json()}
    assert types == {"reception"}
    assert db.scalar(select(JournalAudit).where(JournalAudit.action == "lots.creation")) is not None


def test_deux_lots_peuvent_partager_un_numero_de_bobine(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    assert client.post("/api/receptions", headers=entetes, json=_reception(base, "CONT-A")).status_code == 201
    assert client.post("/api/receptions", headers=entetes, json=_reception(base, "CONT-B")).status_code == 201
    bobines = client.get("/api/bobines").json()
    assert len(bobines) == 6 and len({b["lot_id"] for b in bobines}) == 2
    assert _solde(client, base["jumbo"])["physique"] == 6.0


def test_reception_refusee_selon_les_regles(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    assert client.post("/api/receptions", headers=entetes, json=_reception(base)).status_code == 201
    assert client.post("/api/receptions", headers=entetes, json=_reception(base)).status_code == 409
    doublons = _bobines(2) + _bobines(1, depart=1)
    assert client.post("/api/receptions", headers=entetes,
                       json=_reception(base, "C2", doublons)).status_code == 400
    imprimee = _bobines(1, couleur_impression="rouge", module_impression=45)
    assert client.post("/api/receptions", headers=entetes,
                       json=_reception(base, "C3", imprimee)).status_code == 400
    kaki = _bobines(1, couleur_finition="kaki_imprime", couleur_impression="rouge", module_impression=45)
    assert client.post("/api/receptions", headers=entetes, json=_reception(base, "C4", kaki)).status_code == 201
    futur = _reception(base, "C5") | {"date_reception": str(date.today() + timedelta(days=3))}
    assert client.post("/api/receptions", headers=entetes, json=futur).status_code == 422
    # Un tube (pieces) ou un produit fini ne se recoit pas comme une bobine.
    for article in (base["tube"], base["produit"]):
        reponse = client.post("/api/receptions", headers=entetes,
                              json=_reception(base, "C6") | {"article_id": str(article.id)})
        assert reponse.status_code == 400
    assert client.post("/api/receptions", headers=entetes,
                       json=_reception(base, "C7", [{"numero_fournisseur": "1", "poids_kg": 0,
                                                     "couleur_finition": "kaki_simple"}])).status_code == 422


# --- Mouvements a valider ----------------------------------------------------------------------


def _ajustement(client, entetes, article, sens="plus", quantite=5, **extra):
    return client.post("/api/stock/mouvements", headers=entetes, json={
        "type": "ajustement", "sens": sens, "article_id": str(article.id), "quantite": quantite,
        "motif": "Ecart constate au comptage", **extra})


def test_un_ajustement_ne_compte_qu_apres_validation_par_une_autre_personne(client, en_tant_que, base, db):
    entetes_stock = en_tant_que("responsable_stock")
    mouvement = _ajustement(client, entetes_stock, base["tube"], quantite=40)
    assert mouvement.status_code == 201 and mouvement.json()["statut"] == "en_attente"
    solde = _solde(client, base["tube"])
    assert (solde["physique"], solde["en_attente_validation"]) == (0.0, 1)

    entetes_dg = en_tant_que("dg")
    valide = client.post(f"/api/stock/mouvements/{mouvement.json()['id']}/validation", headers=entetes_dg,
                         json={"decision": "valide"})
    assert valide.status_code == 200 and valide.json()["statut"] == "valide"
    assert valide.json()["valide_par"] is not None
    solde = _solde(client, base["tube"])
    assert (solde["physique"], solde["en_attente_validation"]) == (40.0, 0)
    assert db.scalar(select(JournalAudit).where(JournalAudit.action == "validations_mouvements.creation"))


def test_un_rejet_exige_un_motif_et_ne_change_pas_le_stock(client, en_tant_que, base):
    mouvement = _ajustement(client, en_tant_que("responsable_stock"), base["tube"], quantite=40).json()
    entetes_dg = en_tant_que("dg")
    chemin = f"/api/stock/mouvements/{mouvement['id']}/validation"
    assert client.post(chemin, headers=entetes_dg, json={"decision": "rejete"}).status_code == 422
    rejet = client.post(chemin, headers=entetes_dg, json={"decision": "rejete", "motif": "Comptage à refaire"})
    assert rejet.status_code == 200 and rejet.json()["statut"] == "rejete"
    assert _solde(client, base["tube"])["physique"] == 0.0
    # Une decision est definitive.
    assert client.post(chemin, headers=entetes_dg, json={"decision": "valide"}).status_code == 409
    assert [m["statut"] for m in client.get("/api/stock/mouvements", params={"statut": "rejete"}).json()] == [
        "rejete"]


def test_chaque_type_a_son_valideur(client, en_tant_que, base):
    entetes_stock = en_tant_que("responsable_stock")
    cas = {
        "entree_directe": {"type": "entree_directe", "article_id": str(base["produit"].id), "quantite": 12,
                           "motif": "Cartons déjà présents dans l'usine"},
        "ajustement": {"type": "ajustement", "sens": "plus", "article_id": str(base["tube"].id), "quantite": 5,
                       "motif": "Ecart de comptage"},
        "sortie_exceptionnelle": {"type": "sortie_exceptionnelle", "article_id": str(base["tube"].id),
                                  "quantite": 2, "motif": "Echantillons offerts"},
        "rebut_destruction": {"type": "rebut_destruction", "article_id": str(base["tube"].id), "quantite": 1,
                              "motif": "Tubes écrasés"},
    }
    ids = {t: client.post("/api/stock/mouvements", headers=entetes_stock, json=d).json()["id"]
           for t, d in cas.items()}
    for profil in ("responsable_stock", "chef_production", "comptable", "directeur_commercial"):
        entetes = en_tant_que(profil)
        for mouvement_id in ids.values():
            reponse = client.post(f"/api/stock/mouvements/{mouvement_id}/validation", headers=entetes,
                                  json={"decision": "valide"})
            assert reponse.status_code == 403, (profil, reponse.text)
    entetes_dg = en_tant_que("dg")
    for mouvement_id in ids.values():
        assert client.post(f"/api/stock/mouvements/{mouvement_id}/validation", headers=entetes_dg,
                           json={"decision": "valide"}).status_code == 200


def test_entree_directe_reservee_aux_produits_finis(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    reponse = client.post("/api/stock/mouvements", headers=entetes, json={
        "type": "entree_directe", "article_id": str(base["jumbo"].id), "quantite": 5, "motif": "Bobines trouvées"})
    assert reponse.status_code == 400


def test_le_sens_n_appartient_qu_a_l_ajustement(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    commun = {"article_id": str(base["tube"].id), "quantite": 5, "motif": "Motif suffisant"}
    assert client.post("/api/stock/mouvements", headers=entetes,
                       json={"type": "ajustement", **commun}).status_code == 422
    assert client.post("/api/stock/mouvements", headers=entetes,
                       json={"type": "sortie_exceptionnelle", "sens": "plus", **commun}).status_code == 422
    assert client.post("/api/stock/mouvements", headers=entetes,
                       json={"type": "ajustement", "sens": "moins", **commun, "quantite": 0}).status_code == 422
    assert client.post("/api/stock/mouvements", headers=entetes,
                       json={"type": "ajustement", "sens": "moins", **commun, "motif": "ok"}).status_code == 422


def test_stock_negatif_signale_jamais_bloquant(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    sortie = client.post("/api/stock/mouvements", headers=entetes, json={
        "type": "sortie_exceptionnelle", "article_id": str(base["tube"].id), "quantite": 30,
        "motif": "Sortie avant saisie de la réception"})
    assert sortie.status_code == 201 and sortie.json()["quantite"] == -30.0
    client.post(f"/api/stock/mouvements/{sortie.json()['id']}/validation", headers=en_tant_que("dg"),
                json={"decision": "valide"})
    solde = _solde(client, base["tube"])
    assert solde["physique"] == -30.0 and solde["negatif"] is True


def test_filtres_et_pagination_des_mouvements(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    for i in range(4):
        client.post("/api/receptions", headers=entetes, json=_reception(base, f"CONT-{i}", _bobines(1)))
    page1 = client.get("/api/stock/mouvements", params={"limite": 3}).json()
    assert len(page1) == 3
    page2 = client.get("/api/stock/mouvements", params={"limite": 3, "avant": page1[-1]["cree_le"]}).json()
    assert len(page2) == 1 and page2[0]["id"] not in {m["id"] for m in page1}
    assert client.get("/api/stock/mouvements", params={"type": "ajustement"}).json() == []
    assert client.get("/api/stock/mouvements", params={"type": "inconnu"}).status_code == 422


# --- Separation saisie / validation : trois couches -----------------------------------------------


def test_la_meme_personne_ne_peut_pas_valider_son_propre_mouvement(client, en_tant_que, creer_compte, base, db):
    """Le DG ne saisit pas en temps normal ; on simule un mouvement saisi par lui pour verifier la regle."""
    dg = creer_compte("dg", "dg.auteur")
    mouvement = service.creer_mouvement_manuel(db, dg, {
        "type": "ajustement", "sens": "plus", "article_id": base["tube"].id, "quantite": Decimal(9),
        "motif": "Mouvement saisi par le valideur"})
    client.cookies.clear()
    csrf = {"X-CSRF-Token": se_connecter(client, "dg.auteur")}
    refus = client.post(f"/api/stock/mouvements/{mouvement.id}/validation", headers=csrf,
                        json={"decision": "valide"})
    assert refus.status_code == 403 and "autre personne" in refus.json()["detail"]
    assert db.scalar(select(JournalAudit).where(JournalAudit.action == "validation.refusee_meme_personne"))
    autre = en_tant_que("dg")
    assert client.post(f"/api/stock/mouvements/{mouvement.id}/validation", headers=autre,
                       json={"decision": "valide"}).status_code == 200


def test_la_base_refuse_aussi_un_valideur_identique(db_proprietaire, entreprise_proprietaire):
    e, utilisateur, article = entreprise_proprietaire
    mouvement = MouvementStock(entreprise_id=e.id, article_id=article.id, type="ajustement",
                               quantite=Decimal(5), unite="piece", requiert_validation=True,
                               motif="Ajustement de test", cree_par=utilisateur.id)
    db_proprietaire.add(mouvement)
    db_proprietaire.commit()
    with pytest.raises(DBAPIError, match="Separation saisie/validation"), db_proprietaire.begin_nested():
        db_proprietaire.execute(text(
            "INSERT INTO validations_mouvements (id, entreprise_id, mouvement_id, decision, valide_par) "
            "VALUES (gen_random_uuid(), :e, :m, 'valide', :u)"),
            {"e": e.id, "m": mouvement.id, "u": utilisateur.id})


@pytest.fixture
def entreprise_proprietaire(db_proprietaire):
    from app.core.audit import maintenant
    from app.modules.identite.models import Utilisateur
    e = Entreprise(nom="Usine proprietaire stock")
    db_proprietaire.add(e)
    db_proprietaire.flush()
    maintenant_ = maintenant()
    u = Utilisateur(entreprise_id=e.id, identifiant="auteur.stock", nom="Auteur Stock", role="responsable_stock",
                    mot_de_passe_hash="x", mot_de_passe_modifie_le=maintenant_, cree_le=maintenant_)
    article = Article(entreprise_id=e.id, code="A", nom="Article A", niveau_stock="semi_fini",
                      unite_gestion="piece")
    db_proprietaire.add_all([u, article])
    db_proprietaire.commit()
    return e, u, article


# --- Reservations -------------------------------------------------------------------------------------


def test_reservation_reduit_le_disponible_pas_le_physique(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    client.post("/api/receptions", headers=entetes, json=_reception(base, bobines=_bobines(10)))
    corps = {"article_id": str(base["jumbo"].id), "quantite": 4, "motif": "Ordre de fabrication BSG 30"}
    reservation = client.post("/api/stock/reservations", headers=entetes, json=corps)
    assert reservation.status_code == 201
    solde = _solde(client, base["jumbo"])
    assert (solde["physique"], solde["reserve"], solde["disponible"]) == (10.0, 4.0, 6.0)
    # Pas de promesse au-dela du disponible.
    assert client.post("/api/stock/reservations", headers=entetes,
                       json=corps | {"quantite": 7}).status_code == 409
    assert client.post("/api/stock/reservations", headers=entetes, json=corps | {"quantite": 6}).status_code == 201
    levee = client.post(f"/api/stock/reservations/{reservation.json()['id']}/lever", headers=entetes)
    assert levee.status_code == 200 and levee.json()["statut"] == "levee"
    assert client.post(f"/api/stock/reservations/{reservation.json()['id']}/lever", headers=entetes).status_code == 409
    assert _solde(client, base["jumbo"])["disponible"] == 4.0
    assert [r["statut"] for r in client.get("/api/stock/reservations", params={"statut": "ouverte"}).json()] == [
        "ouverte"]


# --- Isolation entre entreprises ----------------------------------------------------------------------


def test_isolation_entre_entreprises(client, en_tant_que, base, db):
    autre = Entreprise(nom="Autre usine")
    db.add(autre)
    db.flush()
    etranger = Article(entreprise_id=autre.id, code="SECRET", nom="Autre", niveau_stock="semi_fini",
                       unite_gestion="rouleau")
    db.add(etranger)
    db.commit()
    entetes = en_tant_que("responsable_stock")
    assert "SECRET" not in [s["code"] for s in client.get("/api/stock/soldes").json()]
    reponse = client.post("/api/stock/reservations", headers=entetes,
                          json={"article_id": str(etranger.id), "quantite": 1, "motif": "Tentative étrangère"})
    assert reponse.status_code == 400
    reception = client.post("/api/receptions", headers=entetes,
                            json=_reception(base) | {"article_id": str(etranger.id)})
    assert reception.status_code == 400


# --- Protections en base ---------------------------------------------------------------------------------


@pytest.mark.parametrize("requete", [
    "UPDATE mouvements_stock SET quantite = 999", "DELETE FROM mouvements_stock", "TRUNCATE mouvements_stock",
    "UPDATE validations_mouvements SET decision = 'valide'", "DELETE FROM validations_mouvements",
    "UPDATE lignes_import_colisage SET poids_kg = 1", "DELETE FROM lignes_import_colisage",
    "UPDATE lots SET conteneur_reference = 'X'", "DELETE FROM lots", "DELETE FROM bobines",
    "DELETE FROM reservations_stock", "DELETE FROM imports_colisage",
])
def test_le_compte_applicatif_ne_peut_ni_reecrire_ni_supprimer(db, requete):
    with pytest.raises(DBAPIError, match="permission denied"), db.begin_nested():
        db.execute(text(requete))


def test_le_proprietaire_lui_meme_ne_reecrit_pas_le_registre(db_proprietaire, entreprise_proprietaire):
    e, utilisateur, article = entreprise_proprietaire
    mouvement = MouvementStock(entreprise_id=e.id, article_id=article.id, type="reception", quantite=Decimal(1),
                               unite="piece", requiert_validation=False, motif="Reception de test",
                               cree_par=utilisateur.id)
    db_proprietaire.add(mouvement)
    db_proprietaire.commit()
    for requete in (f"UPDATE mouvements_stock SET quantite = 99 WHERE id = '{mouvement.id}'",
                    f"DELETE FROM mouvements_stock WHERE id = '{mouvement.id}'"):
        with pytest.raises(DBAPIError, match="ajout seul"), db_proprietaire.begin_nested():
            db_proprietaire.execute(text(requete))


@pytest.mark.parametrize("valeurs,contrainte", [
    ("'reception', -1, FALSE", "entree_positive"),
    ("'sortie', 1, FALSE", "sortie_negative"),
    ("'ajustement', 0, TRUE", "quantite_non_nulle"),
    ("'ajustement', 5, FALSE", "validation_selon_type"),
    ("'reception', 1, TRUE", "validation_selon_type"),
    ("'inventeur', 1, FALSE", "type_connu"),
])
def test_contraintes_de_coherence_des_mouvements(db_proprietaire, entreprise_proprietaire, valeurs, contrainte):
    e, utilisateur, article = entreprise_proprietaire
    with pytest.raises(DBAPIError, match=contrainte), db_proprietaire.begin_nested():
        db_proprietaire.execute(text(
            "INSERT INTO mouvements_stock (id, entreprise_id, article_id, type, quantite, unite, "
            "requiert_validation, motif) "
            f"VALUES (gen_random_uuid(), :e, :a, {valeurs.split(',')[0]}, {valeurs.split(',')[1]}, 'piece', "
            f"{valeurs.split(',')[2]}, 'Test de contrainte')"), {"e": e.id, "a": article.id})


# --- Import de packing list ------------------------------------------------------------------------------


def _import(base, reference="CONT-IMP", lignes=None, **extra) -> dict:
    return {"conteneur_reference": reference, "date_reception": str(date.today()),
            "fournisseur_id": str(base["fournisseur"].id), "article_id": str(base["jumbo"].id),
            "lignes": lignes if lignes is not None else [
                {"numero_fournisseur": str(i), "poids_kg": 251 + i % 3, "metrage_propre": 4000,
                 "couleur_brute": "Gold transparent", "couleur_finition": "or_transparent"}
                for i in range(1, 6)], **extra}


def test_analyse_des_lignes_fonction_pure():
    lignes = [{"numero_fournisseur": "1", "poids_kg": Decimal(250), "couleur_finition": "kaki_simple",
               "metrage_propre": Decimal(4000)},
              {"numero_fournisseur": "1", "poids_kg": Decimal(250), "couleur_finition": "kaki_simple"},
              {"numero_fournisseur": None, "poids_kg": None, "couleur_finition": None, "couleur_brute": "Golden01"},
              {"numero_fournisseur": "4", "poids_kg": Decimal(250), "couleur_finition": "kaki_simple",
               "couleur_impression": "rouge", "metrage_propre": Decimal(1)}]
    codes = [[a["code"] for a in ligne] for ligne in service.analyser_lignes(lignes)]
    assert codes[0] == ["doublon_numero"]
    assert codes[1] == ["doublon_numero", "metrage_manquant"]
    assert codes[2] == ["numero_manquant", "poids_manquant", "finition_non_reconnue", "metrage_manquant"]
    assert codes[3] == ["impression_incoherente"]


def test_poids_atypique_signale_a_partir_de_dix_lignes():
    lignes = [{"numero_fournisseur": str(i), "poids_kg": Decimal(252), "couleur_finition": "kaki_simple",
               "metrage_propre": Decimal(4000)} for i in range(12)]
    lignes[5]["poids_kg"] = Decimal(300)
    anomalies = service.analyser_lignes(lignes)
    assert [a["code"] for a in anomalies[5]] == ["poids_atypique"]
    assert all(not a for i, a in enumerate(anomalies) if i != 5)
    assert not any(service.analyser_lignes(lignes[:5]))


def test_import_en_deux_temps_rien_en_stock_avant_validation(client, en_tant_que, base, db):
    entetes = en_tant_que("responsable_stock")
    apercu = client.post("/api/imports-colisage", headers=entetes, json=_import(base))
    assert apercu.status_code == 201
    corps = apercu.json()
    assert (corps["statut"], corps["nb_lignes"], corps["nb_bloquantes"], corps["nb_avertissements"]) == (
        "brouillon", 5, 0, 0)
    assert len(corps["lignes"]) == 5 and corps["lignes"][0]["couleur_brute"] == "Gold transparent"
    assert client.get("/api/lots").json() == [] and _solde(client, base["jumbo"])["physique"] == 0.0

    valide = client.post(f"/api/imports-colisage/{corps['id']}/valider", headers=entetes)
    assert valide.status_code == 200
    assert valide.json()["statut"] == "valide" and valide.json()["lot_id"] is not None
    assert _solde(client, base["jumbo"])["physique"] == 5.0
    lots = client.get("/api/lots").json()
    assert [(lot["conteneur_reference"], lot["nb_bobines"]) for lot in lots] == [("CONT-IMP", 5)]
    assert db.scalar(select(JournalAudit).where(JournalAudit.action == "imports_colisage.modification"))
    # Un import valide ne se rejoue pas : pas de reception en double.
    assert client.post(f"/api/imports-colisage/{corps['id']}/valider", headers=entetes).status_code == 409
    assert client.post(f"/api/imports-colisage/{corps['id']}/annuler", headers=entetes).status_code == 409
    assert _solde(client, base["jumbo"])["physique"] == 5.0


def test_anomalies_bloquantes_empechent_la_validation(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    lignes = [{"numero_fournisseur": "1", "poids_kg": 251, "couleur_finition": "or_transparent"},
              {"numero_fournisseur": "1", "poids_kg": 252, "couleur_finition": "or_transparent"},
              {"numero_fournisseur": "3", "poids_kg": 251, "couleur_brute": "Golden01"}]
    apercu = client.post("/api/imports-colisage", headers=entetes, json=_import(base, lignes=lignes)).json()
    assert apercu["nb_bloquantes"] == 3 and apercu["nb_avertissements"] == 3
    assert {a["code"] for ligne in apercu["lignes"] for a in ligne["anomalies"]} == {
        "doublon_numero", "finition_non_reconnue", "metrage_manquant"}
    refus = client.post(f"/api/imports-colisage/{apercu['id']}/valider", headers=entetes)
    assert refus.status_code == 400 and "3 anomalie" in refus.json()["detail"]
    assert client.get("/api/lots").json() == []
    # Correction : on annule puis on refait l'import (le conteneur est de nouveau libre).
    assert client.post("/api/imports-colisage", headers=entetes,
                       json=_import(base, lignes=lignes)).status_code == 409
    assert client.post(f"/api/imports-colisage/{apercu['id']}/annuler", headers=entetes).status_code == 200
    assert client.post("/api/imports-colisage", headers=entetes, json=_import(base)).status_code == 201


def test_import_refuse_un_conteneur_deja_recu(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    client.post("/api/receptions", headers=entetes, json=_reception(base, "CONT-DEJA"))
    assert client.post("/api/imports-colisage", headers=entetes,
                       json=_import(base, "CONT-DEJA")).status_code == 409


def test_la_validation_revalide_l_etat_du_moment(client, en_tant_que, base):
    """Un conteneur recu entre l'apercu et la validation ne doit pas etre recu une seconde fois."""
    entetes = en_tant_que("responsable_stock")
    apercu = client.post("/api/imports-colisage", headers=entetes, json=_import(base, "CONT-COURSE")).json()
    client.post("/api/receptions", headers=entetes, json=_reception(base, "CONT-COURSE"))
    refus = client.post(f"/api/imports-colisage/{apercu['id']}/valider", headers=entetes)
    assert refus.status_code == 409
    assert _solde(client, base["jumbo"])["physique"] == 3.0
    assert client.get(f"/api/imports-colisage/{apercu['id']}").json()["statut"] == "brouillon"


def test_validation_de_l_import_reservee_au_controle_des_receptions(client, en_tant_que, base):
    apercu = client.post("/api/imports-colisage", headers=en_tant_que("responsable_stock"),
                         json=_import(base)).json()
    for profil in ("chef_production", "comptable", "directeur_commercial", "dg", "administrateur"):
        refus = client.post(f"/api/imports-colisage/{apercu['id']}/valider", headers=en_tant_que(profil))
        assert refus.status_code == 403, profil


def test_import_d_un_conteneur_reel_sans_metrage(client, en_tant_que, base):
    """Forme du premier fichier fournisseur : numero, finition, poids net, aucun metrage (102 bobines)."""
    entetes = en_tant_que("responsable_stock")
    finitions = [(range(1, 61), "Gold transparent", "or_transparent"),
                 (range(61, 81), "Jaune transparent", "jaune_transparent"),
                 (range(81, 96), "Clair transparent", "transparent_clair"),
                 (range(96, 103), "Kaki simple", "kaki_simple")]
    lignes = [{"numero_fournisseur": str(n), "poids_kg": 252 - (n % 4), "couleur_brute": brut,
               "couleur_finition": finition} for plage, brut, finition in finitions for n in plage]
    apercu = client.post("/api/imports-colisage", headers=entetes, json=_import(base, "CONT-102", lignes))
    assert apercu.status_code == 201
    corps = apercu.json()
    assert (corps["nb_lignes"], corps["nb_bloquantes"], corps["nb_avertissements"]) == (102, 0, 102)
    assert client.post(f"/api/imports-colisage/{corps['id']}/valider", headers=entetes).status_code == 200
    assert _solde(client, base["jumbo"])["physique"] == 102.0
    kaki = client.get("/api/bobines", params={"couleur": "kaki_simple"}).json()
    assert len(kaki) == 7 and all(b["metrage_propre"] is None for b in kaki)


def test_import_du_vrai_fichier_du_fournisseur_chinois(client, en_tant_que, base):
    """Packing list reelle (102 bobines BOPP) : totaux de reference, aucune anomalie, finitions et metrages."""
    from app.donnees_demo import lignes_packing_list_102

    entetes = en_tant_que("responsable_stock")
    lignes = lignes_packing_list_102()
    corps = client.post("/api/imports-colisage", headers=entetes, json=_import(base, "CONT-REEL", lignes)).json()
    assert (corps["nb_lignes"], corps["nb_bloquantes"], corps["nb_avertissements"]) == (102, 0, 0)
    assert client.post(f"/api/imports-colisage/{corps['id']}/valider", headers=entetes).status_code == 200

    bobines = client.get("/api/bobines", params={"limite": 200}).json()
    assert len(bobines) == 102 and _solde(client, base["jumbo"])["physique"] == 102.0
    assert round(sum(float(b["poids_kg"]) for b in bobines), 1) == 25666.8
    assert sum(float(b["metrage_propre"]) for b in bobines) == 408590
    par_finition = {f: sum(1 for b in bobines if b["couleur_finition"] == f)
                    for f in ("or_transparent", "jaune_transparent", "transparent_clair", "kaki_simple")}
    assert par_finition == {"or_transparent": 60, "jaune_transparent": 20, "transparent_clair": 15,
                            "kaki_simple": 7}
    # La reference couleur du fournisseur reste consultable : Golden01 (40) et Golden03 (20).
    detail = client.get(f"/api/imports-colisage/{corps['id']}").json()["lignes"]
    assert sum("Golden01" in (l["couleur_brute"] or "") for l in detail) == 40
    assert sum("Golden03" in (l["couleur_brute"] or "") for l in detail) == 20


def test_import_trop_gros_ou_mal_forme_refuse(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    assert client.post("/api/imports-colisage", headers=entetes, json=_import(base, lignes=[])).status_code == 422
    trop = [{"numero_fournisseur": str(i), "poids_kg": 250, "couleur_finition": "kaki_simple"}
            for i in range(2001)]
    assert client.post("/api/imports-colisage", headers=entetes, json=_import(base, lignes=trop)).status_code in (
        413, 422)
    inconnue = [{"numero_fournisseur": "1", "poids_kg": 250, "couleur_finition": "arc_en_ciel"}]
    assert client.post("/api/imports-colisage", headers=entetes,
                       json=_import(base, lignes=inconnue)).status_code == 422


def test_isolation_des_imports_et_des_lots(client, en_tant_que, base, db):
    autre = Entreprise(nom="Autre usine imports")
    db.add(autre)
    db.flush()
    fournisseur = Fournisseur(entreprise_id=autre.id, code="F-AUTRE", nom="Autre fournisseur")
    db.add(fournisseur)
    db.flush()
    lot = Lot(entreprise_id=autre.id, conteneur_reference="CONT-ETRANGER", date_reception=date.today(),
              fournisseur_id=fournisseur.id)
    db.add(lot)
    db.commit()
    en_tant_que("responsable_stock")
    assert client.get("/api/lots").json() == []
    assert client.get(f"/api/lots/{lot.id}").status_code == 404
    assert client.get(f"/api/imports-colisage/{lot.id}").status_code == 404
    # Le meme numero de conteneur reste libre dans notre entreprise.
    assert client.post("/api/receptions", headers=en_tant_que("responsable_stock"),
                       json=_reception(base, "CONT-ETRANGER")).status_code == 201
    assert db.scalar(select(Bobine).where(Bobine.entreprise_id == autre.id)) is None
