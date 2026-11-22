"""Production (M06) : cycle de vie de l'ordre de fabrication, de la creation a la cloture."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.audit import JournalAudit
from app.modules.identite.models import Entreprise
from app.modules.identite.permissions import ROLES, a_la_permission
from app.modules.production.models import OrdreFabrication, TransitionOF
from app.modules.referentiel import service as referentiel
from app.modules.referentiel.models import Article, Fournisseur, Moule
from app.modules.stock import service as stock
from app.modules.stock.models import Bobine, MouvementStock, Reservation

ANNEE = date.today().year
RESULTAT_COHERENT = {"tours_totaux": 160, "tours_defectueux": 2, "pieces_defectueuses_supplementaires": 10,
                     "quantite_doctor_rewinder": 50, "pertes_definitives": 16}


@pytest.fixture
def usine(db, entreprise, creer_compte):
    """Un modele BSG 30 complet, trois bobines (dont une sans metrage) et 5 000 tubes en stock."""
    db.info.update(acteur_id=None, entreprise_id=entreprise.id)
    chef = creer_compte("chef_production", "chef.setup")
    magasinier = creer_compte("responsable_stock", "stock.setup")
    jumbo = Article(entreprise_id=entreprise.id, code="JUMBO", nom="Jumbo BOPP", niveau_stock="semi_fini",
                    unite_gestion="rouleau")
    produit = Article(entreprise_id=entreprise.id, code="BSG30", nom="BSG 30", niveau_stock="produit_fini",
                      unite_gestion="carton")
    tube = Article(entreprise_id=entreprise.id, code="TUBE-45", nom="Tube papier 45", niveau_stock="semi_fini",
                   unite_gestion="piece")
    fournisseur = Fournisseur(entreprise_id=entreprise.id, code="CHINE", nom="Fournisseur jumbo")
    moule = Moule(entreprise_id=entreprise.id, code="M45", nom="Moule 45 mm")
    db.add_all([jumbo, produit, tube, fournisseur, moule])
    db.commit()
    referentiel.charger_references_connues(db, entreprise.id)
    modele = referentiel.creer_modele(db, chef, {
        "code": "BSG-30", "nom": "BSG 30", "famille": "bopp", "largeur_mm": Decimal(45),
        "longueur_rouleau_m": Decimal(25)})
    incomplet = referentiel.creer_modele(db, chef, {
        "code": "BSG-INCOMPLET", "nom": "Sans nomenclature", "famille": "bopp", "largeur_mm": Decimal(45),
        "longueur_rouleau_m": Decimal(25)})
    referentiel.nouvelle_version(db, chef, modele.id, {
        "motif": "Nomenclature complete", "moule_id": moule.id, "article_produit_fini_id": produit.id,
        "article_tube_id": tube.id})
    stock.creer_reception(db, magasinier, {
        "conteneur_reference": "CONT-PROD", "date_reception": date.today(), "fournisseur_id": fournisseur.id,
        "article_id": jumbo.id, "bobines": [
            {"numero_fournisseur": "1", "poids_kg": Decimal(251), "metrage_propre": Decimal(4000),
             "couleur_finition": "or_transparent"},
            {"numero_fournisseur": "2", "poids_kg": Decimal(251), "metrage_propre": Decimal(4000),
             "couleur_finition": "or_transparent"},
            {"numero_fournisseur": "3", "poids_kg": Decimal(251), "couleur_finition": "or_transparent"}]})
    stock.enregistrer_mouvement(db, magasinier, tube, "entree", Decimal(5000), "Stock initial de tubes")
    db.commit()
    bobines = {b.numero_fournisseur: b for b in db.scalars(select(Bobine))}
    return {"chef": chef, "magasinier": magasinier, "jumbo": jumbo, "produit": produit, "tube": tube,
            "modele": modele, "incomplet": incomplet, "moule": moule, "bobines": bobines, "db": db}


def _ordre(usine, numero_bobine="1", metrage=4000, **extra) -> dict:
    return {"modele_id": str(usine["modele"].id), "bobine_id": str(usine["bobines"][numero_bobine].id),
            "metrage_engage": metrage, **extra}


def _solde(client, article) -> dict:
    return client.get("/api/stock/soldes", params={"article_id": str(article.id)}).json()[0]


class Atelier:
    """Les acteurs de la chaine de fabrication, chacun avec sa session."""

    def __init__(self, client, en_tant_que, usine):
        self.client, self.en_tant_que, self.usine = client, en_tant_que, usine

    def _appeler(self, profil, methode, chemin, **corps):
        entetes = self.en_tant_que(profil)
        return self.client.request(methode, chemin, headers=entetes, **corps)

    def creer(self, **extra):
        reponse = self._appeler("chef_production", "POST", "/api/ordres-fabrication",
                                json=_ordre(self.usine, **extra))
        assert reponse.status_code == 201, reponse.text
        return reponse.json()

    def faire(self, profil, ordre, action, attendu=200, **corps):
        reponse = self._appeler(profil, "POST", f"/api/ordres-fabrication/{ordre['id']}/{action}",
                                json=corps or None)
        assert reponse.status_code == attendu, (action, reponse.status_code, reponse.text)
        return reponse.json()

    def resultat(self, ordre, attendu=200, **surcharge):
        corps = {**RESULTAT_COHERENT, "bobine_epuisee": False, **surcharge}
        reponse = self._appeler("chef_production", "PUT", f"/api/ordres-fabrication/{ordre['id']}/resultat",
                                json=corps)
        assert reponse.status_code == attendu, reponse.text
        return reponse.json()

    def jusqu_a_en_cours(self, **extra):
        ordre = self.creer(**extra)
        self.faire("chef_production", ordre, "soumettre")
        self.faire("responsable_stock", ordre, "valider-matieres")
        return self.faire("chef_production", ordre, "demarrer")


@pytest.fixture
def atelier(client, en_tant_que, usine):
    return Atelier(client, en_tant_que, usine)


# --- Droits : chaque route, chaque profil -------------------------------------------------------


ROUTES = [
    ("POST", "/api/ordres-fabrication/{id}/soumettre", "production.saisir", None),
    ("POST", "/api/ordres-fabrication/{id}/valider-matieres", "stock.executer_sortie", None),
    ("POST", "/api/ordres-fabrication/{id}/demarrer", "production.saisir", None),
    ("PUT", "/api/ordres-fabrication/{id}/resultat", "production.saisir",
     {**RESULTAT_COHERENT, "bobine_epuisee": False}),
    ("POST", "/api/ordres-fabrication/{id}/valider-resultat", "production.valider", None),
    ("POST", "/api/ordres-fabrication/{id}/cloturer", "production.cloturer", None),
    ("POST", "/api/ordres-fabrication/{id}/annuler", "production.annuler", {"motif": "Essai de droits"}),
    ("PATCH", "/api/ordres-fabrication/{id}", "production.saisir", {"commentaire": "x"}),
    ("GET", "/api/ordres-fabrication/{id}", "production.consulter", None),
    ("GET", "/api/ordres-fabrication", "production.consulter", None),
]


@pytest.mark.parametrize("role", ROLES)
def test_chaque_transition_exige_son_propre_droit(client, en_tant_que, usine, role):
    entetes = en_tant_que(role)
    inconnu = uuid.uuid4()
    for methode, chemin, permission, corps in ROUTES:
        reponse = client.request(methode, chemin.format(id=inconnu), headers=entetes, json=corps)
        if a_la_permission(role, permission):
            # Autorise : l'ordre n'existe pas, donc 404 (jamais 403).
            assert reponse.status_code in (200, 404), (role, methode, chemin, reponse.status_code)
        else:
            assert reponse.status_code == 403, (role, methode, chemin, reponse.status_code)
    creation = client.post("/api/ordres-fabrication", headers=entetes, json=_ordre(usine))
    assert (creation.status_code == 201) == a_la_permission(role, "production.saisir"), role


def test_qui_fait_quoi_dans_la_chaine_de_fabrication():
    assert a_la_permission("chef_production", "production.saisir")
    assert not a_la_permission("chef_production", "production.valider")
    assert a_la_permission("dg", "production.valider")
    assert not a_la_permission("chef_production", "production.cloturer")
    assert not a_la_permission("chef_production", "stock.executer_sortie")
    assert a_la_permission("responsable_stock", "stock.executer_sortie")
    assert a_la_permission("responsable_stock", "production.cloturer")
    assert not a_la_permission("responsable_stock", "production.valider")
    assert a_la_permission("dg", "production.annuler")
    assert not a_la_permission("dg", "production.saisir")
    assert not a_la_permission("chef_production", "production.annuler")


def test_sans_session_tout_est_refuse(client):
    assert client.get("/api/ordres-fabrication").status_code == 401
    assert client.post("/api/production/previsions", json={}).status_code in (401, 403)


# --- Cycle de vie complet ------------------------------------------------------------------------------


def test_cycle_de_vie_complet_de_la_creation_a_la_cloture(client, atelier, usine, db):
    ordre = atelier.creer()
    assert ordre["numero"] == f"OF-{ANNEE}-00001" and ordre["statut"] == "brouillon"
    assert ordre["pieces_theoriques"] is None  # la prevision est figee a la soumission

    ordre = atelier.faire("chef_production", ordre, "soumettre")
    assert (ordre["statut"], ordre["tours_prevus"], ordre["pieces_theoriques"], ordre["cartons_prevus"],
            ordre["pieces_restantes_prevues"]) == ("soumis", 160, 4480, 49, 70)
    assert ordre["alertes"] == []
    tubes = _solde(client, usine["tube"])
    assert (tubes["physique"], tubes["reserve"], tubes["disponible"]) == (5000.0, 4480.0, 520.0)

    ordre = atelier.faire("responsable_stock", ordre, "valider-matieres")
    assert ordre["statut"] == "matieres_validees"
    tubes = _solde(client, usine["tube"])
    assert (tubes["physique"], tubes["reserve"]) == (520.0, 0.0)  # sortis du stock, reservation levee

    assert atelier.faire("chef_production", ordre, "demarrer")["statut"] == "en_cours"

    saisi = atelier.resultat(ordre)
    assert saisi["statut"] == "resultat_saisi"
    calcule = saisi["resultat"]
    assert (calcule["pieces_conformes"], calcule["cartons_complets"], calcule["pieces_restantes"]) == (4414, 49, 4)
    assert calcule["coherent"] is True and calcule["ecart_pieces"] == -66

    valide = atelier.faire("dg", ordre, "valider-resultat")
    assert valide["statut"] == "resultat_valide" and valide["version_formule"]

    cloture = atelier.faire("responsable_stock", ordre, "cloturer")
    assert cloture["statut"] == "cloture"
    produit = _solde(client, usine["produit"])
    assert produit["physique"] == 49.0  # cartons complets ; les 4 pieces restantes restent un reliquat
    mouvement = db.scalar(select(MouvementStock).where(MouvementStock.article_id == usine["produit"].id))
    assert mouvement.type == "entree" and str(mouvement.ordre_fabrication_id) == ordre["id"]
    assert _solde(client, usine["tube"])["physique"] == 520.0  # 4 480 pieces produites = 4 480 tubes sortis
    assert usine["bobines"]["1"].statut == "entamee_presente"
    assert _solde(client, usine["jumbo"])["physique"] == 3.0  # entamee mais toujours presente

    historique = [(t["de_statut"], t["vers_statut"]) for t in cloture["transitions"]]
    assert historique == [(None, "brouillon"), ("brouillon", "soumis"), ("soumis", "matieres_validees"),
                          ("matieres_validees", "en_cours"), ("en_cours", "resultat_saisi"),
                          ("resultat_saisi", "resultat_valide"), ("resultat_valide", "cloture")]
    actions = set(db.scalars(select(JournalAudit.action)))
    assert {"ordres_fabrication.creation", "ordres_fabrication.modification", "mouvements_stock.creation"} <= actions


def test_numerotation_sequentielle(atelier, usine):
    premier = atelier.creer()
    second = atelier.creer(numero_bobine="2")
    assert (premier["numero"], second["numero"]) == (f"OF-{ANNEE}-00001", f"OF-{ANNEE}-00002")


def test_previsualisation_sans_rien_creer(client, en_tant_que, usine):
    entetes = en_tant_que("chef_production")
    corps = {"modele_id": str(usine["modele"].id), "bobine_id": str(usine["bobines"]["1"].id),
             "metrage_engage": 3900}
    prevision = client.post("/api/production/previsions", headers=entetes, json=corps)
    assert prevision.status_code == 200
    assert (prevision.json()["tours_complets"], prevision.json()["pieces_theoriques"],
            prevision.json()["cartons_complets"], prevision.json()["pieces_restantes"]) == (156, 4368, 48, 48)
    assert client.get("/api/ordres-fabrication").json() == []


# --- Refus a la creation ---------------------------------------------------------------------------------


def test_creation_refusee_selon_les_regles(client, en_tant_que, usine):
    entetes = en_tant_que("chef_production")

    def tenter(**surcharge):
        return client.post("/api/ordres-fabrication", headers=entetes, json=_ordre(usine) | surcharge)

    incomplet = tenter(modele_id=str(usine["incomplet"].id))
    assert incomplet.status_code == 400 and "moule" in incomplet.json()["detail"]
    sans_metrage = tenter(bobine_id=str(usine["bobines"]["3"].id))
    assert sans_metrage.status_code == 400 and "métrage propre" in sans_metrage.json()["detail"]
    trop = tenter(metrage_engage=4001)
    assert trop.status_code == 400 and "dépasse" in trop.json()["detail"]
    court = tenter(metrage_engage=24)
    assert court.status_code == 400 and "un seul tour" in court.json()["detail"]
    assert tenter(metrage_engage=0).status_code == 422
    assert tenter(bobine_id=str(uuid.uuid4())).status_code == 400
    assert tenter(modele_id=str(uuid.uuid4())).status_code == 400
    assert tenter(statut="soumis").status_code == 422  # le statut ne se choisit pas


def test_bobine_epuisee_ou_modele_desactive_refuses(client, en_tant_que, usine, db):
    entetes = en_tant_que("chef_production")
    usine["bobines"]["2"].statut = "epuisee"
    db.commit()
    assert client.post("/api/ordres-fabrication", headers=entetes,
                       json=_ordre(usine, "2")).status_code == 400
    usine["modele"].actif = False
    db.commit()
    assert client.post("/api/ordres-fabrication", headers=entetes, json=_ordre(usine)).status_code == 400


def test_une_bobine_ne_sert_qu_a_un_ordre_a_la_fois(atelier, client, en_tant_que, usine, db):
    premier = atelier.creer()
    entetes = en_tant_que("chef_production")
    refus = client.post("/api/ordres-fabrication", headers=entetes, json=_ordre(usine))
    assert refus.status_code == 409 and premier["numero"] in refus.json()["detail"]
    # Liberee par l'annulation : un nouvel ordre est possible.
    atelier.faire("dg", premier, "annuler", motif="Mauvaise bobine choisie")
    assert client.post("/api/ordres-fabrication", headers=en_tant_que("chef_production"),
                       json=_ordre(usine)).status_code == 201


def test_la_base_garantit_aussi_l_unicite_de_la_bobine_active(usine, db):
    """Meme sans passer par l'API : l'index partiel refuse un second ordre actif sur la bobine."""
    version = referentiel.version_courante(db, usine["modele"].id)
    valeurs = {"e": usine["chef"].entreprise_id, "m": usine["modele"].id, "v": version.id,
               "b": usine["bobines"]["1"].id}
    requete = text("INSERT INTO ordres_fabrication (id, entreprise_id, numero, modele_id, version_id, bobine_id, "
                   "metrage_engage, statut) VALUES (gen_random_uuid(), :e, :n, :m, :v, :b, 1000, :s)")
    db.execute(requete, valeurs | {"n": "OF-X-1", "s": "brouillon"})
    with pytest.raises(DBAPIError, match="uq_ordres_fabrication_bobine_active"), db.begin_nested():
        db.execute(requete, valeurs | {"n": "OF-X-2", "s": "soumis"})


def test_deux_creations_simultanees_sur_une_bobine_donnent_un_refus_propre(usine, db, monkeypatch):
    """Course : la verification passe pour les deux requetes, seul l'index de la base les departage.
    Le perdant doit recevoir un refus metier (409), pas une erreur de base brute (500)."""
    from app.core.erreurs import Conflit
    from app.modules.production import service as production

    production.creer(db, usine["chef"], {"modele_id": usine["modele"].id, "bobine_id": usine["bobines"]["1"].id,
                                          "metrage_engage": Decimal(4000)})
    monkeypatch.setattr(production, "_ordre_actif_de", lambda *_: None)  # la course : verification aveugle
    with pytest.raises(Conflit, match="vient d'être engagée"):
        production.creer(db, usine["chef"], {"modele_id": usine["modele"].id,
                                             "bobine_id": usine["bobines"]["1"].id,
                                             "metrage_engage": Decimal(4000)})
    assert len(db.scalars(select(OrdreFabrication)).all()) == 1


def test_brouillon_modifiable_puis_fige(atelier, client, en_tant_que, usine):
    ordre = atelier.creer(metrage=3900)
    entetes = en_tant_que("chef_production")
    modif = client.patch(f"/api/ordres-fabrication/{ordre['id']}", headers=entetes,
                         json={"metrage_engage": 4000, "commentaire": "Reprise du métrage mesuré"})
    assert modif.status_code == 200 and modif.json()["metrage_engage"] == 4000.0
    assert client.patch(f"/api/ordres-fabrication/{ordre['id']}", headers=entetes,
                        json={"metrage_engage": 4500}).status_code == 400
    assert client.patch(f"/api/ordres-fabrication/{ordre['id']}", headers=entetes,
                        json={"statut": "cloture"}).status_code == 422
    assert client.patch(f"/api/ordres-fabrication/{ordre['id']}", headers=entetes,
                        json={"bobine_id": str(usine["bobines"]["2"].id)}).status_code == 422
    atelier.faire("chef_production", ordre, "soumettre")
    gele = client.patch(f"/api/ordres-fabrication/{ordre['id']}", headers=en_tant_que("chef_production"),
                        json={"commentaire": "Trop tard"})
    assert gele.status_code == 409


# --- Machine a etats : aucun saut possible -------------------------------------------------------------------


def test_aucun_saut_d_etat(atelier, usine):
    ordre = atelier.creer()
    atelier.faire("chef_production", ordre, "demarrer", attendu=409)
    atelier.faire("responsable_stock", ordre, "valider-matieres", attendu=409)
    atelier.faire("dg", ordre, "valider-resultat", attendu=409)
    atelier.faire("responsable_stock", ordre, "cloturer", attendu=409)
    atelier.resultat(ordre, attendu=409)
    atelier.faire("chef_production", ordre, "soumettre")
    atelier.faire("chef_production", ordre, "soumettre", attendu=409)
    atelier.faire("chef_production", ordre, "demarrer", attendu=409)
    atelier.faire("responsable_stock", ordre, "valider-matieres")
    atelier.faire("responsable_stock", ordre, "valider-matieres", attendu=409)
    atelier.resultat(ordre, attendu=409)  # pas encore demarre
    atelier.faire("chef_production", ordre, "demarrer")
    atelier.faire("dg", ordre, "valider-resultat", attendu=409)  # rien n'est saisi
    atelier.faire("responsable_stock", ordre, "cloturer", attendu=409)
    assert len(usine["db"].scalars(select(TransitionOF).where(TransitionOF.ordre_id == uuid.UUID(ordre["id"]))).all()) == 4


def test_un_echec_ne_laisse_aucune_trace_en_memoire(atelier, usine, db):
    """Une transition refusee n'a rien change : ni statut, ni mouvement, ni reservation."""
    ordre = atelier.creer()
    atelier.faire("responsable_stock", ordre, "valider-matieres", attendu=409)
    db.expire_all()
    en_base = db.get(OrdreFabrication, uuid.UUID(ordre["id"]))
    assert en_base.statut == "brouillon"
    assert db.scalar(select(MouvementStock).where(MouvementStock.ordre_fabrication_id == en_base.id)) is None
    assert db.scalar(select(Reservation).where(Reservation.ordre_fabrication_id == en_base.id)) is None


# --- Resultat et controle de coherence ------------------------------------------------------------------------------


def test_le_controle_de_coherence_bloque_la_validation_pas_la_saisie(atelier, usine):
    ordre = atelier.jusqu_a_en_cours()
    # 66 non conformes mais seulement 60 expliques : une piece oubliee.
    saisi = atelier.resultat(ordre, pertes_definitives=10)
    assert saisi["statut"] == "resultat_saisi"
    assert saisi["resultat"]["coherent"] is False and saisi["resultat"]["ecart_comptage"] == 6
    refus = atelier._appeler("dg", "POST", f"/api/ordres-fabrication/{ordre['id']}/valider-resultat")
    assert refus.status_code == 400
    assert "non traitées" in refus.json()["detail"] and "+6" in refus.json()["detail"]
    # Double comptage dans l'autre sens.
    atelier.resultat(ordre, quantite_doctor_rewinder=60)
    refus = atelier._appeler("dg", "POST", f"/api/ordres-fabrication/{ordre['id']}/valider-resultat")
    assert refus.status_code == 400 and "double comptage" in refus.json()["detail"]
    # Correction : la saisie se refait tant que rien n'est valide.
    atelier.resultat(ordre)
    assert atelier.faire("dg", ordre, "valider-resultat")["statut"] == "resultat_valide"
    atelier.resultat(ordre, attendu=409)  # une fois valide, le resultat est fige


def test_la_correction_de_saisie_est_tracee(atelier, usine, db):
    ordre = atelier.jusqu_a_en_cours()
    atelier.resultat(ordre, pertes_definitives=10)
    atelier.resultat(ordre)
    entrees = db.scalars(select(JournalAudit).where(JournalAudit.cible_id == ordre["id"],
                                                    JournalAudit.action == "ordres_fabrication.modification")).all()
    changes = [e for e in entrees if e.avant and "pertes_definitives" in e.avant]
    assert any(e.avant["pertes_definitives"] == 10 and e.apres["pertes_definitives"] == 16 for e in changes)


def test_saisies_impossibles_refusees(atelier):
    ordre = atelier.jusqu_a_en_cours()
    assert "plus de tours" in atelier.resultat(ordre, attendu=400, tours_defectueux=161)["detail"]
    assert "depassent" in atelier.resultat(ordre, attendu=400, pieces_defectueuses_supplementaires=5000)["detail"]
    atelier.resultat(ordre, attendu=422, tours_totaux=-1)
    atelier.resultat(ordre, attendu=422, pertes_definitives="beaucoup")


def test_plus_de_tours_que_prevu_est_un_avertissement(atelier):
    ordre = atelier.jusqu_a_en_cours()
    saisi = atelier.resultat(ordre, tours_totaux=165, tours_defectueux=0, pieces_defectueuses_supplementaires=0,
                             quantite_doctor_rewinder=0, pertes_definitives=0)
    assert [a["code"] for a in saisi["alertes"]] == ["tours_superieurs_prevision"]
    corrige = atelier.resultat(ordre)
    assert corrige["alertes"] == []


def test_celui_qui_saisit_le_resultat_ne_peut_pas_le_valider(atelier):
    """Separation structurelle : le chef de production saisit, seul le DG (ou son delegataire) valide."""
    ordre = atelier.jusqu_a_en_cours()
    atelier.resultat(ordre)
    refus = atelier._appeler("chef_production", "POST", f"/api/ordres-fabrication/{ordre['id']}/valider-resultat")
    assert refus.status_code == 403
    assert atelier.faire("dg", ordre, "valider-resultat")["statut"] == "resultat_valide"


# --- Cloture : regularisations ----------------------------------------------------------------------------------------


def test_cloture_restitue_les_tubes_non_utilises(client, atelier, usine):
    ordre = atelier.jusqu_a_en_cours()
    # 150 tours au lieu de 160 : 280 tubes sortis en trop.
    atelier.resultat(ordre, tours_totaux=150, tours_defectueux=0, pieces_defectueuses_supplementaires=0,
                     quantite_doctor_rewinder=0, pertes_definitives=0)
    atelier.faire("dg", ordre, "valider-resultat")
    atelier.faire("responsable_stock", ordre, "cloturer")
    assert _solde(client, usine["tube"])["physique"] == 520.0 + 280.0
    assert _solde(client, usine["produit"])["physique"] == 46.0  # 4 200 pieces / 90 = 46 cartons


def test_cloture_ajoute_les_tubes_manquants(client, atelier, usine):
    ordre = atelier.jusqu_a_en_cours()
    atelier.resultat(ordre, tours_totaux=162, tours_defectueux=0, pieces_defectueuses_supplementaires=0,
                     quantite_doctor_rewinder=0, pertes_definitives=0)
    atelier.faire("dg", ordre, "valider-resultat")
    atelier.faire("responsable_stock", ordre, "cloturer")
    assert _solde(client, usine["tube"])["physique"] == 520.0 - 56.0


def test_bobine_epuisee_sort_du_stock(client, atelier, usine):
    ordre = atelier.jusqu_a_en_cours()
    atelier.resultat(ordre, bobine_epuisee=True)
    atelier.faire("dg", ordre, "valider-resultat")
    atelier.faire("responsable_stock", ordre, "cloturer")
    assert usine["bobines"]["1"].statut == "epuisee"
    assert _solde(client, usine["jumbo"])["physique"] == 2.0
    refus = atelier._appeler("chef_production", "POST", "/api/ordres-fabrication",
                             json=_ordre(usine))
    assert refus.status_code == 400  # une bobine epuisee ne se reutilise pas


def test_une_bobine_entamee_sert_a_une_seance_suivante(atelier, usine):
    premier = atelier.jusqu_a_en_cours(metrage=2000)
    atelier.resultat(premier, tours_totaux=80, tours_defectueux=0, pieces_defectueuses_supplementaires=0,
                     quantite_doctor_rewinder=0, pertes_definitives=0)
    atelier.faire("dg", premier, "valider-resultat")
    atelier.faire("responsable_stock", premier, "cloturer")
    second = atelier.creer(metrage=2000)
    assert second["statut"] == "brouillon"
    assert not second["alertes"]
    soumis = atelier.faire("chef_production", second, "soumettre")
    assert soumis["alertes"] == []  # 2 000 + 2 000 = metrage initial exact : aucun depassement


def test_metrage_cumule_superieur_au_metrage_initial_alerte(atelier, usine, db):
    stock.enregistrer_mouvement(db, usine["magasinier"], usine["tube"], "entree", Decimal(5000),
                                "Reapprovisionnement de tubes")
    db.commit()
    premier = atelier.jusqu_a_en_cours(metrage=3000)
    atelier.resultat(premier, tours_totaux=120, tours_defectueux=0, pieces_defectueuses_supplementaires=0,
                     quantite_doctor_rewinder=0, pertes_definitives=0)
    atelier.faire("dg", premier, "valider-resultat")
    atelier.faire("responsable_stock", premier, "cloturer")
    suite = atelier.creer(metrage=2000)
    soumis = atelier.faire("chef_production", suite, "soumettre")
    assert [a["code"] for a in soumis["alertes"]] == ["metrage_cumule"]


def test_stock_de_tubes_insuffisant_bloque_la_sortie(client, atelier, usine, db):
    stock.enregistrer_mouvement(db, usine["magasinier"], usine["tube"], "consommation", Decimal(4000),
                                "Sortie hors fabrication")
    db.commit()
    ordre = atelier.creer()
    soumis = atelier.faire("chef_production", ordre, "soumettre")
    assert [a["code"] for a in soumis["alertes"]] == ["tubes_insuffisants"]
    assert _solde(client, usine["tube"])["reserve"] == 0.0
    # Le magasinier ne peut pas sortir des tubes qui n'existent pas : le stock reste intact.
    refus = atelier._appeler("responsable_stock", "POST", f"/api/ordres-fabrication/{ordre['id']}/valider-matieres")
    assert refus.status_code == 409 and "insuffisant" in refus.json()["detail"]
    assert _solde(client, usine["tube"])["physique"] == 1000.0
    assert atelier._appeler("responsable_stock", "GET", f"/api/ordres-fabrication/{ordre['id']}").json()["statut"] == "soumis"
    # Il ne peut pas non plus s'accorder lui-meme une derogation.
    interdit = atelier._appeler("responsable_stock", "POST", f"/api/ordres-fabrication/{ordre['id']}/valider-matieres",
                                json={"derogation_motif": "On est presses"})
    assert interdit.status_code == 403
    # Le DG peut accorder une derogation motivee : tracee dans l'historique, stock negatif signale.
    accorde = atelier.faire("dg", ordre, "valider-matieres", derogation_motif="Tubes en route, arrivee demain")
    assert accorde["statut"] == "matieres_validees"
    assert any("Tubes en route" in (t["motif"] or "") for t in accorde["transitions"])
    assert _solde(client, usine["tube"])["negatif"] is True


# --- Annulation ----------------------------------------------------------------------------------------------------------------


def test_annulation_exige_motif_et_le_dg(atelier, usine, client):
    ordre = atelier.creer()
    atelier.faire("chef_production", ordre, "annuler", attendu=403, motif="Je ne devrais pas pouvoir")
    atelier.faire("dg", ordre, "annuler", attendu=422)
    atelier.faire("dg", ordre, "annuler", attendu=422, motif="non")
    annule = atelier.faire("dg", ordre, "annuler", motif="Bobine endommagée avant fabrication")
    assert annule["statut"] == "annule" and annule["motif_annulation"].startswith("Bobine")
    assert annule["transitions"][-1]["motif"] == annule["motif_annulation"]
    atelier.faire("dg", ordre, "annuler", attendu=409, motif="Deuxième annulation")
    atelier.faire("chef_production", ordre, "soumettre", attendu=409)


def test_annulation_apres_sortie_des_matieres_remet_les_tubes(client, atelier, usine):
    ordre = atelier.jusqu_a_en_cours()
    assert _solde(client, usine["tube"])["physique"] == 520.0
    atelier.faire("dg", ordre, "annuler", motif="Panne de la rembobineuse")
    assert _solde(client, usine["tube"])["physique"] == 5000.0
    assert _solde(client, usine["jumbo"])["physique"] == 3.0
    assert usine["bobines"]["1"].statut == "disponible"


def test_annulation_apres_soumission_leve_la_reservation(client, atelier, usine):
    ordre = atelier.creer()
    atelier.faire("chef_production", ordre, "soumettre")
    assert _solde(client, usine["tube"])["reserve"] == 4480.0
    atelier.faire("dg", ordre, "annuler", motif="Commande client annulée")
    assert _solde(client, usine["tube"])["reserve"] == 0.0


def test_un_ordre_cloture_ne_s_annule_pas(atelier):
    ordre = atelier.jusqu_a_en_cours()
    atelier.resultat(ordre)
    atelier.faire("dg", ordre, "valider-resultat")
    atelier.faire("responsable_stock", ordre, "cloturer")
    atelier.faire("dg", ordre, "annuler", attendu=409, motif="Trop tard pour annuler")


# --- Lecture, filtres, isolation ----------------------------------------------------------------------------------------------


def test_filtres_de_la_liste(client, atelier, usine, en_tant_que):
    premier = atelier.creer()
    atelier.creer(numero_bobine="2")
    atelier.faire("chef_production", premier, "soumettre")
    entetes = en_tant_que("dg")
    assert len(client.get("/api/ordres-fabrication", headers=entetes).json()) == 2
    soumis = client.get("/api/ordres-fabrication", params={"statut": "soumis"}).json()
    assert [o["numero"] for o in soumis] == [premier["numero"]]
    par_bobine = client.get("/api/ordres-fabrication", params={"bobine_id": str(usine["bobines"]["2"].id)}).json()
    assert len(par_bobine) == 1
    assert client.get("/api/ordres-fabrication", params={"statut": "inconnu"}).status_code == 422


def test_isolation_entre_entreprises(client, atelier, usine, db, en_tant_que):
    ordre = atelier.creer()
    autre = Entreprise(nom="Autre usine production")
    db.add(autre)
    db.commit()
    from app.core.audit import maintenant
    from app.modules.identite.models import Utilisateur
    from tests.conftest import hash_de_test
    db.add(Utilisateur(entreprise_id=autre.id, identifiant="chef.autre", nom="Chef Autre", role="chef_production",
                       mot_de_passe_hash=hash_de_test(), doit_changer_mot_de_passe=False,
                       mot_de_passe_modifie_le=maintenant(), cree_le=maintenant()))
    db.commit()
    client.cookies.clear()
    from tests.conftest import se_connecter
    entetes = {"X-CSRF-Token": se_connecter(client, "chef.autre")}
    assert client.get("/api/ordres-fabrication").json() == []
    assert client.get(f"/api/ordres-fabrication/{ordre['id']}").status_code == 404
    assert client.post(f"/api/ordres-fabrication/{ordre['id']}/soumettre", headers=entetes).status_code == 404
    assert en_tant_que


# --- Protections en base ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("requete", [
    "DELETE FROM ordres_fabrication", "TRUNCATE ordres_fabrication",
    "UPDATE transitions_ordre_fabrication SET vers_statut = 'cloture'",
    "DELETE FROM transitions_ordre_fabrication", "UPDATE bobine_utilisations SET metrage_engage = 1",
    "DELETE FROM bobine_utilisations",
])
def test_le_compte_applicatif_ne_peut_ni_supprimer_ni_reecrire_l_historique(db, requete):
    with pytest.raises(DBAPIError, match="permission denied"), db.begin_nested():
        db.execute(text(requete))


def test_le_proprietaire_ne_reecrit_pas_l_historique_des_transitions(proprietaire, atelier, db):
    ordre = atelier.creer()
    with proprietaire():
        for requete in (f"UPDATE transitions_ordre_fabrication SET vers_statut = 'cloture' "
                        f"WHERE ordre_id = '{ordre['id']}'",
                        f"DELETE FROM transitions_ordre_fabrication WHERE ordre_id = '{ordre['id']}'"):
            with pytest.raises(DBAPIError, match="ajout seul"), db.begin_nested():
                db.execute(text(requete))


def test_une_annulation_exige_un_motif_en_base(atelier, db):
    ordre = atelier.creer()
    with pytest.raises(DBAPIError, match="annulation_motivee"), db.begin_nested():
        db.execute(text(f"UPDATE ordres_fabrication SET statut = 'annule' WHERE id = '{ordre['id']}'"))
