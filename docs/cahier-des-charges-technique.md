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

### 4.1 Implémentation livrée (2026-11-20) — contrat pour l'interface

| Ressource | Chemins | Lecture | Écriture |
|---|---|---|---|
| Articles | `/api/articles` (`?niveau=&actif=&recherche=`), `/{id}` | `referentiels.consulter` | `referentiels.saisir` (resp. stock) |
| Conversions d'unités | `/api/conversions-unites` | `referentiels.consulter` | `referentiels.saisir` |
| Moules | `/api/moules` | `modeles.consulter` | `modeles.saisir` (chef de production) |
| Largeurs → pièces/tour | `/api/references/largeurs` | `modeles.consulter` | `modeles.saisir` |
| Conditionnements | `/api/references/conditionnements` | `modeles.consulter` | `modeles.saisir` |
| Modèles de ruban | `/api/modeles-ruban`, `/{id}`, `/{id}/versions` | `modeles.consulter` | `modeles.saisir` |
| Clients | `/api/clients`, `/{id}` | `clients.consulter` | `clients.saisir` (dir. commercial) |
| Fournisseurs | `/api/fournisseurs`, `/{id}` | `achats.consulter` | `achats.saisir` (resp. stock) |

Méthodes : `GET` (liste, 500 max), `POST` (création), `PATCH` (modification
partielle : seuls les champs envoyés changent, `null` efface un champ
facultatif). **Aucun `DELETE`** : on désactive avec `{"actif": false}`, et la
base refuse la suppression au compte de l'API.

Règles appliquées :
- codes normalisés en majuscules, uniques par entreprise ;
- niveau de stock, unité, code et famille **ne se modifient jamais** (champs
  absents des schémas de modification → 422) ;
- article de niveau `matiere_premiere` refusé (403) tant que le réglage
  `NIVEAU_MATIERE_PREMIERE_ACTIF` est faux ;
- **modèle de ruban versionné** : `POST /{id}/versions` avec un `motif`
  obligatoire crée la version suivante ; les champs absents sont repris de la
  version en vigueur ; si largeur ou longueur changent, pièces/tour et
  pièces/carton sont recalculées depuis les références (ou fournies). Les
  versions sont figées en base, même pour le propriétaire du schéma ;
- `complet: true` quand moule, produit fini et tube papier sont renseignés —
  condition à vérifier au lancement d'un ordre de fabrication (M06) ;
- tube papier = article `semi_fini`, produit fini = article `produit_fini`
  (contrôlé).

Données de l'usine déjà connues : `python -m app.modules.referentiel.cli
charger-references` (4 largeurs, 5 conditionnements BOPP confirmés ;
relançable sans risque, n'écrase jamais une valeur corrigée par l'usine).

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

### 5.6 Implémentation livrée (2026-11-20) — contrat pour l'interface

**Principe** : le stock n'est jamais un compteur, c'est la somme des
mouvements. Un mouvement ne se modifie ni ne se supprime (privilèges + trigger,
même pour le propriétaire du schéma) ; une erreur se corrige par un
mouvement inverse. Les quantités sont envoyées **positives** : le sens vient
du type (ou de `sens` pour un ajustement).

| Méthode | Chemin | Droit | Rôle |
|---|---|---|---|
| GET | `/api/stock/soldes` (`?niveau=&article_id=&sous_seuil=`) | `stock.consulter` | physique, réservé, disponible, négatif, sous seuil, nb en attente |
| GET | `/api/stock/mouvements` (`?article_id=&type=&statut=&avant=&limite=`) | `stock.consulter` | `statut` : `en_attente`, `valide`, `rejete` |
| POST | `/api/stock/mouvements` | `stock.saisir` | types : `entree_directe` (produits finis), `ajustement` (+ `sens`), `sortie_exceptionnelle`, `rebut_destruction` |
| POST | `/api/stock/mouvements/{id}/validation` | selon le type (voir ci-dessous) | `{decision: valide\|rejete, motif}` ; rejet motivé |
| GET/POST | `/api/stock/reservations`, `/{id}/lever` | `stock.consulter` / `stock.saisir` | refusée si > disponible (409) |
| GET | `/api/lots`, `/api/lots/{id}`, `/api/bobines` (`?lot_id=&statut=&couleur=`) | `stock.consulter` | |
| POST | `/api/receptions` | `stock.saisir` | saisie directe d'un conteneur (quelques bobines) |
| POST | `/api/imports-colisage` | `stock.saisir` | étape 1 : aperçu + anomalies, **rien en stock** |
| GET | `/api/imports-colisage`, `/{id}` | `stock.consulter` | |
| POST | `/api/imports-colisage/{id}/valider` | `stock.valider_reception` | étape 2 : crée lot, bobines, réceptions |
| POST | `/api/imports-colisage/{id}/annuler` | `stock.saisir` | |

Valideur par type : `entree_directe` → `stock.valider_entree_directe` (DG) ;
`ajustement` → `stock.valider_ajustement` (DG) ; `sortie_exceptionnelle` et
`rebut_destruction` → `stock.valider_sortie_exceptionnelle` (DG). Un
mouvement en attente ou rejeté **ne compte pas** dans le stock.

**Séparation saisie/validation, en trois couches** : l'API (403 + trace
`validation.refusee_meme_personne`), le service, et un trigger PostgreSQL qui
refuse un valideur identique à l'auteur même sur une requête SQL directe.

**Types non exposés** : `reception`, `entree` (fabrication), `consommation`,
`sortie` (livraison), `retour`, `transformation`, `inventaire` sont produits
par les modules concernés via `service.enregistrer_mouvement`, jamais forgés
par un appel HTTP (422).

**Import du packing list** : l'API reçoit des **lignes JSON** (max 2000) ; la
lecture du fichier Excel et la correspondance des colonnes/finitions se font à
l'écran d'aperçu côté interface. Le serveur garde la valeur brute du
fournisseur (`couleur_brute`, ex. « Golden01 ») à côté de la finition choisie.
Anomalies **bloquantes** (empêchent la validation) : numéro manquant ou en
double, poids manquant, finition non associée, impression sur une bobine non
imprimée. **Avertissements** : métrage manquant (courant : la bobine ne
servira à aucune prévision tant qu'il n'est pas renseigné), poids éloigné de
plus de 10 % de la médiane (dès 10 lignes). Un conteneur déjà reçu, ou déjà
en cours d'import, est refusé (409) ; la validation revérifie l'état du
moment.

Limites connues, assumées pour cette livraison :
- **pas de lecture Excel côté serveur** : surface d'attaque (archives piégées)
  à n'ouvrir que si l'interface ne peut pas le faire ;
- **deux feuilles d'un même conteneur** (poids net / métrage et poids brut,
  sans clé commune — voir `regles-gestion-usine.md` §7.2) : à rapprocher
  manuellement avant l'envoi, un import = un conteneur = une liste de lignes ;
- la saisie et le contrôle des réceptions reviennent tous deux au
  responsable stock (matrice officielle) : la séparation de personnes n'y est
  donc pas imposée, seulement tracée (auteur et valideur enregistrés) ;
- la valorisation (CMUP ou autre) reste à définir avec le DG : chaque
  mouvement porte déjà `cout_unitaire_gnf` (vide), aucune migration ne sera
  nécessaire ;
- l'inventaire d'ouverture et les inventaires périodiques (§5.5) ne sont pas
  encore faits.

**Règle PostgreSQL à retenir pour les prochains modules** : `SELECT ... FOR
UPDATE` exige le droit `UPDATE`. Sur un registre en ajout seul, le compte de
l'API ne l'a pas (voulu) : l'exclusion mutuelle passe par une contrainte
d'unicité (ex. une seule validation par mouvement), pas par un verrou de
ligne. Testé sous charge : 8 réservations simultanées sur 10 rouleaux → 3
acceptées, aucune surréservation ; 8 validations simultanées → 1 seule.

### 5.7 Approvisionnement : commande, réception, contrôle (M03) — livré le 2026-11-20

Circuit : **commande préparée → soumise → validée par le DG → passée au
fournisseur → marchandise arrivée → contrôle de conformité → entrée en stock des
seules quantités acceptées.** Rien n'entre en stock à l'arrivée : seul le
contrôle crée des mouvements.

| Méthode | Chemin | Droit | Rôle |
|---|---|---|---|
| GET | `/api/commandes-achat` (`?statut=&fournisseur_id=&en_attente_marchandise=`) | `achats.consulter` | `en_attente_marchandise` : conteneurs attendus, plus proches d'abord |
| GET | `/api/commandes-achat/{id}` | `achats.consulter` | lignes (commandé, reçu accepté, solde, montant), total, réceptions, historique |
| POST / PUT | `/api/commandes-achat`, `/{id}` | `achats.saisir` (resp. stock) | création ; modification en brouillon (les lignes envoyées remplacent les anciennes) |
| POST | `…/soumettre` | `achats.saisir` | brouillon → soumise |
| POST | `…/valider`, `…/refuser` (`motif`) | `achats.valider` (DG) | soumise → validée / refusée |
| POST | `…/commander` | `achats.saisir` | validée → commandée (+ référence proforma) |
| POST | `…/annuler` (`motif`) | initiateur avant validation, DG ensuite | refusée si une réception attend son contrôle |
| POST | `…/solder` (`motif`) | `achats.saisir` | partiellement reçue → clôturée (reliquat abandonné) |
| POST | `…/receptions` | `stock.saisir` | la marchandise est arrivée : réception **en contrôle** |
| GET | `/api/receptions-achat` (`?statut=&commande_id=&avec_ecarts=`), `/{id}` | `achats.consulter` | `avec_ecarts` : litiges (réserves ou refus) |
| POST | `/api/receptions-achat/{id}/controle` | `stock.valider_reception` (resp. stock) | `acceptee` / `acceptee_avec_reserves` / `refusee` |

**Bobines** : une réception de bobines s'appuie sur une packing list déjà
analysée (`POST /api/imports-colisage`, §5.6) et rattachée à la réception. La
quantité reçue vaut alors le nombre de bobines de la liste. Une packing
list rattachée ne peut plus être validée ni annulée à part : seul le contrôle
de sa réception la valide, ce qui supprime tout contournement du contrôle.
Elle doit venir du même fournisseur et porter sur le même article que la
ligne de commande, sans anomalie bloquante.

**Contrôle de conformité** (documentaire puis quantitatif) :
- `acceptee` : tout est conforme, documents compris ;
- `acceptee_avec_reserves` : écart constaté (document manquant, quantité
  réduite, bobine refusée). Chaque écart de quantité exige un motif, et un
  commentaire d'ensemble est obligatoire ;
- `refusee` : rien n'entre en stock, commentaire obligatoire ; la packing
  list est libérée pour être refaite.
Une bobine refusée (`bobines_refusees`, par numéro fournisseur) n'est jamais
créée. La décision est **définitive** : la base refuse de rouvrir une
réception ou ses lignes, même au propriétaire du schéma.

**Suivi** : le reçu et le solde d'une ligne ne comptent que les quantités
**acceptées**. La commande passe seule à `partiellement_recue` puis `recue`.
Une réception dont la quantité dépasse le solde est signalée par un
avertissement lisible avant le contrôle (jamais bloquant en soi), de même
que les anomalies de la packing list ou une finition différente de celle
commandée.

**Séparation** : celui qui prépare la commande ne peut pas la valider
(contrôlé par le service **et** par une contrainte de la base).
Les lignes d'une commande sont **figées en base** dès la soumission.

Choix à confirmer avec le DG :
- **Seuils de validation** : tant qu'ils ne sont pas fixés (fiche de
  collecte), **toute commande passe par le DG**, quel que soit son montant ;
- **Devise** : la commande est dans une devise (USD, EUR, CNY, GNF) ; les
  prix sont facultatifs et ne sont pas convertis en GNF. La valorisation du
  stock reste à définir ;
- **Documents imprimables** (bon de commande, bon de réception) : l'API
  fournit tout le contenu structuré, la mise en page revient à l'interface ;
- **Rapprochement facture / paiement** : relève du module finances (M11),
  non fait ;
- la réception directe hors commande (`POST /api/receptions`, import seul)
  reste disponible pour reprendre le **stock existant** à la mise en service.

Testé sous charge réelle : 6 validations DG simultanées → 1 ; 6 contrôles
simultanés de la même réception → 1 seul, la marchandise entre en stock une
fois (5 000 tubes, 5 bobines).

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

### 6.6 Implémentation livrée (2026-11-20) — contrat pour l'interface

Un point d'entrée par transition, jamais de `PATCH` sur le statut. Chacune
vérifie l'état courant (409 sinon), le droit de l'appelant, et s'inscrit dans
`transitions_ordre_fabrication` (registre en ajout seul : qui, quand, motif).

| Méthode | Chemin | Droit | De → vers |
|---|---|---|---|
| POST | `/api/production/previsions` | `production.consulter` | prévision sans rien créer (écran de préparation) |
| GET | `/api/ordres-fabrication` (`?statut=&bobine_id=&modele_id=`), `/{id}` | `production.consulter` | détail : prévision, saisie, résultat calculé, transitions |
| POST | `/api/ordres-fabrication` | `production.saisir` (chef de production) | → brouillon |
| PATCH | `/api/ordres-fabrication/{id}` | `production.saisir` | brouillon seulement : métrage, commentaire |
| POST | `…/soumettre` | `production.saisir` | brouillon → soumis : fige la prévision, réserve les tubes |
| POST | `…/valider-matieres` | `stock.executer_sortie` (resp. stock) | soumis → matières validées : sortie des tubes |
| POST | `…/demarrer` | `production.saisir` | matières validées → en cours |
| PUT | `…/resultat` | `production.saisir` | en cours / résultat saisi → résultat saisi |
| POST | `…/valider-resultat` | `production.valider` (chef de production) | résultat saisi → résultat validé |
| POST | `…/cloturer` | `production.cloturer` (resp. stock) | résultat validé → clôturé : entrée des produits finis |
| POST | `…/annuler` | `production.annuler` (DG) | tout état non terminal → annulé, `motif` obligatoire |

**Numérotation** `OF-AAAA-NNNNN`, par entreprise et par année, attribuée par un
incrément atomique en base : aucun doublon possible, même sous charge.

**Bobine** : un ordre porte sur une bobine ; elle doit avoir un **métrage
propre** connu (sinon aucune prévision fiable : 400 explicite), un métrage
engagé qui ne le dépasse pas et couvre au moins un tour. Une bobine ne sert
qu'à **un seul ordre non terminé** (garanti par un index partiel en base). À
la clôture elle devient `entamee_presente` (métrage restant jamais présumé)
ou `epuisee` si l'opérateur le déclare (`bobine_epuisee`), avec sortie du
stock. Séances cumulées au-delà du métrage initial : avertissement, pas un
blocage.

**Prévision** figée à la soumission avec les valeurs de la **version de la
fiche** en vigueur à la création (§6.1) : un ordre reste explicable même après
évolution de la fiche. Formules et cas de non-régression : `calculs.py`,
fonctions pures isolées (`VERSION_FORMULE` est stockée avec chaque résultat
validé, pour savoir quelle règle l'a produit).

**Résultat** : la saisie est acceptée telle quelle ; l'API renvoie aussitôt le
calcul et `coherent` / `ecart_comptage` (positif = pièce oubliée, négatif =
double comptage). Seule la **validation** exige un comptage cohérent. La saisie
se corrige tant que rien n'est validé (chaque correction est tracée).

**Stock** : à la soumission, réservation d'un tube par pièce prévue ; si le
disponible est insuffisant, **avertissement** `tubes_insuffisants` et pas de
blocage (stock négatif jamais bloquant, décision 0003). À la validation des
matières, sortie des tubes (`consommation`, lien `ordre_fabrication_id`) et
levée de la réservation. À la clôture : entrée des produits finis (jamais
saisie à la main), puis régularisation des tubes sur les pièces réellement
produites (`retour` ou `consommation` de l'écart). À l'annulation après sortie
des matières : `retour` des tubes.

**Produits finis** : l'entrée est en **cartons complets** si l'article se gère
au carton (les pièces restantes restent un reliquat visible sur l'ordre :
`pieces_restantes`), ou en pièces si l'article se gère à la pièce.

À faire confirmer avec le DG / le chef de production :
- l'**unité de gestion des produits finis** (carton ou pièce) et le sort des
  pièces restantes (reliquat à recompléter par un ordre suivant ?) ;
- la **séparation saisie/validation du résultat** : la matrice officielle
  n'a pas de profil « agent de saisie » distinct du chef de production, donc
  non imposée par défaut. Réglage `SEPARER_SAISIE_VALIDATION_RESULTAT` à
  activer dès qu'un agent existe (testé) ;
- la **nomenclature** des consommations : seules la bobine et le tube sont
  modélisés. Plastiques d'emballage, étiquettes, cartons vides, aluminium :
  non encore rattachés à un modèle ;
- la **formule du résultat réel** (§6.4), à reconfirmer en atelier.

Les quantités envoyées au Doctor Rewinder sont enregistrées dans le résultat
de l'ordre ; le suivi des encours (M07) est le prochain module.

Testé sous charge réelle : 8 créations simultanées sur 8 bobines et 6 sur une
même bobine → 9 ordres, 5 refus propres, numéros contigus sans doublon ; 6
validations simultanées des matières → 1 seule sortie de tubes.

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

**À faire confirmer par le DG (ajouté le 2026-11-20)** : la matrice
officielle ne dit pas qui crée les fiches du référentiel. Choix appliqué en
attendant, modifiable en une ligne dans `permissions.py` : articles et
conversions → responsable stock ; moules, modèles et références de
production → chef de production ; clients → directeur commercial ;
fournisseurs → responsable stock. Le DG consulte tout, ne saisit rien.

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
