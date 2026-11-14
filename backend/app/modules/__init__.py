"""Modules metier.

Un dossier par domaine, chacun autonome (routes, schemas, service, repository) :

    identite/       entreprise, utilisateurs, roles, permissions   -> sprint 2
    referentiel/    articles, entrepots, lots, tiers               -> sprint 3
    stock/          registre de mouvements, soldes, inventaire     -> apres la base
    production/     formules, ordres de fabrication, rendement
    conditionnement/
    ventes/ achats/ livraison/ tresorerie/

Regle : un module ne lit jamais directement les tables d'un autre module,
il passe par le service expose par celui-ci.
"""
