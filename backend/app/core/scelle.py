"""Scelles du journal d'audit (ADR 0004).

    # Chaque jour (tache planifiee), le scelle part HORS du serveur avec la sauvegarde :
    python -m app.core.scelle creer > scelle-$(date +%F).json

    # Controle : chaine complete + tous les scelles conserves
    python -m app.core.scelle verifier scelles/*.json

Code de sortie 1 si une anomalie est trouvee : exploitable par la supervision.
"""

import argparse
import json
import sys
from pathlib import Path

from app.core.audit import journaliser, sceller, verifier_chaine, verifier_scelle
from app.core.db import SessionLocal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scelles du journal d'audit.")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("creer", help="Affiche un scelle signe du dernier etat du journal.")
    verifier = actions.add_parser("verifier", help="Verifie la chaine et les scelles fournis.")
    verifier.add_argument("fichiers", nargs="*", type=Path)
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        if args.action == "creer":
            scelle = sceller(db)
            details = {"numero": scelle["numero"], "entry_hash": scelle["entry_hash"]}
            journaliser(db, "audit.scelle", apres=details, acteur_id=None, entreprise_id=None)
            db.commit()
            print(json.dumps(scelle, ensure_ascii=False))
            return 0

        anomalies = []
        chaine = verifier_chaine(db)
        if not chaine["integre"]:
            anomalies.append(f"chaine rompue a l'entree {chaine['premiere_anomalie']}")
        for fichier in args.fichiers:
            probleme = verifier_scelle(db, json.loads(fichier.read_text(encoding="utf-8")))
            if probleme:
                anomalies.append(f"{fichier.name} : {probleme}")
    if anomalies:
        print("ANOMALIE\n" + "\n".join(anomalies), file=sys.stderr)
        return 1
    print(f"Journal integre : {chaine['entrees_verifiees']} entrees, "
          f"{len(args.fichiers)} scelle(s) respecte(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
