# 0003 — Stratégie hors-ligne

**Date** : 2026-11-14 · **Statut** : accepté

## Contexte

À Conakry, la connexion internet et l'électricité sont irrégulières. L'atelier
ne peut pas s'arrêter parce que le réseau tombe. Mais un ERP manipule des
quantités et de l'argent : accepter n'importe quelle écriture différée
produirait des incohérences impossibles à arbitrer.

## Décision

**Lecture hors-ligne : tout.** Les données consultées sont mises en cache
localement (articles, stock au dernier rafraîchissement, ordres en cours,
commandes, instructions de la direction).

**Écriture hors-ligne : uniquement les opérations qui ajoutent une ligne** et
ne dépendent pas d'un état global à l'instant de l'action — avancement d'un
ordre de fabrication, consommation matière, prise de commande en tournée,
rédaction d'une instruction. Chaque écriture porte une **clé d'idempotence**
générée sur l'appareil, donc un rejeu après reconnexion ne crée jamais de
doublon.

**Écriture exigeant la connexion** : validation d'un bon de livraison (elle
vérifie le stock réel), encaissement, clôture d'inventaire, modification d'un
prix ou d'un rôle. L'interface annonce clairement l'indisponibilité plutôt que
de faire semblant.

**Stock négatif** : techniquement autorisé et signalé comme écart à
régulariser, jamais bloquant. Un opérateur bloqué contourne le logiciel ; un
écart visible se corrige.

*Précision (2026-11-21)* : la **sortie de tubes pour un ordre de fabrication** est
bloquée quand le stock ne couvre pas le besoin (un stock négatif y cacherait une
réception non saisie). Pour ne pas bloquer l'atelier, le DG (ou son délégataire,
droit `stock.valider_sortie_exceptionnelle`) peut accorder une **dérogation
motivée**, inscrite dans l'historique de l'ordre ; le stock négatif reste alors
signalé comme écart à régulariser.

## Conséquences

- Le stock **doit** être un registre de mouvements en ajout seul, jamais un
  compteur mis à jour en place : c'est ce qui rend deux saisies concurrentes
  additionnables au lieu de destructrices.
- Mise en service : on démarre **en ligne**, le hors-ligne est activé juste
  après, pour ne pas retarder l'usage réel de plusieurs semaines.
