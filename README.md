# Barryson ERP

ERP de production pour **Group BARRYSON Sarl** (Conakry, Guinée) : matières
premières, jumbos, produits finis, ordres de fabrication, conditionnement,
ventes, livraisons, trésorerie et commissions commerciales.

Monnaie : **GNF**. Langue de l'interface et du métier : **français**.

> Le prototype de démonstration validé par la direction vit dans le dossier
> voisin (`../backend`, `../frontend`). Il reste intact et démontrable ; ce
> dépôt-ci est la version de production, reconstruite sur des bases solides.

## Démarrer en développement

```bash
cp .env.example .env     # adapter le mot de passe
docker compose up --build
```

- API : http://localhost:8000
- Documentation interactive : http://localhost:8000/api/docs
- Sonde de vie : http://localhost:8000/healthz
- Sonde de disponibilité (teste la base) : http://localhost:8000/readyz

PostgreSQL écoute sur `127.0.0.1:15432` (et non 5432, pour ne pas entrer en
conflit avec une installation locale). Accessible depuis la machine uniquement.

## Commandes utiles

```bash
# Tests
docker compose exec api pytest -q

# Qualité du code
docker compose exec api ruff check .

# Créer une migration après avoir modifié un modèle
docker compose exec api alembic revision --autogenerate -m "description"

# Appliquer les migrations
docker compose exec api alembic upgrade head
```

## Structure

```
backend/
  app/
    core/          configuration, base de données, sécurité, audit
    modules/       un dossier par domaine métier (voir modules/__init__.py)
  alembic/         migrations de schéma versionnées
  tests/
docs/
  architecture.md  principes et dettes corrigées
  decisions/       décisions d'architecture et leurs conséquences
```

## Avancement

Objectif : **noyau usine en service en 6 semaines** (stock, production,
conditionnement, ventes). Trésorerie, commissions et mode hors-ligne suivent
après la mise en service. Voir `docs/conventions.md` pour la répartition du
travail entre les deux développeurs.

| Semaine | Contenu | État |
|---|---|---|
| 1 | Socle technique | ✅ |
| 1 | Identité, rôles, RBAC serveur, journal d'audit + mise en ligne | ⏳ |
| 2 | Référentiel (articles, entrepôts, tiers) + portage de l'interface | — |
| 3 | Stock : registre de mouvements, soldes, CMUP, inventaire d'ouverture | — |
| 4 | Production : formules, ordres de fabrication, écarts + conditionnement | — |
| 5 | Achats, ventes, livraisons + documents imprimables | — |
| 6 | Trésorerie, commissions, recette, formation, bascule | — |

Le détail métier (modules M01-M13, matrice de droits, cycle de vie d'un
ordre de fabrication, calcul de prévision BSG, circuit Doctor Rewinder,
circuit de validation, documents à générer) est posé dans
`docs/metier/regles-gestion-usine.md`, à partir du cahier des charges
officiel v1 transmis par la direction le 2026-11-18 (Saal Multi Services).
C'est la référence qui prévaut sur les hypothèses du prototype.

**Dépendances côté client** — sans elles le planning glisse (liste détaillée
en fin de `docs/metier/regles-gestion-usine.md`, §18) :

| Attendu de la direction | Date limite |
|---|---|
| Nomenclature des matières premières/semi-finis + unités de gestion | semaine 2 |
| Recettes de fabrication colles et tubes papier (rendements) | semaine 3 — toujours manquant, point le plus fragile |
| Pièces par carton par modèle + règles de conversion poids/métrage/pièces | semaine 3 |
| Matrice des droits et seuils de validation (achats, dépenses, ajustements) | semaine 2 |
| Inventaire physique d'ouverture | semaine 3 |
| Décision sur le module ventes/commerciaux (voir écart signalé §7 du doc métier) | semaine 2 |
