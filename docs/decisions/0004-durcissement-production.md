# 0004 — Durcissement production : audit, CI/CD, sauvegarde, observabilité

**Date** : 2026-11-19 · **Statut** : accepté

## Contexte

Les ADR 0001-0003 posent le socle (FastAPI/PostgreSQL/VPS), le schéma
multi-entreprise préparé et la stratégie hors-ligne. Ils ne fixent pas encore
quatre points nécessaires avant une mise en service réelle sur un ERP qui
manipule du stock physique et de l'argent : l'intégrité vérifiable du journal
d'audit, un gate de sécurité avant déploiement, un plan de sauvegarde
*testé* (et pas seulement souhaité), et une surveillance active de
l'application en production. Sans ces quatre points, les principes déjà
posés (traçabilité, robustesse) restent des intentions non vérifiables.

## Décision

### 1. Journal d'audit chaîné par hash

`journal_audit` reste en ajout seul (ADR-0001/architecture.md principe 3),
mais chaque entrée porte en plus :

```
entry_hash = sha256(prev_hash || canonical_json(payload) || acteur_id || horodatage)
```

`prev_hash` référence l'entrée précédente du journal (chaîne globale, pas par
table). Toute altération a posteriori d'une ligne casse la chaîne à partir de
ce point — vérifiable par un script de contrôle d'intégrité exécutable par le
DG ou un auditeur externe, sans accès en écriture à la base. Coût
d'implémentation marginal puisque la table n'existe pas encore (sprint 2 en
cours) : le champ est posé dès la première version du schéma.

### 2. CI/CD avec gate de vulnérabilité

Pipeline GitHub Actions sur `main` :
1. Tests automatisés (pytest + ruff).
2. Build d'image Docker versionnée (tag = commit).
3. Scan Trivy (dépendances + image).
4. **Gate** : une vulnérabilité haute/critique non corrigée bloque le
   déploiement en production, sauf dérogation écrite, motivée et datée.
5. Déploiement de la même image en recette, puis en production après
   validation.

Pas de scan sur chaque PR (coût CI), seulement sur `main` — choix de coût
assumé, à revoir si la fréquence de merge augmente.

### 3. Sauvegarde : objectifs chiffrés et testés

- Sauvegarde PostgreSQL quotidienne, chiffrée, envoyée vers un stockage objet
  compatible S3 (Backblaze ou Scaleway — compte au nom du client), conservée
  30 jours **hors de l'hôte de production**.
- Clés de chiffrement détenues par le client, jamais uniquement sur le VPS
  de production.
- **Vérification quotidienne** que la sauvegarde s'est bien exécutée (alerte
  si échec) et **test de restauration mensuel**, loggé avec sa durée réelle.
- Objectifs : **RPO ≤ 24 h**, **RTO ≤ 1 jour ouvré** une fois un hôte de
  remplacement et les accès disponibles — vérifiés *pendant* le test de
  restauration, pas supposés.
- Procédure de rollback écrite pour chaque déploiement (revenir à l'image
  précédente + dernière sauvegarde cohérente).

### 4. Observabilité séparée du journal d'audit métier

Les sondes `/healthz` et `/readyz` existantes sont surveillées activement par
un outil léger auto-hébergé (Uptime Kuma), sur un hébergement distinct du
VPS de production, qui alerte (email/SMS) en cas d'indisponibilité de l'API
ou de la base. Cette surveillance technique reste strictement séparée du
journal d'audit métier (§1) : l'une regarde si le système fonctionne, l'autre
retrace qui a fait quoi.

### 5. Environnement de recette

Un second environnement (VPS séparé à bas coût, ou second `docker compose`
sur la même machine si le budget ne permet pas deux VPS immédiatement) avec
des données anonymisées, utilisé pour valider chaque déploiement avant la
production. Les vraies données usine n'y sont chargées que ponctuellement,
sous accès restreint, pour la recette métier avec le DG.

## Conséquences

- Surcoût de développement : faible — un champ de hash en plus, un pipeline
  CI à écrire une fois, un outil de monitoring gratuit à déployer.
- Surcoût d'exploitation récurrent : le stockage objet de sauvegarde
  (quelques euros/mois) et, si un second VPS est retenu, son coût
  (~5-12 €/mois selon le fournisseur).
- **Discipline à tenir** : le test de restauration mensuel et la vérification
  quotidienne de sauvegarde doivent être réellement exécutés et logués — une
  sauvegarde jamais restaurée n'est pas une sauvegarde (cf. échange du
  2026-11-19 sur l'architecture).
- Si une dérogation de sécurité (vulnérabilité non corrigée) est acceptée,
  elle doit être écrite, motivée, datée et revue au merge suivant — jamais
  tacite.
