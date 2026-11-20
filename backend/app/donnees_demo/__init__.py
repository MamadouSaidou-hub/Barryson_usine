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
