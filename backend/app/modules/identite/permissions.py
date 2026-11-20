"""Matrice des droits — table de verite unique du controle d'acces.

Source : cahier des charges officiel v1, §3 (Consultation / Saisie /
Validation), reproduit dans docs/cahier-des-charges-technique.md §3.2.
Aucun controle d'acces ne doit se faire ailleurs qu'a travers
`a_la_permission` : c'est ce qui permet de tester la matrice entiere.

Les commerciaux n'ont pas de compte en v1 (decision definitive) : ils sont
volontairement absents. Les permissions des modules pas encore construits
sont declarees des maintenant pour que la matrice soit relue une seule fois
avec le client, pas module par module.
"""

from typing import Literal, get_args

Role = Literal[
    "dg",
    "chef_production",
    "directeur_commercial",
    "responsable_stock",
    "comptable",
    "responsable_rh",
    "administrateur",
]
ROLES: tuple[str, ...] = get_args(Role)

LIBELLES_ROLES: dict[str, str] = {
    "dg": "Directeur général",
    "chef_production": "Chef de production",
    "directeur_commercial": "Directeur commercial",
    "responsable_stock": "Responsable stock et approvisionnement",
    "comptable": "Comptable",
    "responsable_rh": "Responsable des ressources humaines",
    "administrateur": "Administrateur",
}

CATALOGUE: dict[str, str] = {
    "tableaux_de_bord.consulter": "Cockpit et tableaux de bord",
    "audit.consulter": "Lire le journal d'audit",
    "audit.verifier": "Vérifier l'intégrité du journal d'audit",
    "journal_technique.consulter": "Lire le journal technique (connexions, erreurs)",
    "utilisateurs.consulter": "Voir les comptes utilisateurs",
    "utilisateurs.gerer": "Créer, modifier, désactiver un compte, réinitialiser un mot de passe",
    "delegations.gerer": "Désigner et révoquer des délégataires pour les validations du DG",
    "parametres.consulter": "Voir les paramètres",
    "parametres.gerer": "Modifier les paramètres",
    "referentiels.consulter": "Articles, unités, moules",
    # Non precise par la matrice officielle : attribue au responsable stock, a confirmer avec le client.
    "referentiels.saisir": "Créer et modifier les articles et les conversions d'unités",
    "modeles.consulter": "Fiches modèles de ruban, moules, références de conditionnement",
    "modeles.saisir": "Créer et modifier les fiches modèles de ruban, moules et références",
    "stock.consulter": "Stocks des trois niveaux",
    "stock.saisir": "Réceptions, packing lists, mouvements, inventaires, entrées de produits finis",
    "stock.valider_reception": "Contrôler une réception, exécuter une sortie déjà validée",
    "stock.valider_ajustement": "Valider un ajustement de stock",
    "stock.valider_sortie_exceptionnelle": "Valider une sortie exceptionnelle",
    "stock.valider_entree_directe": "Valider une entrée directe de produits finis sans ordre de fabrication",
    "achats.consulter": "Commandes et demandes d'achat",
    "achats.saisir": "Demandes d'achat",
    "achats.valider": "Valider un achat",
    "production.consulter": "Ordres de fabrication et résultats",
    "production.saisir": "Ordres de fabrication, demandes de matières",
    "production.valider": "Valider le résultat de fabrication d'un ordre",
    "production.cloturer": "Clôturer un ordre de fabrication (entrée des produits finis en stock)",
    "production.annuler": "Annuler un ordre de fabrication (motif obligatoire)",
    "stock.executer_sortie": "Exécuter la sortie des matières d'un ordre de fabrication",
    "doctor_rewinder.consulter": "Encours Doctor Rewinder",
    "doctor_rewinder.valider": "Valider le traitement Doctor Rewinder",
    "clients.consulter": "Fiches clients et créances",
    "clients.saisir": "Créer et modifier les clients",
    "ventes.consulter": "Commandes, ventes, livraisons",
    "ventes.saisir": "Commandes, ventes terrain, livraisons, objectifs",
    "ventes.valider_conditions": "Valider des conditions commerciales dans la limite des délégations",
    "ventes.valider_engagement": "Valider un engagement commercial au-delà des délégations",
    "finances.consulter": "Synthèses financières, caisse, banque",
    "finances.saisir": "Synthèses caisse/banque, rapprochements",
    "finances.valider": "Valider une dépense ou un transfert",
    "rh.consulter": "Dossiers du personnel, présences, éléments de paie",
    "rh.saisir": "Dossiers, présences, congés, éléments variables de paie",
}

_CONSULTATIONS = frozenset(p for p in CATALOGUE if p.endswith(".consulter"))

_MATRICE: dict[str, frozenset[str]] = {
    # Vue transversale sur tout ; aucune saisie obligatoire ; valide ce qui engage l'usine.
    "dg": _CONSULTATIONS | {
        "audit.verifier",
        "stock.valider_ajustement",
        "stock.valider_sortie_exceptionnelle",
        "stock.valider_entree_directe",
        "production.annuler",
        "delegations.gerer",
        "achats.valider",
        "finances.valider",
        "ventes.valider_engagement",
    },
    "chef_production": frozenset({
        "production.consulter", "doctor_rewinder.consulter", "stock.consulter",
        "referentiels.consulter", "modeles.consulter",
        "modeles.saisir", "production.saisir",
        "production.valider", "doctor_rewinder.valider",
    }),
    "directeur_commercial": frozenset({
        "clients.consulter", "ventes.consulter", "stock.consulter",
        "tableaux_de_bord.consulter", "referentiels.consulter",
        "clients.saisir", "ventes.saisir",
        "ventes.valider_conditions",
    }),
    "responsable_stock": frozenset({
        "stock.consulter", "production.consulter", "referentiels.consulter", "achats.consulter",
        "modeles.consulter",
        "stock.saisir", "achats.saisir", "referentiels.saisir",
        "stock.valider_reception", "stock.executer_sortie", "production.cloturer",
    }),
    "comptable": frozenset({
        "ventes.consulter", "clients.consulter", "achats.consulter", "finances.consulter",
        "finances.saisir",
    }),
    "responsable_rh": frozenset({"rh.consulter", "rh.saisir"}),
    # Technique uniquement : jamais les donnees salariales ni le journal d'audit metier.
    "administrateur": frozenset({
        "utilisateurs.consulter", "utilisateurs.gerer",
        "parametres.consulter", "parametres.gerer",
        "journal_technique.consulter",
    }),
}


# Validations que le DG peut confier a un delegataire pour une duree limitee. Rien d'autre ne se delegue :
# ni la gestion des comptes, ni l'audit, ni la delegation elle-meme.
DELEGABLES: frozenset[str] = frozenset({
    "achats.valider",
    "stock.valider_ajustement",
    "stock.valider_sortie_exceptionnelle",
    "stock.valider_entree_directe",
    "finances.valider",
    "ventes.valider_engagement",
})


# Valider suppose de pouvoir voir ce qu'on valide. Une delegation emporte donc, pour sa duree seulement,
# la lecture correspondante : jamais de droit de saisie, ni de lecture d'un autre domaine.
LECTURE_IMPLICITE: dict[str, frozenset[str]] = {
    "achats.valider": frozenset({"achats.consulter"}),
    "stock.valider_ajustement": frozenset({"stock.consulter", "referentiels.consulter"}),
    "stock.valider_sortie_exceptionnelle": frozenset({"stock.consulter", "referentiels.consulter"}),
    "stock.valider_entree_directe": frozenset({"stock.consulter", "referentiels.consulter"}),
    "finances.valider": frozenset({"finances.consulter"}),
    "ventes.valider_engagement": frozenset({"ventes.consulter", "clients.consulter"}),
}


def droits_couverts(permissions: list[str] | set[str]) -> set[str]:
    """Les droits d'une delegation, plus la lecture qu'ils impliquent."""
    couverts = set(permissions)
    for permission in permissions:
        couverts |= LECTURE_IMPLICITE.get(permission, frozenset())
    return couverts


def a_la_permission(role: str, permission: str) -> bool:
    return permission in _MATRICE.get(role, frozenset())


def permissions_du_role(role: str) -> list[str]:
    return sorted(_MATRICE.get(role, frozenset()))


def matrice() -> dict[str, frozenset[str]]:
    return dict(_MATRICE)


class ConflitDeSeparation(Exception):
    """Une meme personne tente de saisir et de valider la meme operation."""


def exiger_valideur_distinct(cree_par: object, valide_par: object) -> None:
    """Separation saisie/validation imposee par le systeme, pas par la procedure."""
    if valide_par is None or cree_par == valide_par:
        raise ConflitDeSeparation("La validation doit être faite par une autre personne que la saisie.")
