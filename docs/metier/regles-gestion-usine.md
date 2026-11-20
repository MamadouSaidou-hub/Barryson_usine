# Règles de gestion de l'usine — cahier des charges officiel

Source : « GROUPE BARRYSON SARL — Cahier des charges — Logiciel de gestion
intégré de l'usine », v1, préparé par Saal Multi Services, reçu le
2026-11-18. Ce document **remplace** la version précédente (document de
cadrage du 2026-11-16) comme référence métier : il est plus détaillé et
formalisé, soumis à validation DG. En cas de divergence avec le code ou les
autres docs du dépôt, c'est lui qui prévaut, sauf mention contraire validée
avec la direction.

Les durées indicatives du plan de réalisation du cahier des charges (section
20 de la source) ne sont **pas reprises ici** : le planning réel du projet
est celui de `README.md` (6 semaines, noyau usine) et `docs/architecture.md`,
construit avec l'équipe à deux développeurs.

## 1. Objectifs et périmètre

Objectifs du projet (ce qui définit « fini ») :
- vue DG globale et temps réel sur tous les modules, opérations, stocks,
  résultats et validations ;
- **le module production est le cœur du système, prioritaire** — ordres de
  fabrication, prévisions, résultats réels, défauts, pertes, Doctor Rewinder ;
- traçabilité complète de la bobine reçue au carton vendu ;
- circuits de validation + séparation stricte saisie/validation ;
- suppression des écarts non expliqués entre stock théorique et stock réel.

Indicateurs de réussite explicites : tous les mouvements de stock tracés et
justifiés ; écart prévision/réel visible pour chaque OF ; cockpit DG à jour
sans ressaisie ; aucune opération sensible sans auteur, date, quantité, motif.

**Inclus** : administration/sécurité, référentiels, achats/fournisseurs,
stocks 3 niveaux, production, Doctor Rewinder, ventes/commandes, suivi
commercial, synthèses financières, RH, tableaux de bord, journal d'audit.

**Exclus de la v1** : comptabilité générale détaillée (reste dans Sage ou
équivalent, synthèses seulement) ; comptes utilisateurs pour les commerciaux
(ils remontent via le directeur commercial) ; paie complète (seuls les
éléments variables sont suivis).

## 2. Principes directeurs (non négociables)

a. Trois niveaux de stock distincts et liés, un article = un seul niveau.
b. Stock = somme des mouvements validés, **jamais de modification directe
   d'un solde** — toute correction passe par un mouvement ou ajustement
   autorisé.
c. Prévisions théoriques calculées par le logiciel, résultats réels saisis
   par l'utilisateur, écart mesuré automatiquement.
d. **Séparation saisie/validation : l'auteur d'une opération ne peut pas la
   valider lui-même.** Règle technique à appliquer, pas juste UI.
e. Chaque opération sensible conserve auteur, date/heure, quantités, motif,
   statut, valideur, pièces justificatives.
f. Accès transversal du DG à tous les modules et tableaux de bord.
g. Paramétrage sans développement des modèles, seuils, unités, délégations,
   par un administrateur habilité.
h. Interface entièrement en français, vocabulaire usine.

## 3. Organisation et profils d'accès (matrice officielle)

| Profil | Consultation | Saisie | Validation |
|---|---|---|---|
| Directeur général | Tous modules, tous tableaux de bord, journal d'audit, jusqu'à l'opération d'origine | Aucune obligatoire | Achats, dépenses, transferts de fonds, ajustements de stock, sorties exceptionnelles, entrées directes de produits finis, engagements commerciaux, selon seuils |
| Chef de production | Production, Doctor Rewinder, stocks | Fiches modèles, OF, demandes de matières | Résultats de fabrication, clôture des OF, traitement Doctor Rewinder |
| Directeur commercial | Clients, commandes, ventes, dispo PF, créances, tableaux de bord commerciaux | Clients, commandes, ventes terrain, livraisons, objectifs | Conditions commerciales, dans la limite de ses délégations |
| Responsable stock et approvisionnement | Stocks 3 niveaux, OF ouverts, alertes | Réceptions, packing lists, mouvements, inventaires, demandes d'achat, entrées PF | Contrôle des réceptions, exécution des sorties déjà validées |
| Comptable | Ventes, créances, achats, synthèses financières | Synthèses caisse/banque, rapprochements, échanges Sage | Aucune — exécute les paiements déjà autorisés |
| Responsable RH | Dossiers personnel, effectifs, présences | Dossiers, présences, congés, éléments variables de paie | Aucune — mises à jour sensibles validées par le DG |
| Administrateur (nouveau, technique) | Paramètres et journal technique, **sans accès aux données salariales** | Utilisateurs, rôles, paramètres, sauvegardes | Aucune |
| Commerciaux | — | — | **Pas de compte en v1**, remontée papier vers le directeur commercial |

Ce tableau remplace celui du prototype et celui du document de cadrage
précédent. Point confirmé définitivement (ne plus redemander) : pas de compte
commercial en v1, c'est dans le plan d'évolution (section 10 ci-dessous).

## 4. Architecture fonctionnelle — modules et priorité

| Code | Module | Priorité |
|---|---|---|
| M01 | Administration, sécurité, journal d'audit | Haute |
| M02 | Référentiels : articles, unités, moules, modèles, clients, fournisseurs | Haute |
| M03 | Fournisseurs et achats | Haute |
| M04 | Stock matières premières | Haute |
| M05 | Stock produits semi-finis, bobines BOPP, transformations | Haute |
| M06 | Production : ordres, prévisions, résultats | **Critique** |
| M07 | Doctor Rewinder et rectification | **Critique** |
| M08 | Stock produits finis | Haute |
| M09 | Ventes, commandes et livraisons | Haute |
| M10 | Suivi commercial terrain | Moyenne |
| M11 | Finances et échange comptable | Moyenne |
| M12 | Ressources humaines | Moyenne |
| M13 | Tableaux de bord et cockpit DG | **Critique** |

Cet ordre de priorité confirme le découpage déjà posé dans
`docs/architecture.md` (socle → identité → référentiel → stock → production).
M06/M07/M13 sont critiques : à traiter en premier une fois l'identité (M01)
posée.

## 5. Module Production (M06) — détail à coder

### 5.1 Fiche de modèle de ruban

Minimum : famille, nom du modèle, largeur, longueur de rouleau, pièces par
tour, pièces par carton, finition/couleur, moule/outillage, nomenclature des
semi-finis consommés. **Paramétrable et modifiable par un utilisateur
habilité, avec historique des versions** — donc une table versionnée, pas un
simple update en place.

| Largeur | Pièces par tour |
|---|---|
| 45 mm | 28 |
| 48 mm | 26 |
| 55 mm | 23 |
| 70 mm | 18 |

Rubans imprimés : couleur d'impression (rouge/noir/bleu) + module (45/48/70).
Finitions jaune transparent, transparent clair, or transparent, kaki simple :
même processus, la couleur dépend de la bobine sélectionnée.

**Confirmation terrain (réunion usine, 2026-11-19, photos à l'appui)** — ce
point était resté flou depuis le début et vient d'être clarifié avec les
responsables : **il n'y a pas de fabrication/enduction sur site pour la
famille ruban BOPP**. Les bobines jumbo sont achetées déjà enduites en Chine
(étiquette fournisseur relevée : « BOPP TAPE JUMBO ROLL, SIZE 50MIC×1280MM×
4002M, Transparent Golden Yellow, G.W. 255, N.W. 251.4, ROLL NO. 65 » — même
structure que les exemples de colisage §7.2). Le site ne fait que :
1. **Refendage** (slitting) du jumbo 1280 mm sur une rembobineuse dédiée —
   c'est très exactement ce que modélise déjà la formule §5.3/§5.4 : le
   nombre de **pièces par tour** correspond physiquement au nombre de bandes
   découpées simultanément dans la largeur du jumbo (ex. 1280 mm / 45 mm ≈ 28
   bandes, ce qui recoupe la valeur déjà connue pour 45 mm). Rien à changer
   dans le modèle de données ou les formules — c'est une confirmation, pas
   une correction.
2. **Conditionnement** — bobines finies emballées, étiquetées et cartonnées
   (cartons « Barryson Adhésif »).

Donc le **niveau 1 « matière première »** du modèle de stock (§7.1) ne
concerne **que** la famille colle papier/tubes (papier gris-gris, colle
liquide, papier logo/blanc → mandrins longs) — jamais le ruban BOPP, dont le
jumbo entre directement en stock **niveau 2** par achat/réception conteneur,
exactement comme déjà décrit en §7.2 et §9 (achats). Les tubes/mandrins vus
en photo (déjà découpés à longueur courte, logo imprimé) confirment aussi
qu'il existe une étape de découpe des mandrins longs en segments courts sur
site, cohérente avec §5.6/§7.2 (paniers de pièces découpées par dimension).

### 5.2 Cycle de vie d'un ordre de fabrication (machine à états à implémenter telle quelle)

| Statut | Déclenché par | Intervenant |
|---|---|---|
| Brouillon | Sélection famille/modèle/lot/bobine/moule/métrage engagé | Chef de production |
| Soumis | Prévision calculée + demande de matières envoyée | Chef de production |
| Matières validées | Sortie de stock validée, matière remise à la production | Responsable stock |
| En cours | Fabrication lancée | Production |
| Résultat saisi | Saisie du rapport papier opérateur | Agent habilité |
| Résultat validé | Contrôle de cohérence + validation | Chef de production |
| Clôturé | Entrée en stock de produits finis générée | Responsable stock |
| Annulé | Motif obligatoire | DG ou délégataire |

### 5.3 Prévision automatique (RG, déjà vérifiée sur l'exemple chiffré)

Calcul sur le **métrage propre réel de la bobine sélectionnée**, jamais une
valeur standard :

```
tours_complets    = floor(metrage_engage / longueur_rouleau)
pieces_theoriques = tours_complets * pieces_par_tour
cartons_complets  = floor(pieces_theoriques / pieces_par_carton)
pieces_restantes  = pieces_theoriques - (cartons_complets * pieces_par_carton)
```

Cas de test (BSG 30, rouleau 25 m, 28 p/tour, 90 p/carton) :
3900 m → 156 tours → 4368 pièces → 48 cartons + 48 restantes
4000 m → 160 tours → 4480 pièces → 49 cartons + 70 restantes
4100 m → 164 tours → 4592 pièces → 51 cartons + 2 restantes

### 5.4 Résultat réel — règle de calcul et contrôle de cohérence

Saisi par OF + modèle + bobine : tours totaux effectués (y compris
défectueux), tours entièrement défectueux, pièces défectueuses
supplémentaires (sans double comptage), pièces envoyées au Doctor Rewinder,
pertes définitives. Le logiciel calcule :

```
pieces_brutes       = tours_totaux * pieces_par_tour
pieces_non_conformes = (tours_defectueux * pieces_par_tour) + pieces_defectueuses_supp
# contrôle de cohérence obligatoire :
#   pieces_non_conformes DOIT ETRE EGAL A (doctor_rewinder + pertes_definitives)
#   sinon -> signaler double comptage ou omission, bloquer la validation
pieces_conformes    = pieces_brutes - pieces_non_conformes
cartons_complets    = floor(pieces_conformes / pieces_par_carton)
pieces_restantes    = pieces_conformes - (cartons_complets * pieces_par_carton)
ecart               = pieces_conformes - pieces_theoriques        # quantité et %
rendement           = pieces_conformes / pieces_theoriques
```

Note du cahier des charges : « cette règle de calcul sera confirmée en
atelier avec le chef de production » — donc à vérifier avec lui avant de la
figer en tests de non-régression, même si la formule ci-dessus est déjà
cohérente avec le reste du document.

### 5.5 Bobines utilisées en plusieurs séances

Identifiant interne = **(lot, numéro fournisseur)** — jamais le numéro de
bobine seul, deux lots différents peuvent avoir le même numéro fournisseur.
Historique de chaque utilisation + métrage engagé à chaque séance conservés.
Bobine non épuisée → statut `entamée, présente`, sans obligation de saisir
poids/métrage/emplacement restant (décision client : pas mesurable de façon
fiable). Métrage initial visible pour historique seulement, jamais présenté
comme disponible. **Prévu en évolution** : option paramétrable pour activer
la mesure du métrage restant plus tard — ne pas fermer le schéma, prévoir le
champ mais pas l'UI v1.

### 5.6 Tubes papier (mandrins) et « colle papier »

**Correction terrain (réunion usine, 2026-11-19, confirmée par la
direction)** — cette section était fausse dans les versions précédentes et
vient d'être corrigée. Il n'y a **aucune fabrication de mandrins/tubes sur
site** : les tubes en papier sont **achetés déjà fabriqués**, exactement
comme les bobines jumbo BOPP (même logique d'approvisionnement, probablement
même origine). Un tube papier n'est rien d'autre que le **noyau rigide sur
lequel le ruban découpé est enroulé** — ce n'est pas un produit fabriqué à
partir de papier gris-gris + colle liquide comme supposé initialement.

Conséquence directe : **il n'existe pas de « recette colle papier/tubes
papier » à obtenir du DG** — ce point, identifié comme le plus fragile du
projet, est caduc. Ce qui reste réellement à obtenir est beaucoup plus
simple : une **nomenclature** (quelle référence de tube correspond à quel
modèle/moule de ruban), pas une formule de fabrication. Le champ
correspondant dans `fiche-collecte-infos-manquantes-Barryson.docx` reste
pertinent mais sa portée est réduite à cette association référentielle.

Processus physique réel, confirmé par les responsables et les photos
transmises : sélection du **moule**, du **modèle** et de la **couleur** →
**découpage** (refendage du jumbo BOPP acheté, cf. §5.1) → **assemblage**
(le ruban découpé est enroulé sur le tube papier acheté — opération réalisée
en une seule passe sur la rembobineuse/refendeuse, pas une étape séparée
dans le cycle de vie de l'OF) → **conditionnement** (cartons). Le tube
papier est donc un **composant semi-fini acheté, consommé à l'assemblage**,
au même titre qu'une bobine BOPP consommée au découpage — à modéliser comme
une ligne de nomenclature du modèle (§5.1), pas comme une transformation
matière première.

### 5.7 Fonctions complémentaires attendues

Planification par commandes/prévisions/disponibilités avec charge par moule ;
alertes (écart de rendement au-delà d'un seuil, taux de défauts anormal,
bobine entamée inactive depuis N jours) ; impression OF / bon de sortie /
fiche de résultat calquée sur le rapport papier ; analyse des écarts et
rendement par modèle/largeur/longueur/finition/bobine/lot/période.

## 6. Module Doctor Rewinder (M07)

Encours de rectification — **ni perte définitive ni produit fini
disponible**, un état intermédiaire à modéliser explicitement (table dédiée,
pas un statut sur le produit fini). Enregistre : envois (OF, bobine, lot,
modèle, métrage, quantité) et retours. Après traitement : quantités
récupérées (par modèle/métrage, lien OF+bobine+lot conservé, entrent en
stock PF **après validation**) vs non récupérables (pertes définitives).
Indicateurs : encours en cours, taux de récupération, délai de traitement,
ancienneté des encours.

## 7. Stocks à trois niveaux (détail)

### 7.1 Niveau 1 — matières premières

**Mis à jour suite à la réunion usine du 2026-11-19** : contrairement à ce
qui était supposé dans les premières versions de ce document, **aucune
transformation de matière première n'a lieu sur le site de Barryson**. Tout
ce qui entre en production (bobines jumbo BOPP, tubes papier, plastiques
d'emballage, étiquettes, cartons vides, rouleaux d'aluminium) est acheté
déjà sous forme de semi-fini et entre directement en **stock niveau 2**
(réception conteneur/fournisseur). Le site fait uniquement : découpage,
assemblage, conditionnement.

**Décision confirmée (2026-11-19)** : le niveau 1 « matière première » n'a
**aucun cas d'usage actuel** pour Barryson, et ce n'est pas une question en
attente de réponse du DG — c'est tranché. Mais le schéma de stock à 3
niveaux **doit rester générique et prévu dans le modèle de données**, au cas
où l'usine déciderait un jour de reprendre une fabrication à partir de
matière première (ex. remonter la chaîne, produire elle-même le ruban ou les
tubes plutôt que les acheter déjà semi-finis). Concrètement : le niveau 1
existe dans le schéma (table articles avec `niveau_stock = matiere_premiere`
disponible, mouvements de stock génériques déjà conçus pour n'importe quel
niveau), mais **sans écran ni module dédié tant qu'aucun article réel n'y est
rattaché** — activable plus tard sans migration de schéma, juste en créant
des articles à ce niveau et en ouvrant l'écran correspondant.

### 7.2 Niveau 2 — semi-finis achetés et bobines BOPP

Contenu : **tubes papier (mandrins, achetés déjà fabriqués — §5.6)**,
paniers de pièces découpées par dimension, bobines BOPP, tubes PVC
électriques, plastiques d'emballage rubans, plastiques PVC, étiquettes de
départ, rouleaux d'aluminium, cartons vides. Tous ces articles sont achetés
sous forme de semi-finis prêts à l'emploi — aucun n'est fabriqué à partir de
matière première sur site (§7.1).

Bobine BOPP = un enregistrement par (lot du conteneur, numéro fournisseur de
la bobine). Champs : lot, numéro fournisseur, poids (kg), métrage propre (m),
couleur/finition, impression+module si imprimée, documents (packing list,
facture, bon de réception).

**Import de packing list Excel** : aperçu avant intégration, détection des
doublons, contrôle de cohérence (poids/métrage/finition), rapport d'erreurs,
**validation par le responsable stock avant création des bobines**. Chaque
transformation (consommation → production) enregistrée avec lien vers l'OF
et les articles d'origine.

Deux exemples réels de packing list fournisseur ont été transmis
(`docs/metier/exemples/colisage-exemple-poids-net.csv` et
`colisage-exemple-metrage-poids-brut.csv`, un même conteneur). Ils confirment
le principe mais révèlent que **le format n'est pas standardisé d'une feuille
à l'autre** :
- la première feuille numérote les bobines en séquence (1 à 102) avec un nom
  de finition déjà lisible (Gold transparent, Jaune transparent, Clair
  transparent, Kaki simple) et un poids net ;
- la seconde donne le métrage et un poids brut par bobine, sans numéro de
  bobine, regroupées par **code couleur fournisseur** (Golden01, Golden03,
  Yellowish, Clear White, Brown) distinct du nom de finition lisible, et en
  nombre différent de lignes (~89 vs 102) — donc pas de clé commune évidente
  entre les deux feuilles pour une même bobine physique.

Conséquence technique : l'import ne doit pas supposer un schéma de colonnes
fixe ni une correspondance 1-pour-1 entre feuilles d'un même classeur.
L'écran d'aperçu doit permettre de **mapper manuellement les colonnes** reçues
vers les champs internes (lot, numéro bobine, poids, métrage, couleur/
finition), et si plusieurs feuilles sont fournies pour un même conteneur,
le rapprochement entre elles reste **manuel/assisté**, pas automatique, tant
qu'aucune clé fiable commune n'est confirmée par le fournisseur.

### 7.3 Niveau 3 — produits finis

Suivi par référence, modèle, dimension, finition/couleur, module, pièces/
carton, cartons disponibles. Deux voies d'entrée :
- **depuis la fabrication** : OF clôturé → quantités réelles conditionnées
  transférées, rapprochées de l'OF et des consommations semi-finis ;
- **entrée directe sans OF** (stock de démarrage ou écart d'inventaire) :
  référence + nb cartons + pièces/carton + motif. **Validée par un
  responsable distinct du saisissant**, obligatoire. Conserve saisissant,
  valideur, date/heure, produit, quantités, motif, pièce justificative si
  possible. Ces entrées sont **distinguées dans tous les états** (donc un
  flag/type de mouvement dédié, pas juste un motif texte).

### 7.4 Mouvements, inventaires, contrôles

Types de mouvement : réception, entrée, demande de sortie, sortie,
consommation, transformation, transfert, retour, ajustement, **rebut ou
destruction** (nouveau), inventaire.

- Unités par article (kg, m, rouleau, pièce, panier, carton) + règles de
  conversion paramétrables.
- **Réservations** pour OF et commandes : `stock_disponible = stock_physique - reservations`.
  C'est un concept absent du prototype et du document précédent — à intégrer
  au modèle de données stock dès le sprint stock.
- Seuils min/max/alerte, prévision de rupture, proposition de demande
  d'achat.
- Inventaires tournants et généraux, comptage, écarts, ajustements soumis à
  validation DG ou délégataire.
- Méthode de valorisation et coût de revient : **toujours à définir**.

## 8. Références de conditionnement (connu vs à confirmer)

Table confirmée par la direction :

| Famille | Largeur | Longueur | Pièces/carton |
|---|---|---|---|
| BOPP | 45 mm | 25 m | 90 |
| BOPP | 45 mm | 50 m | 72 |
| BOPP | 45 mm | 100 m | 72 |
| BOPP | 48 mm | 200 m | 36 |
| BOPP | 55 mm | 150 m | 36 |
| PVC électrique | 17,15 mm *(à confirmer)* | 6 yards *(cité)* | 500 *(annoncé, à confirmer)* |

**Encore manquant** (mentionné mais pièces/carton non établi) : BOPP 45 mm
sur 150 m et 1000 m ; BOPP 55 mm sur 200 m et 1000 m ; BOPP 70 mm sur 120 m et
1000 m ; rubans de masquage 24 mm sur 18 m et 50 mm sur 20 m. À ajouter à la
fiche de collecte si elle n'est pas déjà couverte.

## 9. Achats et approvisionnement (M03)

Fiche fournisseur : coordonnées, conditions de paiement, délais, historique
achats/litiges, évaluation. Circuit : besoin → demande d'achat → validation
DG/délégataire selon seuil → commande → réception contrôlée → entrée stock →
rapprochement facture/paiement. Suivi des commandes en cours, retards,
réceptions partielles, écarts qté/qualité. Suivi des conteneurs : date
d'arrivée, documents, bobines reçues, statut de contrôle.

## 10. Ventes et suivi commercial (M09/M10)

**Circuit interentreprises** : commande directe à l'usine, enregistrée par le
directeur commercial, qui vérifie dispo, confirme conditions, suit
préparation/livraison/règlement. Une commande non satisfaite peut générer un
besoin de production visible du chef de production (lien M09→M06 à prévoir).

**Circuit terrain** : commerciaux vendent, remontent par fiche papier au
directeur commercial (ou agent habilité) qui saisit : date, commercial,
client/point de vente, localité, références vendues, quantités, prix, mode
de règlement, sommes encaissées, crédits, observations.

Fonctions : fichier clients (segment, zone, conditions, plafond d'encours),
tarifs/remises, devis, commandes, livraisons, retours/réclamations,
créances/relances, objectifs par commercial/zone/client/produit, rapports
périodiques. **Le stock PF diminue à la livraison validée** (pas à la
commande).

Évolution prévue (hors v1, à ne pas construire maintenant) : application
mobile ou saisie hors ligne pour les commerciaux, accès direct à la
plateforme.

## 11. Finances et échange comptable (M11)

Comptabilité détaillée hors périmètre (Sage ou équivalent), ce module ne
gère que les synthèses : caisse/banque, transferts entre comptes/caisses
(validation DG obligatoire), dépenses, encaissements clients, créances,
dettes fournisseurs, rapprochement ventes/encaissements. **Mode d'échange
encore ouvert** (import/export/interface/saisie manuelle) — dans tous les
cas, import/export Excel normalisé prévu comme filet de sécurité.

## 12. Ressources humaines (M12)

Effectif confirmé : **~14 salariés, horaire 8h–17h du lundi au samedi**.
Dossier employé (identité, poste, affectation, contrat, pièces),
recrutements, présences, absences, congés, effectifs par service, éléments
variables de paie. Données salariales confidentielles : accès RH + DG
uniquement. DG reçoit une synthèse (effectifs, absentéisme, masse salariale).
Hors périmètre 6-semaines noyau usine, mais le dimensionnement (14 personnes)
est désormais connu pour plus tard.

## 13. Cockpit Direction générale (M13)

Écran d'accueil DG : indicateurs clés, alertes du jour, opérations en attente
de sa validation, **accès au détail par clic jusqu'à l'opération d'origine**
(lot, bobine, ordre, mouvement, pièce justificative) — donc un drill-down
complet, pas juste des agrégats.

| Domaine | Indicateurs |
|---|---|
| Production (prioritaire) | OF ouverts/en cours/clôturés, prod prévue vs réelle, rendement par modèle, défauts/pertes, encours Doctor Rewinder + taux récup, consommation par lot/bobine |
| Stocks | 3 niveaux, ruptures prévues, bobines entamées, entrées directes, écarts d'inventaire |
| Achats | commandes en cours, retards, dépenses par fournisseur, conteneurs attendus |
| Ventes | CA par segment/produit/zone/commercial, commandes en attente, livraisons, objectifs atteints |
| Finances | caisses, banques, encaissements, décaissements, transferts, créances âgées, dettes |
| RH | effectif, absences, congés, synthèse paie |
| Contrôle | opérations en attente de validation, ajustements, anomalies, actions correctives |

Chaque responsable a son propre tableau de bord. Fonctions communes : filtres
période, comparaison période précédente, graphiques, exports Excel/PDF,
rapports automatiques, alertes paramétrables.

## 14. Circuit de validation (version officielle)

| Opération | Initiateur | Validation | Exécution |
|---|---|---|---|
| Approvisionnement | Responsable stock | DG ou délégataire, selon seuil | Responsable stock, comptable |
| Réception de matières | Responsable stock | Contrôle documentaire + quantitatif | Responsable stock |
| Sortie pour production | Chef de production | Selon procédure approuvée | Responsable stock |
| Résultat de fabrication | Production | Chef de production | Stock, pour entrée PF |
| Entrée directe de PF | Responsable stock | Responsable habilité distinct du saisissant | Responsable stock |
| Ajustement de stock | Responsable stock | DG ou délégataire | Responsable stock |
| Commande client | Client ou commercial | Conditions commerciales | Service commercial |
| Dépense ou transfert | Demandeur ou comptable | DG selon délégation | Comptable |
| Mise à jour RH sensible | Responsable RH | DG selon nature | Responsable RH |

Seuils financiers, délégations, remplaçants en cas d'absence du DG : toujours
paramétrables et à préciser (déjà demandé dans la fiche de collecte).

## 15. Documents générés par le logiciel

| Document | Module | Contrôle principal |
|---|---|---|
| Bon de commande | Achats | Validation selon seuil |
| Bon de réception | Stock matières/semi-finis | Concordance commande/documents/quantités |
| Bon d'enlèvement de matière | Stock + production | Lien avec un OF |
| Demande et bon de sortie | Stock | Quantité, demandeur, valideur, date |
| Bon de retour | Stock | Quantité, état matière |
| Fiche de production | Production | Cohérence avec la prévision |
| Bon d'entrée de produits finis | Stock PF | Concordance avec la production validée |
| Procès-verbal d'ajustement | Stock | Motif, justificatif, autorisation |
| Bon de livraison | Ventes | Concordance avec la commande |
| Sortie de caisse et reçu | Finances | Autorisation et justificatif |
| Fiche de présence | RH | Contrôle par le responsable RH |

Numérotation automatique et rattachement à l'opération d'origine sur
l'ensemble de ces documents.

## 16. Exigences non fonctionnelles (à ne pas perdre de vue)

- **Sécurité** : mots de passe robustes, verrouillage après échecs répétés,
  droits par profil et par module, chiffrement des échanges, protection
  renforcée données financières/salariales.
- **Disponibilité** — décision d'architecture encore présentée comme ouverte
  dans le cahier des charges (« serveur local à l'usine avec accès distant
  sécurisé pour la Direction » vs « solution hébergée avec mode dégradé »).
  **Déjà tranché de notre côté avec le DG** : VPS auto-géré + Docker, hybride
  cloud/hors-ligne (voir `docs/decisions/0001-socle-technique.md` et
  `0003-strategie-hors-ligne.md`). Pas une nouvelle question à poser — à
  juste reconfirmer en séance de cadrage que ce choix reste valable compte
  tenu des coupures électricité/connexion mentionnées ici.
- **Sauvegardes** : automatiques quotidiennes, copie hors site, test de
  restauration périodique, plan de reprise.
- **Performance** : écrans courants < 3 s pour au moins 10 utilisateurs
  simultanés, marge d'évolution.
- **Ergonomie** : parcours courts, vocabulaire usine, aide contextuelle,
  utilisable sur ordinateur et tablette, cockpit consultable sur téléphone.
- **Évolutivité** : architecture modulaire pour ajouter des modules (qualité,
  maintenance, accès commerciaux) sans refonte.
- **Maintenabilité** : documentation technique, code versionné,
  environnements test/production séparés — déjà en place.

## 17. Modèle de données — entités principales (cahier des charges)

Utilisateur, rôle, article, unité et conversion, lot, bobine, fournisseur,
commande d'achat, réception, mouvement de stock, ordre de fabrication,
séance de production, résultat, dossier Doctor Rewinder, modèle de ruban,
moule, client, commande client, livraison, vente de terrain, encaissement,
compte de caisse/banque, employé, pièce justificative, journal d'audit.

Reprise des données prévue : articles, fournisseurs, clients, stock initial
(inventaire de départ validé par le DG), bobines en cours, OF ouverts, soldes
de créances.

## 18. Ce qui reste à obtenir du DG

Le cahier des charges officiel renvoie explicitement à la fiche déjà
transmise (`fiche-collecte-infos-manquantes-Barryson.docx`). À compléter
dans cette fiche ou à ajouter si absent :
- ~~recettes colle papier et tubes papier~~ — **caduc** : confirmé en
  réunion usine (2026-11-19) qu'il n'y a pas de fabrication matière première
  sur site (§5.6/§7.1). Remplacé par un besoin bien plus simple : la
  **nomenclature référence tube papier ↔ modèle/moule de ruban** (quel tube
  va avec quel modèle), à ajouter si absent de la fiche existante ;
- pièces par carton pour les références BOPP/masquage encore incomplètes
  (§8 ci-dessus) et confirmation des dimensions PVC électrique ;
- méthode de valorisation des stocks / coût de revient ;
- seuils financiers de validation et délégataires/remplaçants ;
- mode d'échange avec Sage (import/export/interface/saisie) — non
  prioritaire (cf. échanges précédents) ;
- inventaire physique d'ouverture, validé par le DG.

## 19. Recette — scénarios à transformer en tests

Réception d'un conteneur + import packing list ; deux bobines de même numéro
fournisseur dans des lots différents (doivent rester deux enregistrements) ;
cycle complet d'un OF (brouillon → clôturé) avec calcul prévisionnel et
saisie du résultat réel (y compris déclenchement du contrôle de cohérence
§5.4) ; traitement Doctor Rewinder ; bobine utilisée en plusieurs séances ;
entrée PF par les deux voies ; commande interentreprises ; vente terrain
remontée par un commercial ; rapprochement financier ; **tests de droits pour
chaque profil, y compris la vue complète du DG**.
