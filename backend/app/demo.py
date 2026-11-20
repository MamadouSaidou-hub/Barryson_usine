"""Donnees de demonstration, pour montrer l'application au client sans saisir cent fiches.

    docker compose exec api python -m app.demo

Reserve au developpement : refuse de s'executer ailleurs (les comptes ci-dessous partagent un mot de
passe connu, donc jamais en recette ni en production). Relancable : ne cree que ce qui manque.
"""

import sys
from decimal import Decimal

from sqlalchemy import select

from app.core.audit import maintenant
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.identite import mots_de_passe
from app.modules.identite.models import Entreprise, Utilisateur
from app.modules.referentiel import service as referentiel
from app.modules.referentiel.models import Article, Fournisseur, ModeleRuban, Moule

MOT_DE_PASSE = "Lampe-Fleuve-Sable-81"
ENTREPRISE = "Group BARRYSON Sarl"
COMPTES = [
    ("dg.demo", "Directeur Général (démo)", "dg"),
    ("stock.demo", "Responsable stock (démo)", "responsable_stock"),
    ("prod.demo", "Chef de production (démo)", "chef_production"),
    ("commercial.demo", "Directeur commercial (démo)", "directeur_commercial"),
    ("compta.demo", "Comptable (démo)", "comptable"),
    ("admin.demo", "Administrateur (démo)", "administrateur"),
]
ARTICLES = [
    ("JUMBO-BOPP", "Bobine jumbo BOPP 1280 mm", "semi_fini", "rouleau"),
    ("TUBE-PAPIER-45", "Tube papier 45 mm", "semi_fini", "piece"),
    ("CARTON-VIDE", "Carton vide Barryson Adhésif", "semi_fini", "piece"),
    ("BSG30", "BSG 30 — 45 mm x 25 m (carton de 90)", "produit_fini", "carton"),
]


def main() -> int:
    if get_settings().environment != "development":
        print("Refusé : les données de démonstration ne se chargent qu'en développement.", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        entreprise = db.scalar(select(Entreprise).where(Entreprise.nom == ENTREPRISE))
        if entreprise is None:
            entreprise = Entreprise(nom=ENTREPRISE)
            db.add(entreprise)
            db.commit()
        db.info.update(acteur_id=None, entreprise_id=entreprise.id, ip="demo")
        instant = maintenant()
        creees = []
        for identifiant, nom, role in COMPTES:
            if db.scalar(select(Utilisateur.id).where(Utilisateur.identifiant == identifiant)) is None:
                db.add(
                    Utilisateur(
                        entreprise_id=entreprise.id,
                        identifiant=identifiant,
                        nom=nom,
                        role=role,
                        mot_de_passe_hash=mots_de_passe.hacher(MOT_DE_PASSE),
                        doit_changer_mot_de_passe=False,
                        mot_de_passe_modifie_le=instant,
                        cree_le=instant,
                    )
                )
                creees.append(identifiant)
        db.commit()

        for code, nom, niveau, unite in ARTICLES:
            if (
                db.scalar(
                    select(Article.id).where(Article.entreprise_id == entreprise.id, Article.code == code)
                )
                is None
            ):
                db.add(
                    Article(
                        entreprise_id=entreprise.id,
                        code=code,
                        nom=nom,
                        niveau_stock=niveau,
                        unite_gestion=unite,
                        seuil_min=Decimal(10) if unite == "rouleau" else None,
                    )
                )
        if (
            db.scalar(
                select(Fournisseur.id).where(
                    Fournisseur.entreprise_id == entreprise.id, Fournisseur.code == "CHINE-DEMO"
                )
            )
            is None
        ):
            db.add(
                Fournisseur(
                    entreprise_id=entreprise.id,
                    code="CHINE-DEMO",
                    nom="Fournisseur jumbo (Chine, démo)",
                    pays="Chine",
                    delai_livraison_jours=60,
                )
            )
        if (
            db.scalar(select(Moule.id).where(Moule.entreprise_id == entreprise.id, Moule.code == "M45"))
            is None
        ):
            db.add(Moule(entreprise_id=entreprise.id, code="M45", nom="Moule 45 mm"))
        db.commit()
        references = referentiel.charger_references_connues(db, entreprise.id)

        chef = db.scalar(select(Utilisateur).where(Utilisateur.identifiant == "prod.demo"))
        if (
            db.scalar(
                select(ModeleRuban.id).where(
                    ModeleRuban.entreprise_id == entreprise.id, ModeleRuban.code == "BSG-30"
                )
            )
            is None
        ):
            produit = db.scalar(select(Article).where(Article.code == "BSG30"))
            tube = db.scalar(select(Article).where(Article.code == "TUBE-PAPIER-45"))
            moule = db.scalar(select(Moule).where(Moule.code == "M45"))
            modele = referentiel.creer_modele(
                db,
                chef,
                {
                    "code": "BSG-30",
                    "nom": "BSG 30",
                    "famille": "bopp",
                    "largeur_mm": Decimal(45),
                    "longueur_rouleau_m": Decimal(25),
                },
            )
            referentiel.nouvelle_version(
                db,
                chef,
                modele.id,
                {
                    "motif": "Fiche complète (démo)",
                    "moule_id": moule.id,
                    "article_produit_fini_id": produit.id,
                    "article_tube_id": tube.id,
                },
            )

    print(f"Comptes créés : {', '.join(creees) or 'aucun (déjà présents)'}")
    print(f"Références chargées : {references}")
    print(f"\nMot de passe de tous les comptes de démonstration : {MOT_DE_PASSE}")
    print("Le DG et l'administrateur configureront leur double authentification à la première connexion.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
