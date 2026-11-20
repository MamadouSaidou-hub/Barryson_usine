"""Commandes d'administration reservees a qui a acces au serveur.

    # Premier administrateur (une seule fois, aucun compte par defaut) :
    docker compose exec api python -m app.modules.identite.cli amorcer \
        --entreprise "Group BARRYSON Sarl" --identifiant admin --nom "Nom Prenom"

    # Dernier recours : seul administrateur ayant perdu son telephone.
    docker compose exec api python -m app.modules.identite.cli reinitialiser-double-facteur \
        --identifiant admin

Le mot de passe est demande au clavier (jamais en argument : il finirait dans
l'historique du shell). Chaque commande laisse une trace dans le journal d'audit.
"""

import argparse
import getpass
import sys

from app.core.db import SessionLocal
from app.modules.identite import service


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Administration des comptes depuis le serveur.")
    commandes = parser.add_subparsers(dest="commande", required=True)
    amorcer = commandes.add_parser("amorcer", help="Cree l'entreprise et le premier administrateur.")
    amorcer.add_argument("--entreprise", required=True)
    amorcer.add_argument("--identifiant", required=True)
    amorcer.add_argument("--nom", required=True)
    reinit = commandes.add_parser("reinitialiser-double-facteur",
                                  help="Efface la double authentification d'un compte.")
    reinit.add_argument("--identifiant", required=True)
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        try:
            if args.commande == "amorcer":
                mot_de_passe = getpass.getpass("Mot de passe (12 caractères minimum) : ")
                if getpass.getpass("Confirmation : ") != mot_de_passe:
                    print("Les deux saisies diffèrent.", file=sys.stderr)
                    return 1
                compte = service.amorcer(db, nom_entreprise=args.entreprise, identifiant=args.identifiant,
                                         nom=args.nom, mot_de_passe=mot_de_passe)
                print(f"Administrateur « {compte.identifiant} » créé. Il configurera sa double "
                      "authentification à la première connexion.")
            else:
                service.reinitialiser_double_facteur_par_console(db, args.identifiant)
                print(f"Double authentification de « {args.identifiant} » effacée ; sessions fermées.")
        except service.ErreurIdentite as erreur:
            print(erreur.message, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
