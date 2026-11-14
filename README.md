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

- [x] **Sprint 1 — Socle** : dépôt, conteneurs, PostgreSQL, migrations, sondes, tests, intégration continue
- [ ] **Sprint 2 — Identité & sécurité** : entreprise, utilisateurs, rôles, connexion, RBAC serveur, journal d'audit
- [ ] **Sprint 3 — Référentiel** : articles, entrepôts, lots, tiers, import CSV
- [ ] **Sprint 4 — Coquille d'interface** : React + Vite + TypeScript, connexion, navigation, base PWA
- [ ] Modules métier : Stock, Production, Conditionnement, puis amont et aval
