"""Charge les donnees de reference deja connues de l'usine.

    docker compose exec api python -m app.modules.referentiel.cli charger-references

Largeurs -> pieces par tour (45/48/55/70 mm) et conditionnements BOPP
confirmes. Relancable sans risque : n'ajoute que ce qui manque, ne modifie
jamais une valeur deja saisie. Chaque ajout est trace dans le journal d'audit.
"""

import argparse
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.identite.models import Entreprise
from app.modules.referentiel import service


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Donnees de reference du referentiel.")
    commandes = parser.add_subparsers(dest="commande", required=True)
    charger = commandes.add_parser("charger-references", help="Charge les references connues de l'usine.")
    charger.add_argument("--entreprise", help="Nom de l'entreprise (obligatoire s'il y en a plusieurs).")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        requete = select(Entreprise)
        if args.entreprise:
            requete = requete.where(Entreprise.nom == args.entreprise)
        entreprises = db.scalars(requete).all()
        if len(entreprises) != 1:
            print("Entreprise introuvable ou ambiguë : précisez --entreprise (après l'amorçage).",
                  file=sys.stderr)
            return 1
        entreprise = entreprises[0]
        db.info.update(acteur_id=None, entreprise_id=entreprise.id, ip="console")
        ajouts = service.charger_references_connues(db, entreprise.id)
    print(f"{entreprise.nom} : {ajouts['largeurs']} largeur(s) et {ajouts['conditionnements']} "
          "conditionnement(s) ajoutés.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
