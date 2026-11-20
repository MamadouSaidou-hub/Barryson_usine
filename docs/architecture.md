# Architecture

## Vue d'ensemble

```
Navigateur (React + Vite, installable en PWA)
        │  HTTPS
   Caddy (certificat automatique)
        │
   API FastAPI  ──  modules métier
        │
   PostgreSQL (jamais exposé sur internet)
        │
   Sauvegarde chiffrée quotidienne hors-site, restauration testée chaque mois

   Surveillance (Uptime Kuma, hébergement séparé) ──▶ alerte si API/DB down
   CI/CD (GitHub Actions + Trivy) ──▶ gate sécurité avant déploiement
   Environnement de recette (données anonymisées) ──▶ validé avant la prod
```

## Principes

1. **Les droits sont vérifiés côté serveur.** Masquer un bouton n'est pas une
   sécurité ; chaque appel est contrôlé.
2. **Les quantités et l'argent sont des registres en ajout seul.** Le solde est
   dérivé des mouvements, jamais saisi directement. Cela donne l'historique,
   l'inventaire, et la tolérance aux saisies concurrentes.
3. **Toute écriture sensible laisse une trace nominative** (qui, quoi, valeur
   avant et après, quand) dans un journal d'audit en ajout seul et **chaîné
   par hash** (`entry_hash = sha256(prev_hash || payload || acteur || date)`)
   — toute altération a posteriori casse la chaîne et devient détectable
   (voir `decisions/0004-durcissement-production.md`).
4. **Un module ne lit pas les tables d'un autre module**, il passe par son
   service. C'est ce qui permettra d'en extraire un plus tard sans tout casser.
5. **Les identifiants sont des clés étrangères**, jamais des noms. Renommer un
   fournisseur ne doit rien casser.

## Dettes du prototype corrigées ici

| Prototype | Production |
|---|---|
| CRUD générique sur toutes les tables | Points d'entrée métier explicites et validés |
| Droits appliqués dans le navigateur | RBAC vérifié à chaque appel API |
| SQLite, fichier unique | PostgreSQL, sauvegardes testées |
| `stock = stock + x` | Registre de mouvements, solde dérivé |
| Relations par nom | Clés étrangères |
| Dates en texte (`"18/10"`) | Vrais types date |
| Statuts en texte libre | Machine à états, transitions contrôlées |
| Aucun dépôt de code | Git + intégration continue |

## Ordre de construction

| Sprint | Périmètre |
|---|---|
| 1 | Socle : conteneurs, PostgreSQL, migrations, sondes, tests, CI |
| 2 | Identité : entreprise, utilisateurs, rôles, connexion, RBAC, audit |
| 3 | Référentiel : articles, entrepôts, lots, tiers |
| 4 | Coquille d'interface : connexion, navigation, garde de routes, PWA |
| suite | Stock → Production → Conditionnement, puis amont et aval |

Les quatre premiers sprints ne dépendent d'aucun détail du cahier des charges :
ils peuvent avancer pendant que la direction rassemble ses formules de
fabrication, sa matrice des droits et sa date d'inventaire d'ouverture.

## Durcissement avant mise en service

Voir `decisions/0004-durcissement-production.md` pour le détail : journal
d'audit chaîné par hash, CI/CD avec gate de vulnérabilité (Trivy), objectifs
de sauvegarde chiffrés et testés mensuellement (RPO ≤ 24 h, RTO ≤ 1 jour
ouvré), surveillance active (Uptime Kuma) séparée du journal d'audit métier,
et environnement de recette avec données anonymisées avant chaque mise en
production.
