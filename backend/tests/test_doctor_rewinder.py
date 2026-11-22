"""Doctor Rewinder (M07) : de l'envoi des pieces a rectifier a leur entree en stock, apres validation."""

import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.erreurs import OperationInterdite
from app.modules.doctor_rewinder import service as doctor_rewinder
from app.modules.identite.models import Utilisateur
from app.modules.stock.models import MouvementStock
from tests.test_production import atelier, usine  # noqa: F401  (fixtures de l'atelier)

# 3 tours defectueux (84 pieces) + 16 pieces : 100 non conformes, tous envoyes au Doctor Rewinder.
CENT_A_RECTIFIER = {"tours_defectueux": 3, "pieces_defectueuses_supplementaires": 16,
                    "quantite_doctor_rewinder": 100, "pertes_definitives": 0}


def _cloturer(atelier, **resultat) -> dict:
    ordre = atelier.jusqu_a_en_cours()
    atelier.resultat(ordre, **resultat)
    atelier.faire("dg", ordre, "valider-resultat")
    return atelier.faire("responsable_stock", ordre, "cloturer")


def _appel(atelier, profil, methode, chemin, attendu=200, **corps):
    reponse = atelier._appeler(profil, methode, chemin, **corps)
    assert reponse.status_code == attendu, (chemin, reponse.status_code, reponse.text)
    return reponse.json()


def _encours(atelier, profil="chef_production", **filtres) -> list[dict]:
    return _appel(atelier, profil, "GET", "/api/doctor-rewinder", params=filtres)


def _traiter(atelier, encours, recuperee, perdue, attendu=200, profil="chef_production"):
    return _appel(atelier, profil, "PUT", f"/api/doctor-rewinder/{encours['id']}/traitement", attendu,
                  json={"quantite_recuperee": recuperee, "quantite_non_recuperable": perdue})


def _valider(atelier, encours, attendu=200, profil="dg"):
    return _appel(atelier, profil, "POST", f"/api/doctor-rewinder/{encours['id']}/valider", attendu)


def _solde_produit(atelier) -> float:
    lignes = _appel(atelier, "responsable_stock", "GET", "/api/stock/soldes",
                    params={"article_id": str(atelier.usine["produit"].id)})
    return lignes[0]["physique"] if lignes else 0


def test_la_cloture_ouvre_un_encours_pour_les_pieces_envoyees(atelier):
    ordre = _cloturer(atelier)
    [encours] = _encours(atelier)
    assert encours["ordre_id"] == ordre["id"] and encours["bobine_id"] == ordre["bobine_id"]
    assert encours["quantite_envoyee"] == 50 and encours["statut"] == "en_cours"
    assert encours["date_envoi"] == date.today().isoformat() and encours["quantite_recuperee"] is None


def test_rien_envoye_aucun_encours(atelier):
    _cloturer(atelier, quantite_doctor_rewinder=0, pertes_definitives=66)
    assert _encours(atelier) == []


def test_tout_ce_qui_est_parti_doit_etre_compte(atelier):
    _cloturer(atelier)
    [encours] = _encours(atelier)
    refus = _traiter(atelier, encours, 30, 10, attendu=400)
    assert "50 pièces" in refus["detail"] and "40" in refus["detail"]
    assert _traiter(atelier, encours, 30, 20)["statut"] == "a_valider"


def test_qui_fait_quoi(atelier):
    _cloturer(atelier)
    [encours] = _encours(atelier)
    _traiter(atelier, encours, 30, 20, profil="dg", attendu=403)  # le DG ne saisit pas
    _traiter(atelier, encours, 30, 20, profil="responsable_stock", attendu=403)
    _traiter(atelier, encours, 30, 20)
    # Le chef declare, il ne valide pas ; le magasinier ne voit meme pas l'encours.
    _valider(atelier, encours, 403, profil="chef_production")
    _appel(atelier, "responsable_stock", "GET", "/api/doctor-rewinder", 403)
    _valider(atelier, encours)


def test_la_validation_fait_entrer_les_pieces_recuperees_en_stock(atelier, usine):
    _cloturer(atelier, **CENT_A_RECTIFIER)
    avant = _solde_produit(atelier)
    [encours] = _encours(atelier)
    _traiter(atelier, encours, 95, 5)
    # Declare, mais pas encore valide : rien n'entre en stock.
    assert _encours(atelier)[0]["statut"] == "a_valider" and _solde_produit(atelier) == avant
    valide = _valider(atelier, encours)
    # Article gere au carton (90 pieces) : 1 carton complet, 5 pieces de reliquat visibles, 5 perdues.
    assert valide["statut"] == "traite" and valide["pieces_reliquat"] == 5
    assert valide["quantite_non_recuperable"] == 5 and valide["valide_par"] is not None
    assert _solde_produit(atelier) == avant + 1
    mouvement = usine["db"].get(MouvementStock, uuid.UUID(valide["mouvement_id"]))
    assert mouvement.type == "entree" and mouvement.ordre_fabrication_id == uuid.UUID(valide["ordre_id"])
    assert "Doctor Rewinder" in mouvement.motif


def test_aucune_piece_recuperee_aucun_mouvement(atelier):
    _cloturer(atelier)
    [encours] = _encours(atelier)
    _traiter(atelier, encours, 0, 50)
    valide = _valider(atelier, encours)
    assert valide["statut"] == "traite" and valide["mouvement_id"] is None


def test_on_ne_valide_pas_ce_qu_on_a_declare(atelier, usine):
    _cloturer(atelier)
    [encours] = _encours(atelier)
    declare = _traiter(atelier, encours, 30, 20)
    declarant = usine["db"].get(Utilisateur, uuid.UUID(declare["traite_par"]))
    # Meme avec le droit (delegation, par exemple), le declarant ne peut pas valider sa propre saisie.
    with pytest.raises(OperationInterdite, match="autre personne"):
        doctor_rewinder.valider(usine["db"], declarant, uuid.UUID(encours["id"]))


def test_valider_ou_traiter_au_mauvais_moment_est_refuse(atelier):
    _cloturer(atelier)
    [encours] = _encours(atelier)
    _valider(atelier, encours, 409)  # pas encore traite
    _traiter(atelier, encours, 30, 20)
    _valider(atelier, encours)
    _valider(atelier, encours, 409)  # une seule entree en stock
    _traiter(atelier, encours, 10, 40, attendu=409)


def test_un_traitement_conteste_est_renvoye(atelier):
    _cloturer(atelier)
    [encours] = _encours(atelier)
    _traiter(atelier, encours, 30, 20)
    chemin = f"/api/doctor-rewinder/{encours['id']}/renvoyer"
    _appel(atelier, "dg", "POST", chemin, 422, json={"motif": "ok"})  # motif trop court
    renvoye = _appel(atelier, "dg", "POST", chemin, json={"motif": "Recomptez les pièces perdues"})
    assert renvoye["statut"] == "en_cours" and renvoye["quantite_recuperee"] is None
    assert "Recomptez" in renvoye["commentaire"]
    _traiter(atelier, encours, 45, 5)


def test_indicateurs_du_cockpit(atelier):
    vide = _appel(atelier, "dg", "GET", "/api/doctor-rewinder/indicateurs")
    assert vide["encours_ouverts"] == 0 and vide["taux_recuperation"] is None
    assert vide["anciennete_max_jours"] is None and vide["plus_ancien_id"] is None
    _cloturer(atelier)
    [encours] = _encours(atelier)
    ouvert = _appel(atelier, "dg", "GET", "/api/doctor-rewinder/indicateurs")
    assert ouvert["encours_ouverts"] == 1 and ouvert["pieces_en_cours"] == 50
    assert ouvert["plus_ancien_id"] == encours["id"] and ouvert["anciennete_max_jours"] == 0
    _traiter(atelier, encours, 40, 10)
    _valider(atelier, encours)
    clos = _appel(atelier, "dg", "GET", "/api/doctor-rewinder/indicateurs")
    assert clos["encours_ouverts"] == 0 and clos["pieces_recuperees"] == 40
    assert clos["taux_recuperation"] == pytest.approx(0.8) and clos["delai_moyen_jours"] == 0


def test_filtre_par_statut_et_detail(atelier):
    _cloturer(atelier)
    [encours] = _encours(atelier)
    assert _encours(atelier, statut="traite") == [] and len(_encours(atelier, statut="en_cours")) == 1
    detail = _appel(atelier, "chef_production", "GET", f"/api/doctor-rewinder/{encours['id']}")
    assert detail["id"] == encours["id"]
    _appel(atelier, "chef_production", "GET", f"/api/doctor-rewinder/{uuid.uuid4()}", 404)


def test_un_encours_ne_se_supprime_pas(atelier, usine):
    _cloturer(atelier)
    with pytest.raises(DBAPIError, match="permission denied"), usine["db"].begin_nested():
        usine["db"].execute(text("DELETE FROM encours_doctor_rewinder"))
