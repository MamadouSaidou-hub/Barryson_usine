"""Achats (M03) : de la commande au fournisseur jusqu'a l'entree en stock controlee."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.audit import JournalAudit
from app.modules.achats import service as achats
from app.modules.achats.models import CommandeAchat
from app.modules.identite.models import Entreprise
from app.modules.identite.permissions import ROLES, a_la_permission
from app.modules.referentiel.models import Article, Fournisseur
from app.modules.stock.models import Bobine, ImportColisage, Lot

AUJOURD_HUI = str(date.today())


@pytest.fixture
def base(db, entreprise):
    db.info.update(acteur_id=None, entreprise_id=entreprise.id)
    jumbo = Article(entreprise_id=entreprise.id, code="JUMBO", nom="Jumbo BOPP", niveau_stock="semi_fini",
                    unite_gestion="rouleau")
    tube = Article(entreprise_id=entreprise.id, code="TUBE-45", nom="Tube papier 45 mm", niveau_stock="semi_fini",
                   unite_gestion="piece")
    produit = Article(entreprise_id=entreprise.id, code="BSG30", nom="BSG 30", niveau_stock="produit_fini",
                      unite_gestion="carton")
    chine = Fournisseur(entreprise_id=entreprise.id, code="CHINE-1", nom="Fournisseur jumbo Chine", pays="Chine")
    autre = Fournisseur(entreprise_id=entreprise.id, code="CHINE-2", nom="Autre fournisseur", pays="Chine")
    db.add_all([jumbo, tube, produit, chine, autre])
    db.commit()
    return {"jumbo": jumbo, "tube": tube, "produit": produit, "chine": chine, "autre": autre}


def _commande(base, lignes=None, **extra) -> dict:
    return {"fournisseur_id": str(base["chine"].id), "devise": "USD", "date_arrivee_prevue": "2026-12-15",
            "lignes": lignes if lignes is not None else [
                {"article_id": str(base["jumbo"].id), "quantite_commandee": 5, "prix_unitaire": 1450,
                 "couleur_finition": "or_transparent"},
                {"article_id": str(base["tube"].id), "quantite_commandee": 5000, "prix_unitaire": "0.12"}],
            **extra}


def _packing_list(base, reference="CONT-CN-01", nombre=5, **extra) -> dict:
    return {"conteneur_reference": reference, "date_reception": AUJOURD_HUI,
            "fournisseur_id": str(base["chine"].id), "article_id": str(base["jumbo"].id),
            "lignes": [{"numero_fournisseur": str(i), "poids_kg": 251, "metrage_propre": 4000,
                        "couleur_brute": "Gold transparent", "couleur_finition": "or_transparent"}
                       for i in range(1, nombre + 1)], **extra}


class Circuit:
    """Les acteurs du circuit d'approvisionnement, chacun avec sa propre session."""

    def __init__(self, client, en_tant_que, base):
        self.client, self.en_tant_que, self.base = client, en_tant_que, base

    def appeler(self, profil, methode, chemin, attendu=None, **corps):
        reponse = self.client.request(methode, chemin, headers=self.en_tant_que(profil), **corps)
        if attendu is not None:
            assert reponse.status_code == attendu, (methode, chemin, reponse.status_code, reponse.text)
        return reponse

    def commande(self, profil="responsable_stock", **extra) -> dict:
        return self.appeler(profil, "POST", "/api/commandes-achat", 201, json=_commande(self.base, **extra)).json()

    def etape(self, profil, commande, action, attendu=200, **corps) -> dict:
        return self.appeler(profil, "POST", f"/api/commandes-achat/{commande['id']}/{action}", attendu,
                            json=corps or None).json()

    def commande_passee(self, **extra) -> dict:
        commande = self.commande(**extra)
        self.etape("responsable_stock", commande, "soumettre")
        self.etape("dg", commande, "valider")
        return self.etape("responsable_stock", commande, "commander")

    def packing_list(self, reference="CONT-CN-01", nombre=5, attendu=201, **extra) -> dict:
        return self.appeler("responsable_stock", "POST", "/api/imports-colisage", attendu,
                            json=_packing_list(self.base, reference, nombre, **extra)).json()

    def lignes(self, commande) -> dict:
        return {ligne["article_code"]: ligne["id"] for ligne in commande["lignes"]}

    def arrivee(self, commande, importation=None, tubes=5000, attendu=201, **extra) -> dict:
        ids = self.lignes(commande)
        lignes = []
        if importation is not None:
            lignes.append({"ligne_commande_id": ids["JUMBO"]})
        if tubes:
            lignes.append({"ligne_commande_id": ids["TUBE-45"], "quantite_recue": tubes})
        corps = {"date_arrivee": AUJOURD_HUI, "numero_facture": "FAC-CN-77", "lignes": lignes, **extra}
        if importation is not None:
            corps["import_colisage_id"] = importation["id"]
        return self.appeler("responsable_stock", "POST", f"/api/commandes-achat/{commande['id']}/receptions",
                            attendu, json=corps).json()

    def controle(self, reception, decision="acceptee", acceptees=None, documents=True, commentaire=None,
                 attendu=200, refusees=None, motifs=None) -> dict:
        acceptees, refusees, motifs = acceptees or {}, refusees or {}, motifs or {}
        lignes = [{"ligne_reception_id": ligne["id"],
                   "quantite_acceptee": acceptees.get(ligne["article_code"], ligne["quantite_recue"]),
                   "bobines_refusees": refusees.get(ligne["article_code"], []),
                   **({"motif_ecart": motifs[ligne["article_code"]]} if ligne["article_code"] in motifs else {})}
                  for ligne in reception["lignes"]]
        corps = {"decision": decision, "controle_documentaire_ok": documents, "lignes": lignes}
        if commentaire:
            corps["commentaire"] = commentaire
        return self.appeler("responsable_stock", "POST", f"/api/receptions-achat/{reception['id']}/controle",
                            attendu, json=corps).json()


@pytest.fixture
def circuit(client, en_tant_que, base):
    return Circuit(client, en_tant_que, base)


def _solde(client, article) -> dict:
    return client.get("/api/stock/soldes", params={"article_id": str(article.id)}).json()[0]


# --- Droits : chaque route, chaque profil -------------------------------------------------------------------


ROUTES = [
    ("GET", "/api/commandes-achat/{id}", "achats.consulter", None),
    ("PUT", "/api/commandes-achat/{id}", "achats.saisir", {"commentaire": "x"}),
    ("POST", "/api/commandes-achat/{id}/soumettre", "achats.saisir", None),
    ("POST", "/api/commandes-achat/{id}/valider", "achats.valider", None),
    ("POST", "/api/commandes-achat/{id}/refuser", "achats.valider", {"motif": "Prix trop élevé"}),
    ("POST", "/api/commandes-achat/{id}/commander", "achats.saisir", None),
    ("POST", "/api/commandes-achat/{id}/solder", "achats.saisir", {"motif": "Reliquat abandonné"}),
    ("POST", "/api/commandes-achat/{id}/receptions", "stock.saisir",
     {"date_arrivee": AUJOURD_HUI, "lignes": [{"ligne_commande_id": str(uuid.uuid4()), "quantite_recue": 1}]}),
    ("GET", "/api/receptions-achat/{id}", "achats.consulter", None),
    ("POST", "/api/receptions-achat/{id}/controle", "stock.valider_reception",
     {"decision": "acceptee", "controle_documentaire_ok": True,
      "lignes": [{"ligne_reception_id": str(uuid.uuid4()), "quantite_acceptee": 1}]}),
]


@pytest.mark.parametrize("role", ROLES)
def test_chaque_etape_exige_son_propre_droit(client, en_tant_que, base, role):
    entetes = en_tant_que(role)
    inconnu = uuid.uuid4()
    for methode, chemin, permission, corps in ROUTES:
        reponse = client.request(methode, chemin.format(id=inconnu), headers=entetes, json=corps)
        attendu = 404 if a_la_permission(role, permission) else 403
        assert reponse.status_code == attendu, (role, methode, chemin, reponse.status_code)
    assert (client.get("/api/commandes-achat").status_code == 200) == a_la_permission(role, "achats.consulter")
    assert (client.get("/api/receptions-achat").status_code == 200) == a_la_permission(role, "achats.consulter")
    creation = client.post("/api/commandes-achat", headers=entetes, json=_commande(base))
    assert (creation.status_code == 201) == a_la_permission(role, "achats.saisir"), role


def test_qui_fait_quoi_dans_le_circuit_d_approvisionnement():
    assert a_la_permission("responsable_stock", "achats.saisir")
    assert a_la_permission("responsable_stock", "stock.valider_reception")
    assert not a_la_permission("responsable_stock", "achats.valider")
    assert a_la_permission("dg", "achats.valider")
    assert not a_la_permission("dg", "achats.saisir")
    assert a_la_permission("comptable", "achats.consulter")
    assert not a_la_permission("comptable", "achats.saisir")
    assert not a_la_permission("chef_production", "achats.consulter")


def test_sans_session_tout_est_refuse(client):
    assert client.get("/api/commandes-achat").status_code == 401
    assert client.get("/api/receptions-achat").status_code == 401


# --- Le circuit complet : de la commande a l'entree en stock ---------------------------------------------------------


def test_circuit_complet_commande_arrivee_controle_stock(client, circuit, base, db):
    # 1. Preparation de la commande pour la Chine.
    commande = circuit.commande()
    assert commande["numero"] == f"BCA-{date.today().year}-00001" and commande["statut"] == "brouillon"
    assert commande["montant_total"] == 5 * 1450 + 5000 * 0.12 and commande["prix_manquants"] == 0
    assert [ligne["solde"] for ligne in commande["lignes"]] == [5.0, 5000.0]

    commande = circuit.etape("responsable_stock", commande, "soumettre")
    assert commande["statut"] == "soumise"
    commande = circuit.etape("dg", commande, "valider")
    assert commande["statut"] == "validee" and commande["valide_par"] is not None
    commande = circuit.etape("responsable_stock", commande, "commander", reference_fournisseur="PI-2026-088")
    assert commande["statut"] == "commandee" and commande["reference_fournisseur"] == "PI-2026-088"

    attendues = circuit.appeler("responsable_stock", "GET", "/api/commandes-achat",
                                params={"en_attente_marchandise": "true"}).json()
    assert [c["numero"] for c in attendues] == [commande["numero"]]

    # 2. Le conteneur arrive : la packing list est analysee, la reception enregistree. Rien en stock.
    packing = circuit.packing_list()
    reception = circuit.arrivee(commande, packing)
    assert reception["statut"] == "en_controle" and reception["conteneur_reference"] == "CONT-CN-01"
    assert {ligne["article_code"]: ligne["quantite_recue"] for ligne in reception["lignes"]} == {
        "JUMBO": 5.0, "TUBE-45": 5000.0}
    assert _solde(client, base["jumbo"])["physique"] == 0.0 and _solde(client, base["tube"])["physique"] == 0.0
    assert client.get("/api/lots").json() == []

    # 3. Controle de conformite : seul lui fait entrer la marchandise en stock.
    controlee = circuit.controle(reception)
    assert controlee["statut"] == "acceptee" and controlee["lot_id"] is not None
    assert controlee["controle_par"] is not None and controlee["avec_ecarts"] is False
    assert _solde(client, base["jumbo"])["physique"] == 5.0
    assert _solde(client, base["tube"])["physique"] == 5000.0
    assert len(client.get("/api/bobines", params={"lot_id": controlee["lot_id"]}).json()) == 5
    assert client.get(f"/api/imports-colisage/{packing['id']}").json()["statut"] == "valide"

    finale = client.get(f"/api/commandes-achat/{commande['id']}").json()
    assert finale["statut"] == "recue" and [ligne["solde"] for ligne in finale["lignes"]] == [0.0, 0.0]
    assert [t["vers_statut"] for t in finale["transitions"]] == [
        "brouillon", "soumise", "validee", "commandee", "recue"]
    actions = set(db.scalars(select(JournalAudit.action)))
    assert {"commandes_achat.creation", "receptions_achat.creation", "receptions_achat.modification",
            "lots.creation", "mouvements_stock.creation"} <= actions


def test_numerotation_des_commandes_et_receptions(circuit):
    premiere, seconde = circuit.commande(), circuit.commande()
    annee = date.today().year
    assert (premiere["numero"], seconde["numero"]) == (f"BCA-{annee}-00001", f"BCA-{annee}-00002")


# --- Preparation de la commande -----------------------------------------------------------------------------------------


def test_commande_refusee_selon_les_regles(client, en_tant_que, base, db):
    entetes = en_tant_que("responsable_stock")

    def tenter(**surcharge):
        return client.post("/api/commandes-achat", headers=entetes, json=_commande(base) | surcharge)

    ligne = {"article_id": str(base["tube"].id), "quantite_commandee": 10}
    assert tenter(lignes=[]).status_code == 422
    assert tenter(lignes=[{**ligne, "quantite_commandee": 0}]).status_code == 422
    assert tenter(lignes=[{**ligne, "prix_unitaire": -1}]).status_code == 422
    assert tenter(devise="BTC").status_code == 422
    assert tenter(statut="validee").status_code == 422
    assert tenter(fournisseur_id=str(uuid.uuid4())).status_code == 400
    doublon = tenter(lignes=[ligne, ligne])
    assert doublon.status_code == 400 and "qu'une seule fois" in doublon.json()["detail"]
    fini = tenter(lignes=[{"article_id": str(base["produit"].id), "quantite_commandee": 5}])
    assert fini.status_code == 400 and "produit fini" in fini.json()["detail"]
    finition = tenter(lignes=[{**ligne, "couleur_finition": "kaki_simple"}])
    assert finition.status_code == 400 and "bobines" in finition.json()["detail"]
    assert tenter(lignes=[{**ligne, "article_id": str(uuid.uuid4())}]).status_code == 400
    base["chine"].actif = False
    db.commit()
    assert tenter().status_code == 400


def test_prix_manquants_signales_au_dg(circuit, base):
    commande = circuit.commande(lignes=[
        {"article_id": str(base["tube"].id), "quantite_commandee": 1000, "prix_unitaire": "0.10"},
        {"article_id": str(base["jumbo"].id), "quantite_commandee": 5}])
    assert commande["montant_total"] == 100.0 and commande["prix_manquants"] == 1


def test_brouillon_modifiable_puis_fige(circuit, base, client, en_tant_que):
    commande = circuit.commande()
    entetes = en_tant_que("responsable_stock")
    nouvelle = client.put(f"/api/commandes-achat/{commande['id']}", headers=entetes, json={
        "commentaire": "Quantité revue", "lignes": [
            {"article_id": str(base["tube"].id), "quantite_commandee": 8000, "prix_unitaire": "0.11"}]})
    assert nouvelle.status_code == 200
    assert [(ligne["article_code"], ligne["quantite_commandee"]) for ligne in nouvelle.json()["lignes"]] == [
        ("TUBE-45", 8000.0)]
    assert nouvelle.json()["commentaire"] == "Quantité revue"
    assert client.put(f"/api/commandes-achat/{commande['id']}", headers=entetes,
                      json={"statut": "validee"}).status_code == 422
    assert client.put(f"/api/commandes-achat/{commande['id']}", headers=entetes,
                      json={"lignes": []}).status_code == 422
    circuit.etape("responsable_stock", commande, "soumettre")
    gele = client.put(f"/api/commandes-achat/{commande['id']}", headers=en_tant_que("responsable_stock"),
                      json={"commentaire": "Trop tard"})
    assert gele.status_code == 409


# --- Machine a etats : aucun saut ----------------------------------------------------------------------------------------


def test_aucun_saut_d_etat_sur_la_commande(circuit):
    commande = circuit.commande()
    circuit.etape("dg", commande, "valider", attendu=409)  # pas encore soumise
    circuit.etape("responsable_stock", commande, "commander", attendu=409)
    circuit.appeler("responsable_stock", "POST", f"/api/commandes-achat/{commande['id']}/receptions", 409,
                    json={"date_arrivee": AUJOURD_HUI, "lignes": [
                        {"ligne_commande_id": commande["lignes"][0]["id"], "quantite_recue": 1}]})
    circuit.etape("responsable_stock", commande, "soumettre")
    circuit.etape("responsable_stock", commande, "soumettre", attendu=409)
    circuit.etape("responsable_stock", commande, "commander", attendu=409)  # encore a valider
    circuit.etape("dg", commande, "valider")
    circuit.etape("dg", commande, "valider", attendu=409)
    circuit.etape("dg", commande, "refuser", attendu=409, motif="Trop tard pour refuser")
    circuit.etape("responsable_stock", commande, "solder", attendu=409, motif="Rien n'est arrivé")


def test_le_refus_du_dg_est_motive_et_definitif(circuit):
    commande = circuit.commande()
    circuit.etape("responsable_stock", commande, "soumettre")
    circuit.etape("dg", commande, "refuser", attendu=422)
    circuit.etape("dg", commande, "refuser", attendu=422, motif="non")
    refusee = circuit.etape("dg", commande, "refuser", motif="Budget dépassé ce trimestre")
    assert refusee["statut"] == "refusee" and refusee["motif_decision"].startswith("Budget")
    circuit.etape("dg", commande, "valider", attendu=409)
    circuit.etape("responsable_stock", commande, "commander", attendu=409)


def test_annulation_selon_l_etat_et_le_role(circuit):
    commande = circuit.commande()
    # Brouillon : l'initiateur retire sa propre demande.
    assert circuit.etape("responsable_stock", commande, "annuler", motif="Besoin disparu")["statut"] == "annulee"
    circuit.etape("responsable_stock", commande, "annuler", attendu=409, motif="Deuxième annulation")

    passee = circuit.commande_passee()
    # Apres autorisation du DG, seul le DG peut annuler.
    circuit.etape("responsable_stock", passee, "annuler", attendu=403, motif="Je ne devrais pas pouvoir")
    circuit.etape("comptable", passee, "annuler", attendu=403, motif="Pas mon role")
    circuit.etape("dg", passee, "annuler", attendu=422)
    assert circuit.etape("dg", passee, "annuler", motif="Fournisseur défaillant")["statut"] == "annulee"


def test_la_base_impose_un_valideur_different_de_l_initiateur(circuit, db, creer_compte, en_tant_que, base):
    """Le DG ne saisit pas en temps normal ; on simule une commande saisie par lui."""
    dg = creer_compte("dg", "dg.auteur")
    commande = achats.creer(db, dg, _commande(base) | {
        "fournisseur_id": base["chine"].id, "date_arrivee_prevue": None,
        "lignes": [{"article_id": base["tube"].id, "quantite_commandee": Decimal(10)}]})
    achats.soumettre(db, dg, commande.id)
    from tests.conftest import se_connecter
    circuit.client.cookies.clear()
    csrf = {"X-CSRF-Token": se_connecter(circuit.client, "dg.auteur")}
    refus = circuit.client.post(f"/api/commandes-achat/{commande.id}/valider", headers=csrf)
    assert refus.status_code == 403 and "autre personne" in refus.json()["detail"]
    # Le refus ne laisse aucune trace d'etat : la commande attend toujours un autre valideur.
    db.expire_all()
    assert db.get(CommandeAchat, commande.id).statut == "soumise"
    assert db.get(CommandeAchat, commande.id).valide_par is None
    # Defense en profondeur : meme un UPDATE direct est refuse par la base.
    with pytest.raises(DBAPIError, match="valideur_distinct"), db.begin_nested():
        db.execute(text(f"UPDATE commandes_achat SET valide_par = cree_par WHERE id = '{commande.id}'"))


# --- Reception de la marchandise -------------------------------------------------------------------------------------------


def test_reception_partielle_puis_solde(client, circuit, base):
    commande = circuit.commande_passee()
    premiere = circuit.arrivee(commande, tubes=3000, importation=None) if False else None
    ids = circuit.lignes(commande)
    premiere = circuit.appeler("responsable_stock", "POST", f"/api/commandes-achat/{commande['id']}/receptions", 201,
                               json={"date_arrivee": AUJOURD_HUI, "lignes": [
                                   {"ligne_commande_id": ids["TUBE-45"], "quantite_recue": 3000}]}).json()
    assert premiere["lignes"][0]["solde_avant"] == 5000.0
    circuit.controle(premiere)
    partielle = client.get(f"/api/commandes-achat/{commande['id']}").json()
    assert partielle["statut"] == "partiellement_recue"
    assert {ligne["article_code"]: ligne["solde"] for ligne in partielle["lignes"]} == {"JUMBO": 5.0,
                                                                                         "TUBE-45": 2000.0}
    assert _solde(client, base["tube"])["physique"] == 3000.0

    packing = circuit.packing_list()
    seconde = circuit.arrivee(commande, packing, tubes=2000)
    assert {ligne["article_code"]: ligne["solde_avant"] for ligne in seconde["lignes"]} == {
        "JUMBO": 5.0, "TUBE-45": 2000.0}
    circuit.controle(seconde)
    assert client.get(f"/api/commandes-achat/{commande['id']}").json()["statut"] == "recue"
    assert _solde(client, base["tube"])["physique"] == 5000.0


def test_solder_une_commande_partiellement_livree(client, circuit):
    commande = circuit.commande_passee()
    reception = circuit.appeler("responsable_stock", "POST", f"/api/commandes-achat/{commande['id']}/receptions",
                                201, json={"date_arrivee": AUJOURD_HUI, "lignes": [
                                    {"ligne_commande_id": circuit.lignes(commande)["TUBE-45"],
                                     "quantite_recue": 1000}]}).json()
    circuit.etape("responsable_stock", commande, "solder", attendu=409, motif="Reliquat abandonné")  # pas livree
    circuit.controle(reception)
    circuit.etape("responsable_stock", commande, "solder", attendu=422)
    soldee = circuit.etape("responsable_stock", commande, "solder", motif="Reliquat annulé avec le fournisseur")
    assert soldee["statut"] == "cloturee" and soldee["motif_decision"].startswith("Reliquat")
    circuit.arrivee(commande, None, tubes=10, attendu=409)


def test_une_reception_qui_attend_son_controle_bloque_solde_et_annulation(circuit):
    commande = circuit.commande_passee()
    circuit.arrivee(commande, tubes=1000)
    circuit.etape("dg", commande, "annuler", attendu=409, motif="Annulation pendant le contrôle")


def test_receptions_refusees_selon_les_regles(circuit, base, db):
    commande = circuit.commande_passee()
    ids = circuit.lignes(commande)
    base_corps = {"date_arrivee": AUJOURD_HUI}

    def tenter(attendu, **corps):
        return circuit.appeler("responsable_stock", "POST", f"/api/commandes-achat/{commande['id']}/receptions",
                               attendu, json=base_corps | corps).json()

    tenter(422, lignes=[])
    tenter(422, lignes=[{"ligne_commande_id": ids["TUBE-45"], "quantite_recue": 0}])
    tenter(422, date_arrivee=str(date.today() + timedelta(days=2)),
           lignes=[{"ligne_commande_id": ids["TUBE-45"], "quantite_recue": 5}])
    assert "étrangère" in tenter(400, lignes=[{"ligne_commande_id": str(uuid.uuid4()), "quantite_recue": 5}])["detail"]
    assert "qu'une fois" in tenter(400, lignes=[{"ligne_commande_id": ids["TUBE-45"], "quantite_recue": 5}] * 2)[
        "detail"]
    assert "Quantité reçue manquante" in tenter(400, lignes=[{"ligne_commande_id": ids["TUBE-45"]}])["detail"]
    # Les bobines se receptionnent avec leur packing list, et seulement elles.
    assert "packing list" in tenter(400, lignes=[{"ligne_commande_id": ids["JUMBO"]}])["detail"]
    packing = circuit.packing_list()
    assert "aucune ligne de bobines" in tenter(
        400, import_colisage_id=packing["id"], lignes=[{"ligne_commande_id": ids["TUBE-45"], "quantite_recue": 5}]
    )["detail"]


def test_la_packing_list_doit_correspondre_a_la_commande(circuit, base):
    commande = circuit.commande_passee()
    ids = circuit.lignes(commande)
    ligne_bobines = [{"ligne_commande_id": ids["JUMBO"]}]

    def tenter(importation, attendu):
        return circuit.appeler("responsable_stock", "POST", f"/api/commandes-achat/{commande['id']}/receptions",
                               attendu, json={"date_arrivee": AUJOURD_HUI, "import_colisage_id": importation["id"],
                                              "lignes": ligne_bobines})

    autre_fournisseur = circuit.packing_list("CONT-AUTRE", fournisseur_id=str(base["autre"].id))
    assert "autre fournisseur" in tenter(autre_fournisseur, 400).json()["detail"]
    avec_anomalie = circuit.packing_list("CONT-ANOMALIE") | {}
    mauvaise = _packing_list(base, "CONT-DOUBLON")
    mauvaise["lignes"][1]["numero_fournisseur"] = "1"
    bloquee = circuit.appeler("responsable_stock", "POST", "/api/imports-colisage", 201, json=mauvaise).json()
    assert "anomalie(s) bloquante(s)" in tenter(bloquee, 400).json()["detail"]
    assert avec_anomalie
    bonne = circuit.packing_list("CONT-BONNE")
    assert tenter(bonne, 201).status_code == 201
    assert tenter(bonne, 409).status_code == 409  # deja rattachee a une reception


def test_une_packing_list_rattachee_ne_se_valide_pas_a_cote_du_controle(circuit, client):
    commande = circuit.commande_passee()
    packing = circuit.packing_list()
    circuit.arrivee(commande, packing)
    circuit.appeler("responsable_stock", "POST", f"/api/imports-colisage/{packing['id']}/valider", 409)
    circuit.appeler("responsable_stock", "POST", f"/api/imports-colisage/{packing['id']}/annuler", 409)
    assert client.get("/api/lots").json() == []


def test_avertissements_a_lire_avant_de_controler(circuit):
    commande = circuit.commande_passee()
    packing = circuit.packing_list(lignes=None) if False else None
    mixte = _packing_list(circuit.base, "CONT-MIXTE")
    mixte["lignes"][0]["couleur_finition"] = "kaki_simple"
    del mixte["lignes"][1]["metrage_propre"]
    importation = circuit.appeler("responsable_stock", "POST", "/api/imports-colisage", 201, json=mixte).json()
    reception = circuit.arrivee(commande, importation, tubes=6000)
    notes = " | ".join(reception["avertissements"])
    assert "TUBE-45 : 6000 piece reçu(s) pour un solde de 5000" in notes  # plus que le solde, sans decimales
    assert "avertissement(s)" in notes  # packing list : metrage manquant
    assert "finition commandée" in notes and packing is None


# --- Controle de conformite --------------------------------------------------------------------------------------------------------


def test_controle_avec_reserves_bobine_refusee_et_quantite_reduite(client, circuit, base):
    commande = circuit.commande_passee()
    reception = circuit.arrivee(circuit.appeler("responsable_stock", "GET",
                                                f"/api/commandes-achat/{commande['id']}").json(),
                                circuit.packing_list())
    # Ecart + decision "acceptee" : refuse, il faut l'avouer.
    erreur = circuit.controle(reception, "acceptee", acceptees={"TUBE-45": 4800}, attendu=400)
    assert "avec réserves" in erreur["detail"]
    circuit.controle(reception, "acceptee_avec_reserves", acceptees={"TUBE-45": 4800}, attendu=400,
                     commentaire="Tubes écrasés dans deux cartons")  # motif d'ecart manquant
    circuit.controle(reception, "acceptee_avec_reserves", acceptees={"TUBE-45": 4800}, attendu=400,
                     motifs={"TUBE-45": "200 tubes écrasés"})  # commentaire manquant
    controlee = circuit.controle(
        reception, "acceptee_avec_reserves", acceptees={"TUBE-45": 4800}, documents=False,
        refusees={"JUMBO": ["2"]}, motifs={"TUBE-45": "200 tubes écrasés", "JUMBO": "Colis éventré"},
        commentaire="Facture absente du conteneur ; bobine 2 endommagée")
    assert controlee["statut"] == "acceptee_avec_reserves" and controlee["avec_ecarts"] is True
    assert controlee["controle_documentaire_ok"] is False
    assert _solde(client, base["tube"])["physique"] == 4800.0
    assert _solde(client, base["jumbo"])["physique"] == 4.0
    numeros = sorted(b["numero_fournisseur"] for b in client.get("/api/bobines", params={
        "lot_id": controlee["lot_id"]}).json())
    assert numeros == ["1", "3", "4", "5"]  # la bobine 2 n'est jamais entree en stock
    lignes = {ligne["article_code"]: ligne for ligne in controlee["lignes"]}
    assert lignes["JUMBO"]["quantite_acceptee"] == 4.0 and lignes["JUMBO"]["bobines_refusees"] == ["2"]
    assert lignes["TUBE-45"]["motif_ecart"] == "200 tubes écrasés"

    suivi = client.get(f"/api/commandes-achat/{commande['id']}").json()
    assert suivi["statut"] == "partiellement_recue"
    assert {ligne["article_code"]: ligne["solde"] for ligne in suivi["lignes"]} == {"JUMBO": 1.0, "TUBE-45": 200.0}
    litiges = client.get("/api/receptions-achat", params={"avec_ecarts": "true"}).json()
    assert [r["id"] for r in litiges] == [controlee["id"]]


def test_reception_refusee_rien_n_entre_en_stock(client, circuit, base):
    commande = circuit.commande_passee()
    packing = circuit.packing_list()
    reception = circuit.arrivee(commande, packing)
    circuit.controle(reception, "refusee", attendu=400)  # un refus se motive
    refusee = circuit.controle(reception, "refusee", commentaire="Conteneur ne correspond pas à la commande")
    assert refusee["statut"] == "refusee" and refusee["lot_id"] is None
    assert all(ligne["quantite_acceptee"] == 0 for ligne in refusee["lignes"])
    assert _solde(client, base["jumbo"])["physique"] == 0.0 and _solde(client, base["tube"])["physique"] == 0.0
    assert client.get(f"/api/commandes-achat/{commande['id']}").json()["statut"] == "commandee"
    # La packing list est libre : le conteneur pourra etre re-analyse et re-presente.
    assert client.get(f"/api/imports-colisage/{packing['id']}").json()["statut"] == "annule"
    circuit.packing_list("CONT-CN-01", 5)


def test_toutes_les_bobines_refusees_avec_reserves(client, circuit, base):
    commande = circuit.commande_passee()
    reception = circuit.arrivee(commande, circuit.packing_list(nombre=2), tubes=0)
    controlee = circuit.controle(reception, "acceptee_avec_reserves", refusees={"JUMBO": ["1", "2"]},
                                 motifs={"JUMBO": "Humidité"}, commentaire="Deux bobines mouillées",
                                 documents=True)
    assert controlee["lot_id"] is None and _solde(client, base["jumbo"])["physique"] == 0.0
    assert client.get("/api/lots").json() == []


def test_controle_refuse_selon_les_regles(circuit):
    commande = circuit.commande_passee()
    reception = circuit.arrivee(commande, circuit.packing_list())
    ligne_jumbo = next(ligne for ligne in reception["lignes"] if ligne["article_code"] == "JUMBO")
    ligne_tube = next(ligne for ligne in reception["lignes"] if ligne["article_code"] == "TUBE-45")

    def tenter(lignes, decision="acceptee", **extra):
        return circuit.appeler("responsable_stock", "POST", f"/api/receptions-achat/{reception['id']}/controle",
                               json={"decision": decision, "controle_documentaire_ok": True, "lignes": lignes,
                                     **extra})

    complet = [{"ligne_reception_id": ligne_jumbo["id"], "quantite_acceptee": 5},
               {"ligne_reception_id": ligne_tube["id"], "quantite_acceptee": 5000}]
    assert "exactement une fois" in tenter(complet[:1]).json()["detail"]
    assert "exactement une fois" in tenter(complet + complet[:1]).json()["detail"]
    assert tenter([{**complet[0], "ligne_reception_id": str(uuid.uuid4())}, complet[1]]).status_code == 400
    assert "supérieure" in tenter([complet[0], {**complet[1], "quantite_acceptee": 5001}]).json()["detail"]
    assert tenter([complet[0], {**complet[1], "quantite_acceptee": -1}]).status_code == 422
    assert "absente(s)" in tenter([{**complet[0], "bobines_refusees": ["999"]}, complet[1]],
                                  "acceptee_avec_reserves", commentaire="Bobine inconnue").json()["detail"]
    assert "ne s'appliquent qu'aux bobines" in tenter(
        [complet[0], {**complet[1], "bobines_refusees": ["1"]}], "acceptee_avec_reserves",
        commentaire="Mauvaise ligne").json()["detail"]
    assert "Aucun écart" in tenter(complet, "acceptee_avec_reserves", commentaire="Tout est bon").json()["detail"]
    assert tenter(complet, "inconnue").status_code == 422
    # Aucune de ces tentatives n'a rien change.
    detail = circuit.appeler("responsable_stock", "GET", f"/api/receptions-achat/{reception['id']}").json()
    assert detail["statut"] == "en_controle"
    assert all(ligne["quantite_acceptee"] is None for ligne in detail["lignes"])


def test_le_controle_est_definitif(circuit, client):
    commande = circuit.commande_passee()
    reception = circuit.arrivee(commande, circuit.packing_list())
    circuit.controle(reception)
    circuit.controle(reception, attendu=409)
    circuit.controle(reception, "refusee", attendu=409, commentaire="Revenir sur la décision")
    assert _solde(client, circuit.base["tube"])["physique"] == 5000.0


def test_seul_le_responsable_stock_controle(circuit):
    commande = circuit.commande_passee()
    reception = circuit.arrivee(commande, circuit.packing_list())
    corps = {"decision": "acceptee", "controle_documentaire_ok": True,
             "lignes": [{"ligne_reception_id": ligne["id"], "quantite_acceptee": ligne["quantite_recue"]}
                        for ligne in reception["lignes"]]}
    for profil in ("dg", "comptable", "chef_production", "directeur_commercial", "administrateur"):
        assert circuit.appeler(profil, "POST", f"/api/receptions-achat/{reception['id']}/controle",
                               json=corps).status_code == 403, profil


# --- Lecture, isolation, protections en base -------------------------------------------------------------------------------------


def test_conteneurs_attendus_les_plus_proches_d_abord(circuit):
    loin = circuit.commande_passee(date_arrivee_prevue="2027-02-01")
    proche = circuit.commande_passee(date_arrivee_prevue="2026-12-01")
    circuit.commande_passee(date_arrivee_prevue=None)
    circuit.commande()  # brouillon : pas attendue
    attendues = circuit.appeler("dg", "GET", "/api/commandes-achat", params={"en_attente_marchandise": "true"}).json()
    assert [c["numero"] for c in attendues[:2]] == [proche["numero"], loin["numero"]] and len(attendues) == 3
    assert len(circuit.appeler("dg", "GET", "/api/commandes-achat", params={"statut": "brouillon"}).json()) == 1
    assert circuit.appeler("dg", "GET", "/api/commandes-achat", params={"statut": "inconnu"}).status_code == 422


def test_isolation_entre_entreprises(client, circuit, db, base, en_tant_que):
    commande = circuit.commande()
    autre = Entreprise(nom="Autre usine achats")
    db.add(autre)
    db.flush()
    fournisseur = Fournisseur(entreprise_id=autre.id, code="F-ETRANGER", nom="Fournisseur étranger")
    db.add(fournisseur)
    db.flush()
    etrangere = CommandeAchat(entreprise_id=autre.id, numero="BCA-X-1", fournisseur_id=fournisseur.id, devise="USD")
    db.add(etrangere)
    db.commit()
    en_tant_que("responsable_stock")
    assert [c["id"] for c in client.get("/api/commandes-achat").json()] == [commande["id"]]
    assert client.get(f"/api/commandes-achat/{etrangere.id}").status_code == 404
    assert client.get(f"/api/receptions-achat/{etrangere.id}").status_code == 404


@pytest.mark.parametrize("requete", [
    "DELETE FROM commandes_achat", "TRUNCATE commandes_achat", "DELETE FROM receptions_achat",
    "DELETE FROM lignes_reception_achat", "UPDATE transitions_commande_achat SET vers_statut = 'recue'",
    "DELETE FROM transitions_commande_achat", "TRUNCATE lignes_commande_achat",
])
def test_le_compte_applicatif_ne_peut_ni_supprimer_ni_reecrire_l_historique(db, requete):
    with pytest.raises(DBAPIError, match="permission denied"), db.begin_nested():
        db.execute(text(requete))


def test_les_lignes_d_une_commande_soumise_sont_figees_en_base(circuit, db, proprietaire):
    commande = circuit.commande()
    circuit.etape("responsable_stock", commande, "soumettre")
    ligne = commande["lignes"][0]["id"]
    for requete in (f"UPDATE lignes_commande_achat SET quantite_commandee = 9999 WHERE id = '{ligne}'",
                    f"DELETE FROM lignes_commande_achat WHERE id = '{ligne}'",
                    "INSERT INTO lignes_commande_achat (id, commande_id, rang, article_id, quantite_commandee) "
                    f"VALUES (gen_random_uuid(), '{commande['id']}', 99, '{circuit.base['tube'].id}', 1)"):
        with pytest.raises(DBAPIError, match="figees"), db.begin_nested():
            db.execute(text(requete))
        with proprietaire(), pytest.raises(DBAPIError, match="figees"), db.begin_nested():
            db.execute(text(requete))  # meme le proprietaire du schema


def test_une_reception_controlee_ne_se_rouvre_pas_en_base(circuit, db, proprietaire):
    commande = circuit.commande_passee()
    reception = circuit.arrivee(commande, circuit.packing_list())
    circuit.controle(reception)
    ligne = reception["lignes"][0]["id"]
    for requete in (f"UPDATE receptions_achat SET statut = 'en_controle', controle_par = NULL "
                    f"WHERE id = '{reception['id']}'",
                    f"UPDATE lignes_reception_achat SET quantite_acceptee = 1 WHERE id = '{ligne}'"):
        with pytest.raises(DBAPIError, match="controlee|definitive"), db.begin_nested():
            db.execute(text(requete))
        with proprietaire(), pytest.raises(DBAPIError, match="controlee|definitive"), db.begin_nested():
            db.execute(text(requete))


def test_une_commande_motivee_en_base(circuit, db):
    commande = circuit.commande()
    with pytest.raises(DBAPIError, match="decision_motivee"), db.begin_nested():
        db.execute(text(f"UPDATE commandes_achat SET statut = 'refusee' WHERE id = '{commande['id']}'"))


def test_le_lot_et_les_bobines_viennent_bien_du_controle(circuit, db):
    commande = circuit.commande_passee()
    circuit.arrivee(commande, circuit.packing_list())
    assert db.scalar(select(Lot)) is None and db.scalar(select(Bobine)) is None  # rien avant le controle
    importation = db.scalar(select(ImportColisage))
    assert importation.statut == "brouillon" and importation.rattache_reception is True


# --- Catalogue fournisseur ------------------------------------------------------------------------


def _entree_catalogue(base, code="JUMBO-OR-G01", **extra) -> dict:
    return {"fournisseur_id": str(base["chine"].id), "article_id": str(base["jumbo"].id), "code": code,
            "libelle": "Bobine BOPP or transparent — Golden01", "couleur_finition": "or_transparent",
            "reference_couleur_fournisseur": "Golden01", "poids_net_type_kg": "251.67",
            "metrage_type_m": "4006.75", **extra}


@pytest.mark.parametrize("role", ROLES)
def test_droits_du_catalogue_fournisseur(client, en_tant_que, base, role):
    entetes = en_tant_que(role)
    assert client.get("/api/catalogue-fournisseur", headers=entetes).status_code == (
        200 if a_la_permission(role, "achats.consulter") else 403)
    ecriture = client.post("/api/catalogue-fournisseur", headers=entetes, json=_entree_catalogue(base, f"C-{ROLES.index(role)}"))
    assert ecriture.status_code == (201 if a_la_permission(role, "achats.saisir") else 403), role


def test_catalogue_creation_lecture_modification_et_desactivation(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    cree = client.post("/api/catalogue-fournisseur", headers=entetes, json=_entree_catalogue(base))
    assert cree.status_code == 201
    corps = cree.json()
    assert (corps["article_code"], corps["unite"], corps["poids_net_type_kg"], corps["actif"]) == (
        "JUMBO", "rouleau", 251.67, True)
    # Doublon de code chez le meme fournisseur : refuse ; chez un autre fournisseur : autorise.
    assert client.post("/api/catalogue-fournisseur", headers=entetes, json=_entree_catalogue(base)).status_code == 409
    autre = _entree_catalogue(base) | {"fournisseur_id": str(base["autre"].id)}
    assert client.post("/api/catalogue-fournisseur", headers=entetes, json=autre).status_code == 201
    liste = client.get("/api/catalogue-fournisseur", headers=entetes,
                       params={"fournisseur_id": str(base["chine"].id)}).json()
    assert [e["code"] for e in liste] == ["JUMBO-OR-G01"]
    # Desactivation : l'entree reste lisible, mais disparait des listes "actives".
    maj = client.patch(f"/api/catalogue-fournisseur/{corps['id']}", headers=entetes, json={"actif": False})
    assert maj.status_code == 200 and maj.json()["actif"] is False
    assert client.get("/api/catalogue-fournisseur", headers=entetes,
                      params={"fournisseur_id": str(base["chine"].id), "actif": True}).json() == []
    assert client.patch(f"/api/catalogue-fournisseur/{corps['id']}", headers=entetes,
                        json={"libelle": None}).status_code == 422


def test_catalogue_range_le_code_en_majuscules(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    reponse = client.post("/api/catalogue-fournisseur", headers=entetes,
                          json=_entree_catalogue(base, "  tube-45.std ") | {"article_id": str(base["tube"].id),
                                                                              "couleur_finition": None})
    assert reponse.status_code == 201, reponse.text
    assert reponse.json()["code"] == "TUBE-45.STD"
    # Meme code, autre casse : c'est un doublon.
    doublon = client.post("/api/catalogue-fournisseur", headers=entetes,
                          json=_entree_catalogue(base, "Tube-45.Std") | {"article_id": str(base["tube"].id),
                                                                         "couleur_finition": None})
    assert doublon.status_code == 409


def test_catalogue_refuse_les_entrees_incoherentes(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    for extra, attendu in (
        ({"article_id": str(base["produit"].id)}, 400),            # un produit fini ne s'achete pas
        ({"couleur_finition": "rose_bonbon"}, 422),
        ({"poids_net_type_kg": "-3"}, 422),
        ({"fournisseur_id": str(uuid.uuid4())}, 400),
        ({"champ_inconnu": 1}, 422),
    ):
        reponse = client.post("/api/catalogue-fournisseur", headers=entetes, json=_entree_catalogue(base) | extra)
        assert reponse.status_code == attendu, (extra, reponse.status_code, reponse.text)


def test_le_compte_applicatif_ne_peut_pas_supprimer_une_entree_du_catalogue(db, base, entreprise):
    entree = achats.creer_catalogue(db, type("A", (), {"entreprise_id": entreprise.id, "id": None})(),
                                    {k: uuid.UUID(v) if k.endswith("_id") else v
                                     for k, v in _entree_catalogue(base).items()})
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM catalogue_fournisseur WHERE id = :i"), {"i": entree["id"]})
    db.rollback()


def _produit_catalogue(client, entetes, base, code, reference, **extra) -> dict:
    corps = _entree_catalogue(base, code, reference_couleur_fournisseur=reference, **extra)
    reponse = client.post("/api/catalogue-fournisseur", headers=entetes, json=corps)
    assert reponse.status_code == 201, reponse.text
    return reponse.json()


def test_commande_preparee_depuis_le_catalogue(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    g1 = _produit_catalogue(client, entetes, base, "OR-G01", "Golden01")
    g3 = _produit_catalogue(client, entetes, base, "OR-G03", "Golden03")
    # Deux references fournisseur de meme finition dans une meme commande : permis grace au catalogue.
    lignes = [{"article_id": str(base["jumbo"].id), "quantite_commandee": 40, "prix_unitaire": 1450,
               "catalogue_id": g1["id"]},
              {"article_id": str(base["jumbo"].id), "quantite_commandee": 20, "catalogue_id": g3["id"]}]
    reponse = client.post("/api/commandes-achat", headers=entetes, json=_commande(base, lignes))
    assert reponse.status_code == 201, reponse.text
    commande = client.get(f"/api/commandes-achat/{reponse.json()['id']}", headers=entetes).json()
    vues = {ligne["reference_couleur_fournisseur"]: ligne for ligne in commande["lignes"]}
    assert set(vues) == {"Golden01", "Golden03"}
    # La finition est reprise du catalogue (non fournie dans la ligne) ; les caracteristiques types suivent.
    assert vues["Golden01"]["couleur_finition"] == "or_transparent"
    assert vues["Golden01"]["poids_net_type_kg"] == 251.67 and vues["Golden01"]["metrage_type_m"] == 4006.75
    assert vues["Golden03"]["catalogue_libelle"].endswith("Golden01")  # libelle du fixture, commun aux deux
    # Sans catalogue, la meme finition en double reste refusee.
    sans = [{"article_id": str(base["jumbo"].id), "quantite_commandee": 1, "couleur_finition": "or_transparent"}] * 2
    assert client.post("/api/commandes-achat", headers=entetes, json=_commande(base, sans)).status_code == 400
    # Le meme produit du catalogue deux fois : refuse aussi.
    double = [{"article_id": str(base["jumbo"].id), "quantite_commandee": 1, "catalogue_id": g1["id"]}] * 2
    assert client.post("/api/commandes-achat", headers=entetes, json=_commande(base, double)).status_code == 400


def test_ligne_de_catalogue_incoherente_refusee(client, en_tant_que, base):
    entetes = en_tant_que("responsable_stock")
    g1 = _produit_catalogue(client, entetes, base, "OR-G01", "Golden01")
    ligne = {"article_id": str(base["jumbo"].id), "quantite_commandee": 5, "catalogue_id": g1["id"]}
    cas = {
        "finition contredite": ({**ligne, "couleur_finition": "kaki_simple"}, {}),
        "autre article": ({**ligne, "article_id": str(base["tube"].id)}, {}),
        "autre fournisseur": (ligne, {"fournisseur_id": str(base["autre"].id)}),
        "catalogue inconnu": ({**ligne, "catalogue_id": str(uuid.uuid4())}, {}),
    }
    for nom, (cas_ligne, extra) in cas.items():
        reponse = client.post("/api/commandes-achat", headers=entetes, json=_commande(base, [cas_ligne], **extra))
        assert reponse.status_code == 400, (nom, reponse.status_code, reponse.text)
    # Une entree desactivee ne se commande plus.
    client.patch(f"/api/catalogue-fournisseur/{g1['id']}", headers=entetes, json={"actif": False})
    assert client.post("/api/commandes-achat", headers=entetes, json=_commande(base, [ligne])).status_code == 400
