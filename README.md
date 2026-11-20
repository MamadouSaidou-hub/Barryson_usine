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

# Base existante créée avant le 2026-11-20 : créer une fois le compte applicatif
docker compose exec db sh /docker-entrypoint-initdb.d/10-role-applicatif.sh

# Créer le premier administrateur (une seule fois, mot de passe demandé au clavier)
docker compose exec api python -m app.modules.identite.cli amorcer \
    --entreprise "Group BARRYSON Sarl" --identifiant admin --nom "Prénom Nom"

# Charger les données usine déjà connues (largeurs, conditionnements) — relançable
docker compose exec api python -m app.modules.referentiel.cli charger-references

# Seul administrateur ayant perdu son téléphone (accès serveur requis, tracé)
docker compose exec api python -m app.modules.identite.cli reinitialiser-double-facteur --identifiant admin

# Scellé du journal d'audit (quotidien, à envoyer hors du serveur) et contrôle
docker compose exec -T api python -m app.core.scelle creer > scelle-$(date +%F).json
docker compose exec -T api python -m app.core.scelle verifier   # chaîne seule ; ajouter les scellés en argument
```

Il n'existe **aucun compte par défaut**. Les autres comptes se créent ensuite
depuis l'API d'administration (`POST /api/utilisateurs`) avec un mot de passe
temporaire à changer à la première connexion. Le DG et l'administrateur
configurent en plus une application d'authentification (code à 6 chiffres).

L'API se connecte avec un compte PostgreSQL **à moindre privilège**
(`POSTGRES_APP_USER`) ; seules les migrations utilisent le propriétaire du
schéma (`POSTGRES_USER`).

## Structure

```
backend/
  app/
    core/          configuration, base de données, sécurité, audit
    modules/       un dossier par domaine métier (voir modules/__init__.py)
  alembic/         migrations de schéma versionnées
  tests/
docs/
  architecture.md               principes et dettes corrigées
  cahier-des-charges-technique.md  modèle de données, machines à états, RBAC, formules — la cible à coder
  decisions/                    décisions d'architecture et leurs conséquences
  metier/                       cahier des charges fonctionnel officiel et points ouverts
```

## Avancement

Objectif : **noyau usine en service en 6 semaines** (stock, production,
conditionnement, ventes). Trésorerie, commissions et mode hors-ligne suivent
après la mise en service. Voir `docs/conventions.md` pour la répartition du
travail entre les deux développeurs.

| Semaine | Contenu | État |
|---|---|---|
| 1 | Socle technique | ✅ |
| 1 | Identité, rôles, RBAC serveur, journal d'audit chaîné | ✅ |
| 1 | Mise en ligne (VPS, Caddy, compte PostgreSQL à moindre privilège) | ⏳ |
| 2 | Référentiel : articles, unités, moules, modèles de ruban versionnés, clients, fournisseurs | ✅ (backend) |
| 2 | Portage de l'interface | — |
| 3 | Stock : registre de mouvements, validations, réservations, lots et bobines, import du packing list | ✅ (backend) |
| 3 | Stock : valorisation (CMUP ?), inventaire d'ouverture | ⏳ attend les décisions du DG |
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
| Nomenclature tube papier ↔ modèle/moule de ruban (pas de recette de fabrication : confirmé le 2026-11-19 qu'aucune matière première n'est transformée sur site) | semaine 3 |
| Pièces par carton par modèle + règles de conversion poids/métrage/pièces | semaine 3 |
| Matrice des droits et seuils de validation (achats, dépenses, ajustements) | semaine 2 |
| Inventaire physique d'ouverture | semaine 3 |
| Décision sur le module ventes/commerciaux (voir écart signalé §7 du doc métier) | semaine 2 |
