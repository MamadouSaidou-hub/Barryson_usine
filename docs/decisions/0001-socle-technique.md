# 0001 — Socle technique

**Date** : 2026-11-14 · **Statut** : accepté

## Contexte

Le prototype a convaincu la direction, mais il reposait sur SQLite, un CRUD
générique exposé sur toutes les tables, une authentification simulée dans le
navigateur et du React transpilé à la volée via CDN. Aucun de ces choix ne
tient en production.

## Décision

- **Backend** : FastAPI + SQLAlchemy 2 + Alembic + Pydantic. On conserve Python :
  la logique métier existe déjà et l'équipe la maîtrise.
- **Base de données** : PostgreSQL (concurrence réelle, sauvegardes, types riches).
- **Interface** : React + Vite + TypeScript, compilée, installable en PWA.
- **Hébergement** : un VPS auto-géré, Docker Compose, PostgreSQL jamais exposé
  sur internet.
- **Organisation du code** : par **module métier**, pas par couche technique.

## Conséquences

- Le CRUD générique `/api/{table}` disparaît : chaque écriture passe par un
  point d'entrée explicite, validé et soumis aux droits.
- Chaque règle de gestion devient un service couvert par des tests automatisés.
- Coût d'hébergement estimé : environ 12 EUR par mois, sauvegarde comprise.
- **Contrepartie assumée** : l'auto-gestion impose une discipline de sauvegarde
  et un test de restauration mensuel. Sans cette discipline, il faudra basculer
  vers une base managée.
