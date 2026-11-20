"""Journal d'audit : chainage, moindre privilege, inalterabilite, scelles."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.audit import HASH_ORIGINE, JournalAudit, journaliser, sceller, verifier_chaine, verifier_scelle
from app.modules.identite.models import TentativeConnexion
from tests.conftest import se_connecter


def _ecrire(db, n: int) -> None:
    for i in range(n):
        journaliser(db, "test.evenement", apres={"i": i, "texte": "éàç", "decimal": 1.5})
    db.commit()


def test_entrees_numerotees_sans_trou_et_chainees(db):
    _ecrire(db, 5)
    entrees = db.scalars(select(JournalAudit).order_by(JournalAudit.numero)).all()
    assert [e.numero for e in entrees] == list(range(1, len(entrees) + 1))
    assert entrees[0].prev_hash == HASH_ORIGINE
    for precedente, suivante in zip(entrees, entrees[1:], strict=False):
        assert suivante.prev_hash == precedente.entry_hash
    assert verifier_chaine(db)["integre"] is True


def test_la_chaine_survit_a_la_relecture_depuis_la_base(db):
    _ecrire(db, 3)
    db.expire_all()
    resultat = verifier_chaine(db)
    assert resultat["integre"] is True and resultat["entrees_verifiees"] >= 3


# --- Le compte de l'API n'a pas les droits d'alterer quoi que ce soit ---------


@pytest.mark.parametrize("requete", [
    "UPDATE journal_audit SET action = 'effacement'",
    "DELETE FROM journal_audit",
    "TRUNCATE journal_audit",
    "UPDATE tentatives_connexion SET reussie = true",
    "DELETE FROM tentatives_connexion",
    "DELETE FROM utilisateurs",
    "DELETE FROM entreprises",
    "ALTER TABLE journal_audit DISABLE TRIGGER ALL",
    "DROP TRIGGER journal_audit_ajout_seul ON journal_audit",
    "SET session_replication_role = replica",
    "CREATE TABLE porte_derobee (x int)",
    "UPDATE alembic_version SET version_num = 'x'",
])
def test_le_compte_applicatif_ne_peut_rien_alterer(db, requete):
    _ecrire(db, 1)
    with pytest.raises(DBAPIError, match="(?i)permission denied|must be owner"), db.begin_nested():
        db.execute(text(requete))


def test_l_api_ne_se_connecte_pas_en_superutilisateur(db):
    assert db.scalar(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")) is False
    assert db.scalar(text("SELECT current_user")) != db.scalar(text(
        "SELECT tableowner FROM pg_tables WHERE tablename = 'journal_audit'"))


# --- Defense en profondeur : meme le proprietaire est bloque par les triggers --


@pytest.mark.parametrize("requete", [
    "UPDATE journal_audit SET action = 'effacement' WHERE numero = 1",
    "DELETE FROM journal_audit WHERE numero = 1",
    "TRUNCATE journal_audit",
    "DELETE FROM tentatives_connexion",
])
def test_les_triggers_bloquent_aussi_le_proprietaire(db_proprietaire, requete):
    _ecrire(db_proprietaire, 1)
    db_proprietaire.add(TentativeConnexion(identifiant="x", ip=None, reussie=False, motif="test"))
    db_proprietaire.commit()
    with pytest.raises(DBAPIError, match="ajout seul"), db_proprietaire.begin_nested():
        db_proprietaire.execute(text(requete))


# --- Un attaquant superutilisateur qui contourne tout est quand meme detecte ---


def _contourner_les_triggers(db, requete: str) -> None:
    db.execute(text("SET LOCAL session_replication_role = replica"))
    db.execute(text(requete))
    db.execute(text("SET LOCAL session_replication_role = origin"))
    db.expire_all()


def test_une_ligne_falsifiee_est_detectee(db_proprietaire):
    _ecrire(db_proprietaire, 4)
    _contourner_les_triggers(db_proprietaire,
                             "UPDATE journal_audit SET apres = '{\"i\": 99}' WHERE numero = 2")
    resultat = verifier_chaine(db_proprietaire)
    assert resultat["integre"] is False and resultat["premiere_anomalie"] == 2


def test_une_ligne_supprimee_au_milieu_est_detectee(db_proprietaire):
    _ecrire(db_proprietaire, 4)
    _contourner_les_triggers(db_proprietaire, "DELETE FROM journal_audit WHERE numero = 2")
    resultat = verifier_chaine(db_proprietaire)
    assert resultat["integre"] is False and resultat["premiere_anomalie"] == 3


def test_hash_recalcule_par_un_attaquant_reste_detecte(db_proprietaire):
    _ecrire(db_proprietaire, 3)
    _contourner_les_triggers(db_proprietaire, "UPDATE journal_audit SET action = 'x', "
                                              "entry_hash = repeat('a', 64) WHERE numero = 1")
    assert verifier_chaine(db_proprietaire)["premiere_anomalie"] == 1


def test_une_troncature_de_fin_est_detectee_par_le_scelle(db_proprietaire):
    _ecrire(db_proprietaire, 5)
    scelle = sceller(db_proprietaire)
    assert verifier_scelle(db_proprietaire, scelle) is None
    # L'attaquant supprime les dernieres entrees : la chaine restante parait saine...
    _contourner_les_triggers(db_proprietaire,
                             f"DELETE FROM journal_audit WHERE numero >= {scelle['numero'] - 1}")
    assert verifier_chaine(db_proprietaire)["integre"] is True
    # ... mais le scelle conserve hors du serveur le revele.
    assert "tronque" in verifier_scelle(db_proprietaire, scelle)


def test_une_reecriture_de_fin_est_detectee_par_le_scelle(db_proprietaire):
    _ecrire(db_proprietaire, 3)
    scelle = sceller(db_proprietaire)
    _contourner_les_triggers(db_proprietaire, f"DELETE FROM journal_audit WHERE numero = {scelle['numero']}")
    journaliser(db_proprietaire, "entree.substituee")
    db_proprietaire.commit()
    assert "differente" in verifier_scelle(db_proprietaire, scelle)


def test_un_scelle_falsifie_est_rejete(db):
    _ecrire(db, 2)
    scelle = sceller(db)
    assert "signature" in verifier_scelle(db, {**scelle, "numero": scelle["numero"] - 1})


# --- Acces au journal par l'API ---------------------------------------------


def test_seul_le_dg_lit_et_verifie_le_journal(client, creer_compte):
    creer_compte("administrateur")
    se_connecter(client, "administrateur.test")
    assert client.get("/api/audit").status_code == 403
    assert client.get("/api/audit/verification").status_code == 403

    client.cookies.clear()
    creer_compte("dg")
    se_connecter(client, "dg.test")
    verification = client.get("/api/audit/verification")
    assert verification.status_code == 200 and verification.json()["integre"] is True
    entrees = client.get("/api/audit", params={"limite": 5}).json()
    assert entrees and entrees[0]["numero"] > entrees[-1]["numero"]
    actions = {e["action"] for e in client.get("/api/audit").json()}
    assert {"connexion.reussie", "acces.refuse"} <= actions
