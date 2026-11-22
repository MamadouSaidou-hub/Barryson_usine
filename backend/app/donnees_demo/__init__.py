"""Donnees reelles servant aux demonstrations et aux tests (jamais chargees en production)."""

import csv
from pathlib import Path

PACKING_LIST_102 = Path(__file__).with_name("packing_list_102_bobines.csv")

# Couleur ecrite par le fournisseur -> finition de l'usine.
FINITIONS = {
    "Gold transparent": "or_transparent",
    "Jaune transparent": "jaune_transparent",
    "Clair transparent": "transparent_clair",
    "Kaki simple": "kaki_simple",
}


def lignes_packing_list_102() -> list[dict]:
    """Les 102 bobines du premier conteneur recu de Chine, au format attendu par l'import de colisage.

    La reference couleur du fournisseur (Golden01, Golden03...) est conservee dans `couleur_brute` :
    elle distingue des productions que la finition de l'usine regroupe.
    """
    with PACKING_LIST_102.open(encoding="utf-8", newline="") as f:
        return [
            {
                "numero_fournisseur": r["numero_bobine"],
                "poids_kg": f"{float(r['poids_net_kg']):.2f}",
                "metrage_propre": f"{float(r['metrage_m']):.2f}",
                "couleur_brute": f"{r['couleur']} / {r['couleur_fournisseur']}",
                "couleur_finition": FINITIONS[r["couleur"]],
            }
            for r in csv.DictReader(f, delimiter=";")
        ]


def catalogue_depuis_packing_list_102() -> list[dict]:
    """Une entree de catalogue par (finition, reference couleur du fournisseur) du conteneur.

    Poids et metrage "types" = moyennes observees ; la note dit sur combien de bobines.
    """
    libelles = {"or_transparent": "or transparent", "jaune_transparent": "jaune transparent",
                "transparent_clair": "transparent clair", "kaki_simple": "kaki simple"}
    groupes: dict[tuple[str, str], list[dict]] = {}
    with PACKING_LIST_102.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            groupes.setdefault((FINITIONS[r["couleur"]], r["couleur_fournisseur"]), []).append(r)
    entrees = []
    for (finition, reference), bobines in groupes.items():
        n = len(bobines)
        entrees.append({
            "code": f"JUMBO-{finition.split('_')[0].upper()}-{reference.replace(' ', '').upper()}",
            "libelle": f"Bobine BOPP {libelles[finition]} — {reference}",
            "couleur_finition": finition,
            "reference_couleur_fournisseur": reference,
            "poids_net_type_kg": f"{sum(float(b['poids_net_kg']) for b in bobines) / n:.2f}",
            "metrage_type_m": f"{sum(float(b['metrage_m']) for b in bobines) / n:.2f}",
            "note": f"Moyennes observées sur {n} bobines du premier conteneur.",
        })
    return sorted(entrees, key=lambda e: e["code"])
