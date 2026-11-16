# Règles de gestion de l'usine — d'après le cahier des charges fonctionnel

Source : document de cadrage fonctionnel transmis par la direction (Saal Multi
Services), reçu le 2026-11-16. Ce document est la **référence métier qui
prévaut** sur les hypothèses posées dans le prototype ; en cas de divergence,
c'est lui qui gagne.

## 1. Les trois niveaux de stock

| Niveau | Contenu | Alimente |
|---|---|---|
| 1 — Matières premières | Papier gris-gris, colle liquide, papier logo (liste à compléter) | Fabrication des mandrins longs |
| 2 — Semi-finis | Mandrins longs, paniers de pièces découpées, bobines BOPP, tubes PVC électriques, plastiques d'emballage, étiquettes de départ, colles papier, rouleaux d'aluminium | Fabrication des produits finis |
| 3 — Produits finis | Rubans BSG (simple jaune/gold/kaki, imprimé), colle papier, colle électrique, tubes papier, classés par gamme/dimension/conditionnement | Vente |

Règle de transformation clé : **seuls les mandrins longs** alimentent les
paniers de pièces découpées (par découpe) ; ils peuvent aussi aller
directement en fabrication de colle papier. Les autres semi-finis sont
consommés selon la nomenclature du produit fini — nomenclature qui reste à
obtenir (voir §9).

## 2. Identification des bobines — règle à respecter dans le schéma

Une bobine = **(numéro de lot, numéro de bobine)**. La bobine n°1 du lot 1 et
la bobine n°1 du lot 2 sont deux enregistrements distincts. Ne jamais utiliser
le seul numéro de bobine comme clé.

Champs par bobine : lot, numéro bobine (donné par le fournisseur), poids (kg),
métrage initial (m), couleur/finition (jaune transparent, clair transparent,
gold transparent, kaki simple ou imprimé), impression (couleur rouge/noir/bleu
+ module 45/48/70 mm si imprimée), documents liés (packing list, facture, bon
de réception).

Une bobine peut servir à **plusieurs séances/modèles** : conserver
l'historique de chaque utilisation (métrage engagé à chaque séance) ; tant
qu'elle n'est pas terminée son statut est `entamé, présente` — pas de
métrage/poids restant exigé (le client a tranché : pas fiable à mesurer). Le
métrage initial reste visible pour historique mais jamais présenté comme
disponible.

## 3. Paramètres des modèles BSG (fiche produit — valeurs communiquées)

| Largeur | Pièces par tour |
|---|---|
| 45 mm | 28 |
| 48 mm | 26 |
| 55 mm | 23 |
| 70 mm | 18 |

Chaque modèle a aussi : longueur de rouleau, nombre de pièces par carton
(valeur par modèle — à compléter, voir §9). Exemple donné : BSG 30, largeur
45 mm, longueur 25 m.

## 4. Calcul de prévision avant production (RG à coder telle quelle)

Entrée : métrage réellement enregistré sur la bobine sélectionnée (jamais une
constante fixe de 4000 m).

```
tours_complets    = floor(metrage_engage / longueur_modele)
pieces_theoriques = tours_complets * pieces_par_tour
cartons_complets  = floor(pieces_theoriques / pieces_par_carton)
pieces_restantes  = pieces_theoriques - (cartons_complets * pieces_par_carton)
```

Vérifié sur l'exemple du document (BSG 30, 25 m, 28 p/tour, 90 p/carton) :
3900 m → 156 tours → 4368 pièces → 48 cartons + 48 restantes. Ce triplet sert
de cas de test de non-régression pour la fonction.

## 5. Résultat réel de fabrication (saisi après coup, depuis un rapport papier)

Par ordre de fabrication + modèle + bobine, on saisit :

- nombre total de tours effectués (y compris défectueux)
- nombre de tours entièrement défectueux
- pièces défectueuses supplémentaires (sans double comptage avec les tours
  défectueux — le logiciel doit **détecter et signaler** ce double comptage)
- quantités envoyées au Doctor Rewinder
- quantités en perte définitive
- quantités bonnes obtenues

Le système calcule : pièces bonnes → cartons complets + pièces restantes, et
l'écart vs la prévision du §4.

### Doctor Rewinder (atelier de rectification)

Les pièces envoyées là-bas sont un **encours**, ni perte définitive ni
produit fini disponible — état intermédiaire à modéliser explicitement (pas
juste un statut sur le produit fini). Après traitement : quantités récupérées
/ non récupérées, par modèle et métrage, en gardant le lien OF + bobine + lot.

## 6. Entrée en stock de produits finis — deux voies distinctes

1. **Depuis la fabrication** : OF clôturé/validé → quantités réelles
   conditionnées transférées, rapprochées de l'OF et des consommations
   semi-finis.
2. **Entrée directe sans fabrication** (stock initial au démarrage, ou
   régularisation d'inventaire) : saisie référence + nb cartons + pièces/
   carton + motif → système calcule la quantité totale. **Doit être validée
   par un responsable habilité, distinct de la personne qui a saisi**
   (séparation des tâches obligatoire — RG non négociable, à vérifier côté
   serveur, pas seulement masquée à l'écran).

## 7. Rôles et accès (remplace la matrice du prototype)

| Rôle | Accès logiciel | Points clés |
|---|---|---|
| Directeur général | Vue consolidée tous modules, validation des opérations sensibles | seuils de validation à définir (§8) |
| Chef de production | Module production, OF, demandes de matières, saisie/validation résultats, encours Doctor Rewinder | ne modifie pas les mouvements de stock déjà validés |
| Directeur commercial | Clients, commandes, ventes, suivi commerciaux, dispo produits finis | **saisit lui-même** les ventes terrain remontées par fiche papier |
| Responsable stock et approvisionnement | Les 3 niveaux de stock, réceptions, lots/bobines, packing lists, demandes, inventaires, alertes | exécute les sorties seulement après validation |
| Comptable | Données financières autorisées, synthèses, rapprochements | écritures détaillées restent dans Sage (ou autre), pas dans ce logiciel |
| Responsable RH (nouveau rôle, absent du prototype) | Dossiers personnel, recrutement, contrats, absences, congés, éléments de paie | confidentialité renforcée sur les données salariales |
| Commerciaux | **Aucun compte** dans la version initiale | transmettent une fiche papier quotidienne au directeur commercial, qui saisit |

Écart important avec le prototype actuel : on avait donné aux commerciaux une
gestion dédiée façon « CRM » avec commission automatique. Le cahier des
charges dit l'inverse — pas de compte, remontée papier saisie par le
directeur commercial. À trancher avec le DG avant de coder le module ventes
(voir question posée dans le message qui accompagne ce document).

## 8. Circuit de validation (proposition du document, à faire valider par la DG)

| Opération | Initiateur | Validation | Exécution |
|---|---|---|---|
| Approvisionnement | Responsable stock | DG ou délégataire | Responsable stock + comptable selon étape |
| Réception matières | Responsable stock | Contrôle documentaire/quantitatif | Responsable stock |
| Sortie pour production | Chef de production | Selon procédure approuvée | Responsable stock |
| Résultat de fabrication | Production | Chef de production | Entrée stock produits finis |
| Ajustement de stock | Responsable stock | DG ou délégataire | Responsable stock après autorisation |
| Commande client | Client / commercial | Selon conditions commerciales | Service commercial |
| Dépense ou transfert | Service demandeur / comptable | DG selon délégation | Comptable ou personne habilitée |
| Mise à jour RH sensible | Responsable RH | DG selon nature | Responsable RH |

Les seuils financiers et délégataires exacts restent à préciser par la DG.

## 9. Ce qui manque encore pour pouvoir coder (à demander à la direction)

Bloquant pour le schéma stock/production (sprint 3) :
- Liste complète des matières premières/composants/colles/emballages et
  leurs unités de gestion.
- Recettes et nomenclatures de fabrication des colles et tubes papier
  (rendements inclus) — **toujours pas fournies**, c'est le point le plus
  fragile du planning.
- Nombre de pièces par carton pour chaque modèle (on n'a que les pièces/tour
  par largeur).
- Règles de conversion poids ↔ métrage ↔ rouleaux ↔ pièces ↔ cartons.
- Méthode de valorisation des stocks (coût de revient).

Bloquant pour les droits et la trésorerie (sprint 2 et au-delà) :
- Seuils de validation (achats, dépenses, transferts, ajustements) et la
  liste des délégataires/remplaçants.
- Mode d'échange avec l'outil comptable (Sage ou autre) : import/export/API/
  saisie manuelle de synthèse.

Non bloquant pour le noyau usine, mais à obtenir avant le module concerné :
- Fichier clients/fournisseurs/commerciaux/zones, tarifs, remises, limites
  d'encours.
- Traitement des rebuts/retours/produits non conformes/destructions.
- Règles RH (horaires, présences, paie) — module RH entièrement hors du
  périmètre « noyau usine » des 6 semaines.
- Modèles des fiches papier actuelles (production, stock, reporting
  commercial) — utiles pour calquer les écrans de saisie sur ce que les
  équipes connaissent déjà.

## 10. Scénarios de recette (à transformer en tests, sprint par sprint)

Le document impose que ces cas soient rejoués avant mise en service :
réception d'un conteneur + import packing list ; deux bobines portant le même
numéro dans deux lots différents (doit rester deux enregistrements
distincts) ; création d'un OF et calcul prévisionnel ; saisie d'un résultat
réel avec détection de double comptage de défauts ; traitement Doctor
Rewinder ; bobine utilisée sur plusieurs séances ; entrée de produits finis
(les deux voies) ; commande interentreprises ; vente terrain remontée par un
commercial ; rapprochement financier.
