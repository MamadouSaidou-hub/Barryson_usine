"""Delegation des validations du DG, et taux de change des commandes d'achat."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from functools import cached_property

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.audit import JournalAudit, maintenant
from app.core.config import get_settings
from app.modules.identite.delegations import DELEGABLES, delegations_actives
from app.modules.identite.models import Delegation, Utilisateur
from app.modules.identite.permissions import ROLES
from app.modules.referentiel.models import Article, Fournisseur
from tests.conftest import se_connecter


@pytest.fixture
def base(db, entreprise):
    db.info.update(acteur_id=None, entreprise_id=entreprise.id)
    tube = Article(entreprise_id=entreprise.id, code="TUBE-45", nom="Tube", niveau_stock="semi_fini",
                   unite_gestion="piece")
    fini = Article(entreprise_id=entreprise.id, code="BSG30", nom="BSG 30", niveau_stock="produit_fini",
                   unite_gestion="carton")
    chine = Fournisseur(entreprise_id=entreprise.id, code="CHINE", nom="Fournisseur Chine")
    db.add_all([tube, fini, chine])
    db.commit()
    return {"tube": tube, "fini": fini, "chine": chine}


def _commande(base, **extra) -> dict:
    return {"fournisseur_id": str(base["chine"].id), "devise": "USD", "taux_change_gnf": "8650",
            "lignes": [{"article_id": str(base["tube"].id), "quantite_commandee": 1000, "prix_unitaire": "0.12"}],
            **extra}


def _delegation(delegataire, **extra) -> dict:
    return {"delegataire_id": str(delegataire.id), "permissions": ["achats.valider"],
            "jusqu_au": str(date.today() + timedelta(days=14)), "motif": "Absence du DG en mission", **extra}


class Scene:
    def __init__(self, client, en_tant_que, creer_compte, base, db):
        self.client, self.en_tant_que, self.base, self.db = client, en_tant_que, base, db

    def _compte(self, role: str) -> Utilisateur:
        self.en_tant_que(role)  # cree le compte au besoin
        return self.db.scalar(select(Utilisateur).where(Utilisateur.role == role))

    @cached_property
    def commercial(self) -> Utilisateur:
        return self._compte("directeur_commercial")

    @cached_property
    def comptable(self) -> Utilisateur:
        return self._compte("comptable")

    def appeler(self, profil, methode, chemin, **corps):
        return self.client.request(methode, chemin, headers=self.en_tant_que(profil), **corps)

    def deleguer(self, delegataire, profil="dg", **extra):
        return self.appeler(profil, "POST", "/api/delegations", json=_delegation(delegataire, **extra))

    def commande_soumise(self) -> dict:
        reponse = self.appeler("responsable_stock", "POST", "/api/commandes-achat", json=_commande(self.base))
        assert reponse.status_code == 201, reponse.text
        commande = reponse.json()
        assert self.appeler("responsable_stock", "POST", f"/api/commandes-achat/{commande['id']}/soumettre"
                            ).status_code == 200
        return commande


@pytest.fixture
def scene(client, en_tant_que, creer_compte, base, db):
    return Scene(client, en_tant_que, creer_compte, base, db)


# --- Qui peut deleguer ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", [r for r in ROLES if r != "dg"])
def test_seul_le_dg_designe_ou_revoque_un_delegataire(scene, role):
    assert scene.deleguer(scene.commercial, profil=role).status_code == 403
    assert scene.appeler(role, "GET", "/api/delegations").status_code == 403
    assert scene.appeler(role, "POST", f"/api/delegations/{uuid.uuid4()}/revoquer").status_code == 403


def test_un_delegataire_ne_peut_pas_deleguer_a_son_tour(scene):
    assert scene.deleguer(scene.commercial).status_code == 201
    assert scene.deleguer(scene.comptable, profil="directeur_commercial").status_code == 403


def test_sans_session_tout_est_refuse(client):
    assert client.get("/api/delegations").status_code == 401
    assert client.get("/api/delegations/recues").status_code == 401


# --- Regles de creation -----------------------------------------------------------------------------------------------


def test_creation_et_regles_de_validite(scene, creer_compte):
    ok = scene.deleguer(scene.commercial)
    assert ok.status_code == 201 and ok.json()["permissions"] == ["achats.valider"]
    assert ok.json()["revoquee_le"] is None

    def refus(attendu, **extra):
        reponse = scene.deleguer(scene.commercial, **extra)
        assert reponse.status_code == attendu, (extra, reponse.text)
        return reponse

    refus(422, permissions=[])
    refus(422, motif="non")
    refus(422, delegataire_id="pas-un-uuid")
    refus(422, jusqu_au="demain")
    assert "non délégable" in refus(400, permissions=["utilisateurs.gerer"]).json()["detail"]
    assert "non délégable" in refus(400, permissions=["achats.valider", "delegations.gerer"]).json()["detail"]
    assert "non délégable" in refus(400, permissions=["audit.verifier"]).json()["detail"]
    assert "futur" in refus(400, jusqu_au=str(date.today() - timedelta(days=1))).json()["detail"]
    maximum = get_settings().delegation_duree_max_jours
    assert "jours au plus" in refus(400, jusqu_au=str(date.today() + timedelta(days=maximum + 5))).json()["detail"]
    refus(201, jusqu_au=str(date.today() + timedelta(days=maximum - 1)))
    assert "introuvable" in refus(400, delegataire_id=str(uuid.uuid4())).json()["detail"]
    refus(422, role="dg")  # champ inattendu


def test_choix_du_delegataire(scene, creer_compte, db):
    dg = scene.appeler("dg", "GET", "/api/auth/moi").json()["utilisateur"]
    assert "lui-même" in scene.appeler("dg", "POST", "/api/delegations", json={
        **_delegation(scene.commercial), "delegataire_id": dg["id"]}).json()["detail"]
    admin = creer_compte("administrateur")
    assert "administrateur" in scene.deleguer(admin).json()["detail"]
    inactif = creer_compte("responsable_rh")
    inactif.actif = False
    db.commit()
    assert "désactivé" in scene.deleguer(inactif).json()["detail"]


# --- Le delegataire valide ------------------------------------------------------------------------------------------------


def test_le_delegataire_valide_une_commande_au_nom_du_dg(scene, db):
    commande = scene.commande_soumise()
    # Sans delegation, le directeur commercial n'a aucun droit sur la validation des achats.
    assert scene.appeler("directeur_commercial", "POST", f"/api/commandes-achat/{commande['id']}/valider"
                         ).status_code == 403
    delegation = scene.deleguer(scene.commercial).json()

    validee = scene.appeler("directeur_commercial", "POST", f"/api/commandes-achat/{commande['id']}/valider")
    assert validee.status_code == 200
    assert validee.json()["statut"] == "validee"
    assert validee.json()["valide_par"] == str(scene.commercial.id)
    assert validee.json()["valide_via_delegation_id"] == delegation["id"]  # decision imputable a la delegation
    entree = db.scalar(select(JournalAudit).where(JournalAudit.cible_id == commande["id"],
                                                  JournalAudit.action == "commandes_achat.modification",
                                                  JournalAudit.apres["statut"].astext == "validee"))
    assert entree.acteur_id == scene.commercial.id


def test_la_delegation_n_ouvre_que_les_droits_accordes(scene):
    commande = scene.commande_soumise()
    scene.deleguer(scene.commercial)
    moi = scene.appeler("directeur_commercial", "GET", "/api/auth/moi").json()
    assert "achats.valider" in moi["permissions"] and moi["permissions_deleguees"] == ["achats.valider"]
    assert "stock.valider_ajustement" not in moi["permissions"]
    assert "utilisateurs.gerer" not in moi["permissions"]
    # Le delegue valide les achats mais n'a pas acquis les droits de saisie du responsable stock.
    assert scene.appeler("directeur_commercial", "POST", f"/api/commandes-achat/{commande['id']}/soumettre"
                         ).status_code == 403
    assert scene.appeler("directeur_commercial", "GET", "/api/audit").status_code == 403
    assert scene.appeler("directeur_commercial", "POST", "/api/delegations", json=_delegation(scene.comptable)
                         ).status_code == 403


def test_un_delegataire_ne_valide_pas_sa_propre_commande(scene, creer_compte, base):
    """La separation vaut aussi pour lui : s'il a saisi la commande, un autre doit la valider."""
    stock = creer_compte("responsable_stock", "stock.delegue")
    scene.deleguer(stock)
    commande = scene.commande_soumise()  # saisie par un autre responsable stock
    # stock.delegue (delegataire) valide la commande d'un tiers : autorise.
    assert scene.appeler("responsable_stock", "GET", "/api/auth/moi").json()["utilisateur"]["identifiant"] != ""
    autre = scene.client.post(f"/api/commandes-achat/{commande['id']}/valider",
                              headers={"X-CSRF-Token": se_connecter(scene.client, "stock.delegue")})
    assert autre.status_code == 200 and autre.json()["valide_par"] == str(stock.id)

    # Sa propre commande : refusee, delegation ou non.
    propre = scene.client.post("/api/commandes-achat", json=_commande(base),
                               headers={"X-CSRF-Token": se_connecter(scene.client, "stock.delegue")}).json()
    entetes = {"X-CSRF-Token": se_connecter(scene.client, "stock.delegue")}
    scene.client.post(f"/api/commandes-achat/{propre['id']}/soumettre", headers=entetes)
    refus = scene.client.post(f"/api/commandes-achat/{propre['id']}/valider", headers=entetes)
    assert refus.status_code == 403 and "autre personne" in refus.json()["detail"]


def test_le_delegataire_valide_aussi_un_mouvement_de_stock(scene, base, db):
    scene.deleguer(scene.commercial, permissions=["stock.valider_ajustement"])
    mouvement = scene.appeler("responsable_stock", "POST", "/api/stock/mouvements", json={
        "type": "ajustement", "sens": "plus", "article_id": str(base["tube"].id), "quantite": 40,
        "motif": "Ecart constate au comptage"}).json()
    validation = scene.appeler("directeur_commercial", "POST",
                               f"/api/stock/mouvements/{mouvement['id']}/validation", json={"decision": "valide"})
    assert validation.status_code == 200 and validation.json()["statut"] == "valide"
    ligne = db.scalar(text("SELECT delegation_id FROM validations_mouvements WHERE mouvement_id = :m"),
                      {"m": mouvement["id"]})
    assert ligne is not None
    # La delegation couvre l'ajustement, pas la sortie exceptionnelle.
    sortie = scene.appeler("responsable_stock", "POST", "/api/stock/mouvements", json={
        "type": "sortie_exceptionnelle", "article_id": str(base["tube"].id), "quantite": 2,
        "motif": "Echantillons offerts"}).json()
    assert scene.appeler("directeur_commercial", "POST", f"/api/stock/mouvements/{sortie['id']}/validation",
                         json={"decision": "valide"}).status_code == 403


# --- Fin de la delegation ------------------------------------------------------------------------------------------------------


def test_revocation_immediate_et_definitive(scene):
    commande = scene.commande_soumise()
    delegation = scene.deleguer(scene.commercial).json()
    assert len(scene.appeler("directeur_commercial", "GET", "/api/delegations/recues").json()) == 1

    revoquee = scene.appeler("dg", "POST", f"/api/delegations/{delegation['id']}/revoquer")
    assert revoquee.status_code == 200 and revoquee.json()["revoquee_le"] is not None
    assert scene.appeler("directeur_commercial", "POST", f"/api/commandes-achat/{commande['id']}/valider"
                         ).status_code == 403
    assert scene.appeler("directeur_commercial", "GET", "/api/delegations/recues").json() == []
    assert scene.appeler("directeur_commercial", "GET", "/api/auth/moi").json()["permissions_deleguees"] == []
    assert scene.appeler("dg", "POST", f"/api/delegations/{delegation['id']}/revoquer").status_code == 403
    assert scene.appeler("dg", "POST", f"/api/delegations/{uuid.uuid4()}/revoquer").status_code == 404


def test_une_delegation_expiree_ne_donne_plus_rien(scene, db, proprietaire):
    commande = scene.commande_soumise()
    scene.deleguer(scene.commercial)
    delegation = db.scalar(select(Delegation))
    hier = maintenant() - timedelta(days=1)
    # Simule l'ecoulement du temps : la base interdit de modifier une delegation, il faut donc
    # contourner volontairement sa protection (acces proprietaire, declencheurs inhibes).
    with proprietaire():
        db.execute(text("SET LOCAL session_replication_role = replica"))
        db.execute(text("UPDATE delegations SET date_debut = :d, date_fin = :f WHERE id = :i"),
                   {"d": hier - timedelta(days=5), "f": hier, "i": delegation.id})
        db.execute(text("SET LOCAL session_replication_role = origin"))
    db.expire_all()
    assert scene.appeler("directeur_commercial", "POST", f"/api/commandes-achat/{commande['id']}/valider"
                         ).status_code == 403
    assert delegations_actives(db, scene.commercial) == []


def test_le_pouvoir_delegue_disparait_avec_le_dg_qui_l_a_accorde(scene, db):
    commande = scene.commande_soumise()
    scene.deleguer(scene.commercial)
    db.execute(text("UPDATE utilisateurs SET actif = false WHERE role = 'dg'"))
    db.expire_all()
    assert delegations_actives(db, scene.commercial) == []
    assert scene.appeler("directeur_commercial", "POST", f"/api/commandes-achat/{commande['id']}/valider"
                         ).status_code == 403


def test_le_delegataire_desactive_perd_tout(scene, db):
    scene.deleguer(scene.commercial)
    scene.commercial.actif = False
    db.commit()
    assert scene.appeler("dg", "GET", "/api/delegations", params={"actives": "true"}).status_code == 200
    reponse = scene.client.post("/api/auth/connexion", json={"identifiant": scene.commercial.identifiant,
                                                            "mot_de_passe": "Cheval-Correct-Agrafe-91"})
    assert reponse.status_code == 401


# --- Tracabilite et protections en base ------------------------------------------------------------------------------------------


def test_liste_et_audit_des_delegations(scene, db):
    delegation = scene.deleguer(scene.commercial).json()
    scene.appeler("dg", "POST", f"/api/delegations/{delegation['id']}/revoquer")
    scene.deleguer(scene.comptable, permissions=["achats.valider", "finances.valider"])
    toutes = scene.appeler("dg", "GET", "/api/delegations").json()
    assert len(toutes) == 2
    assert [d["id"] for d in scene.appeler("dg", "GET", "/api/delegations", params={"actives": "true"}).json()] == [
        toutes[0]["id"]]
    actions = set(db.scalars(select(JournalAudit.action)))
    assert {"delegations.creation", "delegation.revoquee"} <= actions


def test_delegables_limitees_aux_validations_du_dg():
    assert DELEGABLES == {"achats.valider", "stock.valider_ajustement", "stock.valider_sortie_exceptionnelle",
                          "stock.valider_entree_directe", "finances.valider", "ventes.valider_engagement"}
    assert all(p.split(".")[1].startswith("valider") for p in DELEGABLES)


@pytest.mark.parametrize("requete", [
    "DELETE FROM delegations", "TRUNCATE delegations",
])
def test_le_compte_applicatif_ne_supprime_pas_une_delegation(db, requete):
    with pytest.raises(DBAPIError, match="permission denied"), db.begin_nested():
        db.execute(text(requete))


def test_une_delegation_ne_s_allonge_pas_meme_pour_le_proprietaire(scene, db, proprietaire):
    delegation = scene.deleguer(scene.commercial).json()
    modifications = [
        f"UPDATE delegations SET date_fin = date_fin + interval '1 year' WHERE id = '{delegation['id']}'",
        f"UPDATE delegations SET permissions = '[\"achats.valider\", \"finances.valider\"]' "
        f"WHERE id = '{delegation['id']}'",
        f"UPDATE delegations SET delegataire_id = delegant_id WHERE id = '{delegation['id']}'",
    ]
    for requete in modifications:
        with pytest.raises(DBAPIError, match="figee|delegant_distinct"), db.begin_nested():
            db.execute(text(requete))
        with proprietaire(), pytest.raises(DBAPIError, match="figee|delegant_distinct"), db.begin_nested():
            db.execute(text(requete))
    # Une delegation revoquee ne se reactive pas.
    scene.appeler("dg", "POST", f"/api/delegations/{delegation['id']}/revoquer")
    with proprietaire(), pytest.raises(DBAPIError, match="definitive"), db.begin_nested():
        db.execute(text(f"UPDATE delegations SET revoquee_le = NULL, revoquee_par = NULL "
                        f"WHERE id = '{delegation['id']}'"))


def test_isolation_entre_entreprises(scene, db):
    from app.modules.identite.models import Entreprise
    autre = Entreprise(nom="Autre usine delegations")
    db.add(autre)
    db.flush()
    etranger = Utilisateur(entreprise_id=autre.id, identifiant="resp.autre", nom="Responsable Autre",
                           role="directeur_commercial", mot_de_passe_hash="x", mot_de_passe_modifie_le=maintenant(),
                           cree_le=maintenant())
    db.add(etranger)
    db.commit()
    reponse = scene.deleguer(etranger)
    assert reponse.status_code == 400 and "introuvable" in reponse.json()["detail"]


# --- Taux de change des commandes -------------------------------------------------------------------------------------------------------


def test_estimation_en_gnf_a_partir_du_taux(scene):
    corps = scene.appeler("responsable_stock", "POST", "/api/commandes-achat",
                          json=_commande(scene.base, devise="EUR", taux_change_gnf="9400")).json()
    assert corps["devise"] == "EUR" and corps["taux_change_gnf"] == 9400.0
    assert corps["montant_total"] == 120.0 and corps["montant_total_gnf"] == 120 * 9400
    sans_taux = scene.appeler("responsable_stock", "POST", "/api/commandes-achat",
                              json=_commande(scene.base) | {"taux_change_gnf": None}).json()
    assert sans_taux["montant_total"] == 120.0 and sans_taux["montant_total_gnf"] is None


def test_regles_du_taux_de_change(scene):
    def creer(**extra):
        return scene.appeler("responsable_stock", "POST", "/api/commandes-achat",
                             json=_commande(scene.base, **extra))

    assert creer(taux_change_gnf="0").status_code == 422
    assert creer(taux_change_gnf="-5").status_code == 422
    assert "pas de taux" in creer(devise="GNF", taux_change_gnf="8650").json()["detail"]
    gnf = creer(devise="GNF", taux_change_gnf=None, lignes=[
        {"article_id": str(scene.base["tube"].id), "quantite_commandee": 10, "prix_unitaire": 1000}])
    assert gnf.status_code == 201 and gnf.json()["montant_total_gnf"] == 10000.0
    brouillon = creer().json()
    revise = scene.appeler("responsable_stock", "PUT", f"/api/commandes-achat/{brouillon['id']}",
                           json={"taux_change_gnf": "8700"})
    assert revise.status_code == 200 and revise.json()["montant_total_gnf"] == 120 * 8700
    assert Decimal(str(revise.json()["taux_change_gnf"])) == Decimal("8700")
