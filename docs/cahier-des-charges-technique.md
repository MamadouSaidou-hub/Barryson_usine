# Cahier des charges technique — Barryson ERP

Traduit le cahier des charges fonctionnel officiel (`docs/metier/regles-gestion-usine.md`)
en spécification technique exploitable pour construire le projet de bout en
bout. Pas de code ici — uniquement la cible à coder : modèle de données,
machines à états, règles de calcul, RBAC, contrats de module. Ce document est
la référence que les deux développeurs utilisent pour dériver le schéma
PostgreSQL, les endpoints FastAPI et les écrans.

Hiérarchie des documents du dépôt, pour éviter les redites :
- `docs/metier/regles-gestion-usine.md` — ce que le métier a demandé (source).
- `docs/architecture.md` — comment on héberge, déploie, sécurise.
- `docs/conventions.md` — comment on travaille à deux.
- **ce document** — comment le métier devient schéma, API, droits.

## 1. Primitives techniques communes (valables sur tout le périmètre)

Ces quatre règles, posées dans `architecture.md`, se concrétisent ici de la
même façon partout :

1. **Append-only** : aucune table de stock, de caisse ou de commission n'a de
   colonne de solde modifiable directement. Un solde est une vue calculée
   (`SUM(mouvements)`) ou une colonne matérialisée recalculée par trigger/
   job, jamais un `UPDATE ... SET solde = solde + x`.
2. **Séparation saisie/validation** : toute table portant un statut
   `validé`/`clôturé` a deux colonnes d'auteur distinctes — `cree_par` et
   `valide_par` — avec une contrainte applicative (pas seulement UI) qui
   refuse `valide_par = cree_par`.
3. **Journal d'audit** : table unique `journal_audit` (append-only),
   alimentée automatiquement par un hook générique sur chaque écriture
   sensible — table, ligne, action, avant/après (JSON), auteur, date/heure.
   Un module ne doit pas avoir à y penser explicitement à chaque endpoint.
4. **RBAC serveur** : chaque endpoint déclare le ou les rôles autorisés ;
   vérifié par un middleware/dépendance FastAPI, jamais par le frontend seul.
   La matrice de droits (section 3) est la table de vérité, testée.

Tenant unique aujourd'hui, schéma prêt pour le multi-tenant : toute table
métier porte `entreprise_id`, filtré à un point de passage unique
(repository), comme déjà acté dans `docs/decisions/0002-mono-client-schema-prepare.md`.

## 2. Modules et ordre de dépendance technique

| Code | Module | Dépend de | Sprint cible |
|---|---|---|---|
| M01 | Identité, rôles, RBAC, audit | — | 2 (en cours) |
| M02 | Référentiels (articles, unités, moules, modèles de ruban, clients, fournisseurs) | M01 | 2-3 |
| M04/M05 | Stock semi-finis achetés (lots, bobines, mouvements, réservations) + niveau matière première **générique, non prioritaire** (aucun cas d'usage confirmé — réunion usine 2026-11-19, voir `regles-gestion-usine.md` §7.1) | M02 | 3 |
| M03 | Achats et fournisseurs | M02, M04 | 3-5 |
| M06 | Production (ordres de fabrication, prévision, résultat réel) | M04/M05 | 4 |
| M07 | Doctor Rewinder | M06 | 4 |
| M08 | Stock produits finis | M06, M07 | 4 |
| M09/M10 | Ventes, commandes, livraisons, suivi commercial | M08 | 5 |
| M13 | Cockpit / tableaux de bord | tous les modules ci-dessus | en continu, renforcé fin de sprint |
| M11 | Finances (synthèses seulement) | M09 | 6 |
| M12 | RH | M01 (indépendant du reste) | après le noyau usine |

M06/M07/M13 restent prioritaires dans l'implémentation même si, par
dépendance technique, le stock (M04/M05) doit être posé avant.

## 3. Identité, rôles et RBAC (M01)

### 3.1 Entités

- `utilisateurs` : id, entreprise_id, nom, identifiant de connexion, hash de
  mot de passe (argon2), rôle, actif (bool), créé_le.
- `roles` (table de référence, pas une table à éditer en ligne) : `dg`,
  `chef_production`, `directeur_commercial`, `responsable_stock`,
  `comptable`, `responsable_rh`, `administrateur`.
- `sessions` : cookie httpOnly + CSRF token, pas de JWT en localStorage
  (décision déjà actée). Seul le hash SHA-256 du jeton est stocké.
- `tentatives_connexion` : registre en ajout seul, alimente le limiteur par IP.
- `journal_audit` : voir §1.3 — numéroté sans trou, chaîné par hash (ADR 0004).

### 3.2 Matrice de droits (source : cahier des charges officiel §3)

| Rôle | Consultation | Saisie | Validation |
|---|---|---|---|
| `dg` | Tous modules, tous tableaux de bord, journal d'audit, drill-down jusqu'à l'opération d'origine | Aucune obligatoire | Achats, dépenses, transferts, ajustements de stock, sorties exceptionnelles, entrées directes de PF, engagements commerciaux (selon seuils) |
| `chef_production` | Production, Doctor Rewinder, stocks | Fiches modèles, OF, demandes de matières | Résultats de fabrication, clôture OF, traitement Doctor Rewinder |
| `directeur_commercial` | Clients, commandes, ventes, dispo PF, créances, tableaux de bord commerciaux | Clients, commandes, ventes terrain, livraisons, objectifs | Conditions commerciales dans la limite de ses délégations |
| `responsable_stock` | Stocks 3 niveaux, OF ouverts, alertes | Réceptions, packing lists, mouvements, inventaires, demandes d'achat, entrées PF | Contrôle des réceptions, exécution des sorties déjà validées |
| `comptable` | Ventes, créances, achats, synthèses financières | Synthèses caisse/banque, rapprochements | Aucune |
| `responsable_rh` | Dossiers personnel, effectifs, présences | Dossiers, présences, congés, éléments variables de paie | Aucune |
| `administrateur` | Paramètres et journal technique, **jamais les données salariales** | Utilisateurs, rôles, paramètres, sauvegardes | Aucune |

Implémentation : une table de policy statique (`permissions.py` ou
équivalent) mappant `(role, module, action)` → autorisé/refusé, testée
unitairement contre ce tableau. L'absence des commerciaux dans cette table
est volontaire — ils n'ont pas de compte (v1).

### 3.3 Implémentation livrée (2026-11-19) — contrat pour l'interface

**Authentification** (cookie de session `httpOnly`, `SameSite=Strict`,
préfixe `__Host-` hors développement ; le jeton n'est jamais lisible en
JavaScript ni stocké en clair côté serveur) :

| Méthode | Chemin | Rôle | Notes |
|---|---|---|---|
| POST | `/api/auth/connexion` | public | `{identifiant, mot_de_passe}` → `{utilisateur, permissions, csrf_token}` |
| GET | `/api/auth/moi` | connecté | à appeler au chargement de l'app pour retrouver `csrf_token` |
| POST | `/api/auth/deconnexion` | connecté | révoque la session côté serveur |
| POST | `/api/auth/mot-de-passe` | connecté | `{actuel, nouveau}` → nouvelle session (l'ancienne tombe) |
| GET | `/api/utilisateurs` | `utilisateurs.consulter` | |
| POST | `/api/utilisateurs` | `utilisateurs.gerer` | renvoie `mot_de_passe_temporaire` **une seule fois** |
| PATCH | `/api/utilisateurs/{id}` | `utilisateurs.gerer` | `{nom?, role?, actif?}` ; pas sur soi-même |
| POST | `/api/utilisateurs/{id}/reinitialiser-mot-de-passe` | `utilisateurs.gerer` | |
| GET | `/api/audit?limite=&avant=` | `audit.consulter` (DG) | pagination par numéro décroissant |
| GET | `/api/audit/verification` | `audit.verifier` (DG) | recalcule toute la chaîne |
| POST | `/api/auth/double-facteur/initialiser` | connecté | → `{secret, uri}` : afficher `uri` en QR code |
| POST | `/api/auth/double-facteur/activer` | connecté | `{code}` : confirme avec un premier code |
| POST | `/api/utilisateurs/{id}/reinitialiser-double-facteur` | `utilisateurs.gerer` | téléphone perdu ; pas sur soi-même |

**Double authentification (DG et administrateur, obligatoire)** : la
connexion se fait en deux temps. `POST /api/auth/connexion` sans `code`
répond **401 avec `"code_requis": true`** si le mot de passe est bon ;
l'interface affiche alors le champ du code à 6 chiffres et renvoie la même
requête avec `code`. Tant que `double_facteur_a_configurer` est vrai, seul
l'écran de configuration est utilisable.

Règles que l'interface doit connaître :
- toute requête autre que GET envoie l'en-tête `X-CSRF-Token` (sinon 403) ;
- `permissions` sert à **afficher** les menus ; le serveur re-vérifie tout ;
- `doit_changer_mot_de_passe = true` → seul l'écran de changement est
  utilisable (le reste répond 403) ;
- 401 = session absente/expirée → retour à l'écran de connexion ; 403 =
  droit insuffisant ; 413 = requête trop volumineuse (> 1 Mo) ; 429 = trop
  de tentatives depuis ce poste ;
- le message d'échec de connexion est volontairement unique (ne révèle ni
  l'existence du compte ni son verrouillage).

**Mesures de sécurité en place** : argon2id ; politique de mot de passe
NIST (12 caractères min., refus des mots prévisibles, du nom, de
l'identifiant) ; verrouillage progressif du compte (5 échecs → 15 min, puis
doublement, plafond 24 h) et limiteur par adresse IP ; temps de réponse
identique compte existant ou non ; expiration par inactivité (2 h) et durée
maximale (12 h) ; 5 sessions simultanées max ; révocation immédiate au
changement de rôle, désactivation, réinitialisation ; aucun compte par
défaut (premier administrateur créé par commande, mot de passe saisi au
clavier) ; journal d'audit chaîné par hash, numéroté sans trou, protégé par
triggers contre UPDATE/DELETE/TRUNCATE ; en-têtes HTTP de sécurité et filtre
de nom d'hôte ; refus de démarrer hors développement avec un secret par
défaut ; gate Trivy en CI.

Durcissement du 2026-11-20 (toute faille trouvée est corrigée, pas reportée) :
- **compte PostgreSQL à moindre privilège** : l'API se connecte en
  `barryson_app`, ni superutilisateur ni propriétaire. Elle ne peut ni
  modifier le schéma, ni désactiver un trigger, ni modifier/supprimer une
  ligne du journal d'audit ou des tentatives, ni supprimer un compte ou une
  entreprise (testé requête par requête). Les migrations seules utilisent
  le propriétaire. **Règle pour les futurs modules** : une migration qui crée
  un registre en ajout seul (mouvements de stock, caisse...) retire
  `UPDATE, DELETE, TRUNCATE` au groupe `barryson_app_droits` ;
- **double authentification TOTP** (RFC 6238) obligatoire pour le DG et
  l'administrateur, secret chiffré AES-256-GCM, anti-rejeu, mauvais codes
  comptés dans le verrouillage ; la configuration refuse de démarrer en
  production si ces rôles en sont exemptés ;
- **scellés du journal** : `python -m app.core.scelle creer` produit un
  scellé signé du dernier état ; `verifier` recalcule la chaîne et contrôle
  les scellés fournis (code de sortie 1 en cas d'anomalie) — détecte une
  troncature ou une réécriture de la fin du journal ;
- **image de production minimale** : sans pytest, ruff, tests, pip ni
  setuptools ; libpq du système (la roue psycopg-binary embarquait
  Kerberos/OpenSSL/LDAP de CentOS 7, non déclarés à l'analyse) ; GSSAPI
  désactivé côté client (`gssencmode=disable`) ; 0 faille haute/critique
  corrigeable, **aucune dérogation** ;
- limite de 1 Mo par requête (y compris envoi par morceaux) ; force brute du
  mot de passe actuel bloquée sur le changement de mot de passe ;
  description de l'API publiée en développement uniquement.

**Résiduel, expliqué** :
- des CVE Debian **sans correctif publié** (util-linux, ncurses, krb5,
  sqlite…) restent dans l'image de base. Aucune mise à jour ne les corrige.
  Une image « distroless » en compte davantage (89 contre 53 pour la slim,
  mesuré le 2026-11-20). Atténuation : processus non root, aucun de ces
  outils n'est appelé par l'application, Kerberos désactivé. Mise à jour du
  système à chaque construction : dès qu'un correctif paraît, le gate CI
  l'impose ;
- **dépend du déploiement** (pas encore de serveur) : envoyer chaque scellé
  quotidien hors du serveur avec la sauvegarde chiffrée (ADR 0004), et régler
  `FORWARDED_ALLOW_IPS` sur l'adresse de Caddy.

### 3.4 Définition de « fini » pour M01 (rappel de `conventions.md`)

Connexion réelle (mot de passe haché, pas de mot de passe en clair nulle
part) ; RBAC vérifié côté serveur avec tests sur chaque rôle × chaque
endpoint sensible ; un compte sans droit se voit refuser l'accès (test
d'échec, pas seulement de succès) ; chaque écriture sensible trace un auteur
dans `journal_audit`.

## 4. Référentiels (M02)

- `articles` : id, entreprise_id, nom, niveau_stock (`matiere_premiere` |
  `semi_fini` | `produit_fini` — enum, un article = un seul niveau),
  unite_gestion (`kg`, `m`, `rouleau`, `piece`, `panier`, `carton`),
  seuil_min, seuil_max.
- `unites_conversion` : (article_id ou famille, unite_source, unite_cible,
  facteur) — paramétrable par un administrateur sans déploiement.
- `moules` : id, entreprise_id, nom, description.
- `modeles_ruban` : voir §6.1 (versionné).
- `clients`, `fournisseurs` : coordonnées, conditions de paiement/délais
  (fournisseurs), segment/zone/plafond d'encours (clients).

## 5. Stock à trois niveaux (M04/M05/M08)

### 5.1 Principe général

Une seule table de mouvements (`mouvements_stock`), append-only, porte :
id, entreprise_id, article_id, type (`reception`, `entree`, `demande_sortie`,
`sortie`, `consommation`, `transformation`, `transfert`, `retour`,
`ajustement`, `rebut_destruction`, `inventaire`), quantité (signée), unité,
lot_id (nullable), bobine_id (nullable), ordre_fabrication_id (nullable),
cree_par, valide_par (nullable tant que non validé), statut, motif,
piece_justificative_url (nullable), créé_le.

Le **stock disponible** = somme des mouvements validés − réservations
ouvertes (concept introduit dans la version officielle du cahier des
charges, absent du prototype : à ne pas oublier au moment du schéma).

### 5.2 Lots et bobines (niveau matières premières / semi-finis)

- `lots` : id interne, entreprise_id, conteneur_reference, date_reception,
  fournisseur_id.
- `bobines` : id, lot_id, **numero_fournisseur** (pas d'unicité globale —
  l'unicité est `(lot_id, numero_fournisseur)`), poids_kg, metrage_propre,
  couleur_finition (enum : jaune transparent, transparent clair, or
  transparent, kaki simple, kaki imprimé), couleur_impression (nullable :
  rouge/noir/bleu), module_impression (nullable : 45/48/70), statut
  (`disponible`, `entamee_presente`, `epuisee`), documents (liste de
  pièces jointes).
- `bobine_utilisations` : bobine_id, ordre_fabrication_id, metrage_engage,
  date — historique des séances, une bobine pouvant servir à plusieurs OF.
  Aucun champ de métrage restant exigé en v1 (décision client) ; prévoir la
  colonne nullable pour l'évolution paramétrable future, sans l'exposer en
  v1.

### 5.3 Import de packing list (liste de colisage)

Flux en deux temps, jamais une écriture directe :
1. Upload Excel → parsing → table de staging (aperçu), avec détection de
   doublons `(lot, numero_fournisseur)` et contrôle de cohérence
   poids/métrage/finition. Rapport d'erreurs renvoyé à l'utilisateur.
2. Validation explicite par le responsable stock → transformation du
   staging en lignes `bobines` définitives + mouvements `reception`.

### 5.4 Produits finis — deux voies d'entrée distinctes

- **Depuis la fabrication** : généré par la clôture d'un OF (§6.3), jamais
  saisi à la main.
- **Entrée directe** : table dédiée (ou type de mouvement dédié et
  filtrable, pas juste un motif texte) avec `saisi_par` ≠ `valide_par`
  **imposé en base** (contrainte applicative testée), motif obligatoire,
  pièce justificative optionnelle. Distinguée dans tous les états/exports.

### 5.5 Inventaires

Comptage planifié, écarts calculés contre le stock théorique, ajustement
soumis à validation DG/délégataire (jamais auto-appliqué).

## 6. Production (M06) — le cœur du système

### 6.1 Fiche de modèle de ruban (`modeles_ruban`), versionnée

Champs : famille, nom (ex. `BSG 30`), largeur_mm, longueur_rouleau_m,
pieces_par_tour, pieces_par_carton, finition_defaut, moule_id,
nomenclature_semi_finis (liste de `(article_id, quantite_unitaire)`).
**Versionné** : toute modification crée une nouvelle version datée, l'ancien
OF reste lié à la version utilisée au moment de sa création — ne pas faire
un simple `UPDATE` sur la fiche.

Valeurs connues à charger en donnée de référence (pas en dur dans le code) :

| Largeur | Pièces/tour |
|---|---|
| 45 mm | 28 |
| 48 mm | 26 |
| 55 mm | 23 |
| 70 mm | 18 |

Conditionnement connu (table `references_conditionnement`, à compléter plus
tard pour les lignes manquantes — voir §10) :

| Famille | Largeur | Longueur | Pièces/carton |
|---|---|---|---|
| BOPP | 45 mm | 25 m | 90 |
| BOPP | 45 mm | 50 m | 72 |
| BOPP | 45 mm | 100 m | 72 |
| BOPP | 48 mm | 200 m | 36 |
| BOPP | 55 mm | 150 m | 36 |

### 6.2 Ordre de fabrication — machine à états (`ordres_fabrication`)

États et transitions strictement dans cet ordre (pas de saut d'état) :

```
Brouillon → Soumis → Matières validées → En cours
          → Résultat saisi → Résultat validé → Clôturé
          → (Annulé, depuis n'importe quel état avant Clôturé, motif obligatoire)
```

| État | Déclenché par | Rôle |
|---|---|---|
| Brouillon | Choix famille/modèle/lot/bobine/moule/métrage engagé | `chef_production` |
| Soumis | Prévision calculée (§6.3) + demande de matières envoyée | `chef_production` |
| Matières validées | Sortie de stock validée | `responsable_stock` |
| En cours | Fabrication lancée | — (déclaratif) |
| Résultat saisi | Saisie du rapport papier opérateur | agent habilité |
| Résultat validé | Contrôle de cohérence (§6.4) + validation | `chef_production` |
| Clôturé | Génère les mouvements d'entrée en stock PF | `responsable_stock` |
| Annulé | Motif obligatoire | `dg` ou délégataire |

Chaque transition : un endpoint dédié (`POST /of/{id}/soumettre`, pas un
`PATCH` générique sur le statut), qui vérifie l'état courant, le rôle
appelant, et écrit dans `journal_audit`.

### 6.3 Prévision automatique — à coder telle quelle

```
tours_complets    = floor(metrage_engage / longueur_rouleau_m)
pieces_theoriques = tours_complets * pieces_par_tour
cartons_complets  = floor(pieces_theoriques / pieces_par_carton)
pieces_restantes  = pieces_theoriques - (cartons_complets * pieces_par_carton)
```

Cas de test de non-régression (modèle BSG 30 : 25 m, 28 pièces/tour,
90 pièces/carton) :

| Métrage engagé | Tours | Pièces théoriques | Cartons | Pièces restantes |
|---|---|---|---|---|
| 3 900 m | 156 | 4 368 | 48 | 48 |
| 4 000 m | 160 | 4 480 | 49 | 70 |
| 4 100 m | 164 | 4 592 | 51 | 2 |

Le métrage utilisé est **toujours celui réellement saisi sur la bobine**,
jamais une constante.

### 6.4 Résultat réel et contrôle de cohérence

Entrée (saisie) : `tours_totaux`, `tours_defectueux`,
`pieces_defectueuses_supplementaires`, `quantite_doctor_rewinder`,
`pertes_definitives`.

```
pieces_brutes        = tours_totaux * pieces_par_tour
pieces_non_conformes = (tours_defectueux * pieces_par_tour) + pieces_defectueuses_supplementaires

# contrôle bloquant, à exécuter avant d'autoriser le passage à "Résultat validé" :
assert pieces_non_conformes == quantite_doctor_rewinder + pertes_definitives
# sinon -> erreur explicite "double comptage ou omission", transition refusée

pieces_conformes  = pieces_brutes - pieces_non_conformes
cartons_complets  = floor(pieces_conformes / pieces_par_carton)
pieces_restantes  = pieces_conformes - (cartons_complets * pieces_par_carton)
ecart             = pieces_conformes - pieces_theoriques            # valeur et %
rendement         = pieces_conformes / pieces_theoriques
```

Cette formule sera **reconfirmée en atelier avec le chef de production**
avant d'être figée en test de non-régression bloquant (le cahier des charges
le signale explicitement) — l'implémenter derrière un paramètre isolé
(fonction pure, testable séparément) pour pouvoir l'ajuster sans toucher au
reste du cycle de vie de l'OF.

### 6.5 Clôture de l'OF

À `Résultat validé → Clôturé` : génération automatique d'un mouvement
`entree` en stock produits finis, quantité = pièces conformes (en cartons +
pièces restantes), avec le lien `ordre_fabrication_id` conservé sur le
mouvement. Jamais de saisie manuelle de cette entrée.

## 7. Doctor Rewinder (M07)

Table dédiée `encours_doctor_rewinder` (pas un statut sur `produits_finis`) :
id, ordre_fabrication_id, bobine_id, modele_id, metrage, quantite_envoyee,
date_envoi, quantite_recuperee (nullable tant que non traité), quantite_non_recuperable
(nullable), date_traitement, valide_par.

Au traitement : `quantite_recuperee` → génère un mouvement `entree` en stock
PF (après validation) ; `quantite_non_recuperable` → enregistrée comme perte
définitive, pas de mouvement de stock PF.

Indicateurs à exposer au cockpit (§9) : encours en cours (somme non
traitée), taux de récupération (`recuperee / envoyee`), délai moyen de
traitement, ancienneté du plus vieil encours non traité.

## 8. Ventes et suivi commercial (M09/M10)

Pas de compte utilisateur pour les commerciaux (confirmé, définitif pour la
v1). Le directeur commercial (ou un agent habilité) saisit pour leur compte.

- `commandes` : client_id, type (`interentreprises` | `terrain`), lignes de
  commande (article, quantité, prix), statut, commercial (texte libre ou
  FK vers une table `commerciaux` même sans compte de connexion — à
  trancher en atelier, l'essentiel étant que ce ne soit pas juste un champ
  texte non contrôlé).
- `livraisons` : commande_id, date, quantités livrées par ligne. **Le stock
  PF ne diminue qu'à la validation de la livraison**, jamais à la commande.
- Une commande non satisfaite par le stock disponible doit être visible du
  module production (lien de lecture M09 → M06, pas d'écriture croisée).

## 9. Cockpit et tableaux de bord (M13)

Exigence structurante : **chaque indicateur doit pouvoir descendre jusqu'à
l'opération d'origine** (lot, bobine, OF, mouvement, pièce justificative) en
un clic. Concrètement : les vues de synthèse exposées par l'API portent
toujours un identifiant permettant de récupérer le détail sous-jacent — ne
pas construire des agrégats qui perdent la traçabilité vers la ligne source.

Domaines (voir `regles-gestion-usine.md` §13 pour le détail complet des
indicateurs) : production (prioritaire), stocks, achats, ventes, finances,
RH, contrôle (opérations en attente de validation).

## 10. Points encore ouverts (non bloquants pour démarrer, à tenir à jour)

Mis à jour après la « fiche de synthèse » du 2026-11-18 — rien de nouveau
dans ce document par rapport aux manques déjà identifiés. Hors périmètre
immédiat, à ne plus considérer comme prioritaire tant que le module finances
(M11) n'est pas attaqué : le mode d'échange avec un logiciel comptable
externe (Sage ou autre).

Toujours ouverts et à suivre dans `fiche-collecte-infos-manquantes-Barryson.docx` :
- recettes colle papier et tubes papier (bloque le schéma de `modeles_ruban`
  / nomenclature pour ces deux familles — à traiter avant le sprint
  production si la réponse n'arrive pas) ;
- pièces/carton manquantes : BOPP 45 mm (150 m, 1000 m), 55 mm (200 m,
  1000 m), 70 mm (120 m, 1000 m), masquage (24 mm/18 m, 50 mm/20 m) ;
  dimensions PVC électrique à confirmer ;
- méthode de valorisation des stocks / coût de revient (impacte le calcul
  du CMUP, posé comme principe dans `architecture.md` sans formule
  chiffrée) ;
- seuils financiers de validation et délégataires/remplaçants (impacte le
  paramétrage du circuit de validation, pas sa structure technique) ;
- inventaire physique d'ouverture validé par le DG (nécessaire pour la
  reprise de données, pas pour commencer à coder).

Rien de tout cela ne bloque le sprint en cours (identité M01) ni le suivant
(référentiels M02 + début stock M04/M05).
