"""Calculs de fabrication (cahier des charges technique §6.3 et §6.4). Aucune base de donnees."""

from decimal import Decimal

import pytest

from app.modules.production.calculs import (
    ErreurCalcul,
    SaisieResultat,
    calculer_resultat,
    prevoir,
)

BSG30 = {"longueur_rouleau_m": Decimal(25), "pieces_par_tour": 28, "pieces_par_carton": 90}


# --- Prevision : cas de non-regression de la specification --------------------------------------


@pytest.mark.parametrize("metrage,tours,pieces,cartons,restantes", [
    (3900, 156, 4368, 48, 48),
    (4000, 160, 4480, 49, 70),
    (4100, 164, 4592, 51, 2),
])
def test_previsions_de_reference_du_cahier_des_charges(metrage, tours, pieces, cartons, restantes):
    prevision = prevoir(Decimal(metrage), **BSG30)
    assert (prevision.tours_complets, prevision.pieces_theoriques, prevision.cartons_complets,
            prevision.pieces_restantes) == (tours, pieces, cartons, restantes)


def test_seuls_les_tours_complets_comptent():
    # 4 012,5 m / 25 m = 160,5 tours : le demi-tour ne produit rien.
    assert prevoir(Decimal("4012.5"), **BSG30).tours_complets == 160
    assert prevoir(Decimal("24.99"), **BSG30).tours_complets == 0
    assert prevoir(Decimal("24.99"), **BSG30).pieces_theoriques == 0


def test_les_pieces_se_conservent_cartons_et_reste():
    for metrage in range(25, 6000, 137):
        p = prevoir(Decimal(metrage), **BSG30)
        assert p.cartons_complets * 90 + p.pieces_restantes == p.pieces_theoriques
        assert 0 <= p.pieces_restantes < 90


def test_autres_modeles_de_reference():
    # 48 mm x 200 m : 26 pieces par tour, 36 par carton.
    p = prevoir(Decimal(4000), Decimal(200), 26, 36)
    assert (p.tours_complets, p.pieces_theoriques, p.cartons_complets, p.pieces_restantes) == (20, 520, 14, 16)


@pytest.mark.parametrize("arguments", [
    (Decimal(0), Decimal(25), 28, 90), (Decimal(-5), Decimal(25), 28, 90), (Decimal(100), Decimal(0), 28, 90),
    (Decimal(100), Decimal(25), 0, 90), (Decimal(100), Decimal(25), 28, 0),
])
def test_prevision_refuse_des_valeurs_impossibles(arguments):
    with pytest.raises(ErreurCalcul):
        prevoir(*arguments)


# --- Resultat reel ----------------------------------------------------------------------------------


def _saisie(**surcharge) -> SaisieResultat:
    base = {"tours_totaux": 160, "tours_defectueux": 2, "pieces_defectueuses_supplementaires": 10,
            "quantite_doctor_rewinder": 50, "pertes_definitives": 16}
    return SaisieResultat(**{**base, **surcharge})


def test_resultat_coherent_exemple_complet():
    # 160 tours x 28 = 4 480 brutes ; non conformes = 2 x 28 + 10 = 66 = 50 (Doctor Rewinder) + 16 (pertes).
    r = calculer_resultat(_saisie(), 28, 90, pieces_theoriques=4480)
    assert (r.pieces_brutes, r.pieces_non_conformes, r.pieces_conformes) == (4480, 66, 4414)
    assert (r.cartons_complets, r.pieces_restantes) == (49, 4)
    assert (r.ecart_pieces, r.ecart_pourcentage, r.rendement) == (-66, Decimal("-1.47"), Decimal("0.9853"))
    assert r.ecart_comptage == 0 and r.coherent


def test_piece_oubliee_ecart_positif():
    r = calculer_resultat(_saisie(pertes_definitives=10), 28, 90, 4480)
    assert r.ecart_comptage == 6 and not r.coherent


def test_double_comptage_ecart_negatif():
    r = calculer_resultat(_saisie(quantite_doctor_rewinder=60), 28, 90, 4480)
    assert r.ecart_comptage == -10 and not r.coherent


def test_production_parfaite():
    r = calculer_resultat(_saisie(tours_defectueux=0, pieces_defectueuses_supplementaires=0,
                                  quantite_doctor_rewinder=0, pertes_definitives=0), 28, 90, 4480)
    assert (r.pieces_conformes, r.cartons_complets, r.pieces_restantes) == (4480, 49, 70)
    assert (r.ecart_pieces, r.ecart_pourcentage, r.rendement) == (0, Decimal("0.00"), Decimal("1.0000"))
    assert r.coherent


def test_production_superieure_a_la_prevision():
    # Plus de tours que prevu : l'ecart est positif, jamais bloquant a ce niveau.
    r = calculer_resultat(_saisie(tours_totaux=162, tours_defectueux=0, pieces_defectueuses_supplementaires=0,
                                  quantite_doctor_rewinder=0, pertes_definitives=0), 28, 90, 4480)
    assert r.ecart_pieces == 56 and r.rendement > 1


def test_prevision_nulle_ne_divise_pas_par_zero():
    r = calculer_resultat(_saisie(), 28, 90, pieces_theoriques=0)
    assert (r.ecart_pourcentage, r.rendement) == (Decimal(0), Decimal(0))


@pytest.mark.parametrize("surcharge,fragment", [
    ({"tours_totaux": -1}, "negative"),
    ({"pertes_definitives": -5}, "negative"),
    ({"tours_defectueux": 161}, "plus de tours"),
    ({"tours_totaux": 1, "tours_defectueux": 0, "pieces_defectueuses_supplementaires": 29}, "depassent"),
])
def test_resultat_refuse_des_saisies_impossibles(surcharge, fragment):
    with pytest.raises(ErreurCalcul, match=fragment):
        calculer_resultat(_saisie(**surcharge), 28, 90, 4480)
