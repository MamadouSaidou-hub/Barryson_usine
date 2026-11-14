# Conventions de travail

Projet mené **à deux développeurs**, échéance courte (noyau usine en service à
6 semaines). Ces règles existent pour éviter les collisions et les
re-travaux, pas pour faire de la cérémonie.

## Répartition

| Piste | Responsable | Contenu |
|---|---|---|
| **Backend métier** | Dév. 1 | Identité, droits, audit, référentiel, stock, production, ventes |
| **Interface** | Dév. 2 | Portage du design validé, écrans, navigation, formulaires |

Les deux pistes avancent en parallèle grâce au **contrat d'API** (voir plus
bas) : l'interface n'attend pas que le backend soit fini pour se construire.

## Branches et fusion

- `main` est toujours déployable. On n'y pousse jamais directement.
- Une branche par sujet : `feat/stock-registre`, `fix/calcul-cmup`,
  `docs/procedure-restauration`.
- Toute fusion passe par une *pull request* avec **l'intégration continue au
  vert** (ruff + migrations + tests). Pas d'exception, même sous pression :
  c'est précisément sous pression qu'on casse les choses.
- Relecture croisée obligatoire, même rapide. Celui qui n'a pas écrit le code
  doit pouvoir le comprendre sans explication orale.

## Contrat d'API

FastAPI publie automatiquement la description de l'API sur
`/api/openapi.json`. C'est **la source de vérité partagée entre les deux
pistes** :

- Le backend fige la forme d'un point d'entrée **avant** de l'implémenter.
- L'interface génère ses types TypeScript depuis ce fichier, au lieu de les
  réécrire à la main. Une divergence devient alors une erreur de compilation,
  pas un bug découvert en production.

Changer une réponse d'API déjà consommée se signale dans la pull request.

## Langue du code

- **Le métier s'écrit en français** : `mouvement_stock`, `ordre_fabrication`,
  `quantite`, `entreprise_id`. Le client, les utilisateurs et le cahier des
  charges parlent français ; traduire en anglais crée un décalage permanent
  entre ce qui est dit à l'usine et ce qui est écrit dans le code.
- Les termes purement techniques restent dans leur forme usuelle
  (`repository`, `middleware`, `token`).
- Commentaires, messages de commit et documentation : en français.

## Définition de « fini »

Une tâche n'est finie que si :

1. Les tests automatisés couvrent la règle de gestion concernée (pas seulement
   le passant : aussi le cas d'erreur).
2. `ruff check` passe.
3. La migration de schéma existe et s'applique sur une base vierge.
4. Les droits sont vérifiés **côté serveur**, pas seulement masqués à l'écran.
5. Toute écriture sensible laisse une trace dans le journal d'audit.
6. La documentation est à jour si le comportement change.

## Rythme

- Point court en début de journée : ce que je fais, ce qui me bloque.
- Revue en fin de semaine avec une démonstration réelle, pas des captures.
- Ce qui n'est pas démontrable n'est pas terminé.

## Règles non négociables

- Aucun secret dans le dépôt. Tout passe par les variables d'environnement.
- Aucune donnée réelle de l'usine dans les jeux de test.
- Toute nouvelle table métier porte `entreprise_id` (voir décision 0002).
- Les quantités et l'argent s'écrivent en ajout seul, jamais par écrasement
  d'un compteur (voir décision 0003).
