"""Regles pures du module identite : matrice des droits, mots de passe, verrouillage.
Aucune base de donnees necessaire."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.identite import mots_de_passe
from app.modules.identite.dependances import exiger
from app.modules.identite.permissions import (
    CATALOGUE,
    ROLES,
    ConflitDeSeparation,
    a_la_permission,
    exiger_valideur_distinct,
    matrice,
)
from app.modules.identite.service import duree_verrouillage

# --- Matrice des droits (cahier des charges officiel §3) ---------------------


def test_les_sept_profils_officiels_et_aucun_compte_commercial():
    assert set(ROLES) == {"dg", "chef_production", "directeur_commercial", "responsable_stock",
                          "comptable", "responsable_rh", "administrateur"}
    assert "commercial" not in matrice()


def test_chaque_permission_accordee_existe_et_sert():
    accordees = set().union(*matrice().values())
    assert accordees <= set(CATALOGUE), accordees - set(CATALOGUE)
    assert set(CATALOGUE) <= accordees, set(CATALOGUE) - accordees


def test_le_dg_consulte_tout_et_ne_saisit_rien():
    droits = matrice()["dg"]
    assert all(p in droits for p in CATALOGUE if p.endswith(".consulter"))
    assert not any(p.endswith(".saisir") or p.endswith(".gerer") for p in droits)


def test_l_administrateur_ne_voit_ni_la_paie_ni_l_audit_metier():
    droits = matrice()["administrateur"]
    assert not any(p.startswith("rh.") for p in droits)
    assert "audit.consulter" not in droits
    assert not any(".valider" in p for p in droits)


@pytest.mark.parametrize("role,permission,attendu", [
    ("chef_production", "production.valider", True),
    ("chef_production", "stock.saisir", False),
    ("responsable_stock", "stock.valider_reception", True),
    ("responsable_stock", "stock.valider_ajustement", False),
    ("responsable_stock", "stock.valider_entree_directe", False),
    ("dg", "stock.valider_entree_directe", True),
    ("directeur_commercial", "ventes.valider_conditions", True),
    ("directeur_commercial", "ventes.valider_engagement", False),
    ("comptable", "finances.valider", False),
    ("responsable_rh", "production.consulter", False),
    ("role_inexistant", "production.consulter", False),
])
def test_matrice_points_cles(role, permission, attendu):
    assert a_la_permission(role, permission) is attendu


def test_seuls_le_comptable_et_rh_n_ont_aucune_validation():
    sans_validation = {r for r, d in matrice().items() if not any(".valider" in p for p in d)}
    assert sans_validation == {"comptable", "responsable_rh", "administrateur"}


def test_une_permission_mal_orthographiee_casse_au_demarrage():
    with pytest.raises(ValueError):
        exiger("production.valder")


def test_separation_saisie_validation():
    exiger_valideur_distinct("a", "b")
    with pytest.raises(ConflitDeSeparation):
        exiger_valideur_distinct("a", "a")
    with pytest.raises(ConflitDeSeparation):
        exiger_valideur_distinct("a", None)


# --- Mots de passe -----------------------------------------------------------


def test_hachage_argon2id_et_verification():
    h = mots_de_passe.hacher("Grenier-Lampe-Orage-58")
    assert h.startswith("$argon2id$")
    assert "Grenier" not in h
    assert mots_de_passe.verifier(h, "Grenier-Lampe-Orage-58")
    assert not mots_de_passe.verifier(h, "grenier-lampe-orage-58")
    assert not mots_de_passe.verifier("pas-un-hash", "x")
    assert not mots_de_passe.verifier(h, "x" * 5000)


def test_deux_hachages_du_meme_mot_de_passe_different():
    assert mots_de_passe.hacher("Grenier-Lampe-Orage-58") != mots_de_passe.hacher("Grenier-Lampe-Orage-58")


@pytest.mark.parametrize("candidat", [
    "court1!", "Barryson2026!!", "motdepasse123", "azertyuiop12", "aaaaaaaaaaaaaaaa",
    "x" * 129, "jean.diallo-2026", "Mamadou-Diallo-77",
])
def test_politique_refuse(candidat):
    assert mots_de_passe.verifier_politique(candidat, identifiant="jean.diallo", nom="Mamadou Diallo")


def test_politique_accepte_une_phrase_longue():
    assert mots_de_passe.verifier_politique("Grenier-Lampe-Orage-58", identifiant="jean.diallo") == []


def test_mot_de_passe_temporaire_conforme_et_imprevisible():
    tirages = {mots_de_passe.generer_temporaire() for _ in range(50)}
    assert len(tirages) == 50
    assert all(mots_de_passe.verifier_politique(t) == [] for t in tirages)


def test_verrouillage_progressif_plafonne():
    assert duree_verrouillage(4, 5, 15) == timedelta(0)
    assert duree_verrouillage(5, 5, 15) == timedelta(minutes=15)
    assert duree_verrouillage(6, 5, 15) == timedelta(minutes=30)
    assert duree_verrouillage(500, 5, 15) == timedelta(hours=24)


# --- Configuration -----------------------------------------------------------


def test_la_production_refuse_les_valeurs_par_defaut():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(environment="production", hotes_autorises=["erp.exemple.com"],
                 postgres_password="fort-et-long")
    with pytest.raises(ValidationError, match="POSTGRES_PASSWORD"):
        Settings(environment="production", secret_key="k" * 40, hotes_autorises=["erp.exemple.com"])


_PROD = {"environment": "production", "secret_key": "k" * 40, "postgres_password": "fort-et-long",
         "postgres_app_password": "autre-et-long", "hotes_autorises": ["erp.exemple.com"]}


def test_la_production_impose_le_cookie_securise_et_ferme_la_documentation():
    s = Settings(**_PROD)
    assert s.cookie_securise
    assert s.nom_cookie_session.startswith("__Host-")
    assert not s.docs_publiques
    assert not Settings(**{**_PROD, "environment": "staging"}).docs_publiques


@pytest.mark.parametrize("surcharge,message", [
    ({"postgres_app_password": "changeme_app"}, "POSTGRES_APP_PASSWORD"),
    ({"postgres_app_password": "fort-et-long"}, "POSTGRES_APP_PASSWORD"),
    ({"postgres_app_user": "barryson"}, "POSTGRES_APP_USER"),
    ({"roles_double_facteur": ["dg"]}, "second facteur"),
    ({"roles_double_facteur": []}, "second facteur"),
])
def test_la_production_refuse_les_configurations_affaiblies(surcharge, message):
    with pytest.raises(ValidationError, match=message):
        Settings(**{**_PROD, **surcharge})


def test_l_api_et_les_migrations_n_utilisent_pas_le_meme_compte():
    s = Settings(**_PROD)
    assert "barryson_app:" in s.database_url
    assert "barryson_app" not in s.database_url_proprietaire
