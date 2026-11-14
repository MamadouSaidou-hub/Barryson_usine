# 0002 — Mono-client, schéma préparé au multi-entreprise

**Date** : 2026-11-14 · **Statut** : accepté

## Contexte

Le produit est livré pour Group BARRYSON Sarl. Une revente à d'autres usines
est envisagée sans être engagée.

## Décision

Livrer un système **mono-client**, mais porter dès le départ une colonne
`entreprise_id` sur toutes les tables métier, avec une seule valeur active.

- Le filtrage par entreprise se fait à un **point de passage unique** (couche
  repository), jamais dispersé dans les routes.
- Pas d'isolation au niveau base (RLS) ni de sous-domaines pour l'instant :
  complexité non justifiée tant qu'il n'y a qu'un client.

## Conséquences

- Surcoût aujourd'hui : quasi nul (une colonne et un index composite).
- Si une revente se concrétise, on ajoute l'isolation stricte et la facturation
  sans réécrire le schéma ni migrer les données existantes.
- **Règle à tenir** : toute nouvelle table métier porte `entreprise_id`. Une
  table qui l'oublie coûtera cher plus tard.
