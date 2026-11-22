// Tous les libelles affiches : vocabulaire de l'usine, en francais, a un seul endroit.

export type Ton = "neutre" | "ok" | "info" | "alerte" | "danger";

export const ROLES: Record<string, string> = {
  dg: "Directeur général",
  chef_production: "Chef de production",
  directeur_commercial: "Directeur commercial",
  responsable_stock: "Responsable stock",
  comptable: "Comptable",
  responsable_rh: "Responsable RH",
  administrateur: "Administrateur",
};

export const STATUTS_COMMANDE: Record<string, { libelle: string; ton: Ton }> = {
  brouillon: { libelle: "Brouillon", ton: "neutre" },
  soumise: { libelle: "À valider par le DG", ton: "alerte" },
  validee: { libelle: "Validée", ton: "info" },
  refusee: { libelle: "Refusée", ton: "danger" },
  commandee: { libelle: "Commandée au fournisseur", ton: "info" },
  partiellement_recue: { libelle: "Partiellement reçue", ton: "alerte" },
  recue: { libelle: "Reçue", ton: "ok" },
  cloturee: { libelle: "Soldée", ton: "neutre" },
  annulee: { libelle: "Annulée", ton: "danger" },
};

export const STATUTS_RECEPTION: Record<string, { libelle: string; ton: Ton }> = {
  en_controle: { libelle: "À contrôler", ton: "alerte" },
  acceptee: { libelle: "Acceptée", ton: "ok" },
  acceptee_avec_reserves: { libelle: "Acceptée avec réserves", ton: "alerte" },
  refusee: { libelle: "Refusée", ton: "danger" },
};

export const STATUTS_MOUVEMENT: Record<string, { libelle: string; ton: Ton }> = {
  en_attente: { libelle: "En attente de validation", ton: "alerte" },
  valide: { libelle: "Validé", ton: "ok" },
  rejete: { libelle: "Rejeté", ton: "danger" },
};

export const TYPES_MOUVEMENT: Record<string, string> = {
  reception: "Réception",
  entree: "Entrée de fabrication",
  entree_directe: "Entrée directe",
  retour: "Retour",
  consommation: "Consommation",
  sortie: "Sortie (livraison)",
  sortie_exceptionnelle: "Sortie exceptionnelle",
  rebut_destruction: "Rebut / destruction",
  transformation: "Transformation",
  ajustement: "Ajustement",
  inventaire: "Inventaire",
};

export const FINITIONS: Record<string, string> = {
  or_transparent: "Or transparent",
  jaune_transparent: "Jaune transparent",
  transparent_clair: "Transparent clair",
  kaki_simple: "Kaki simple",
  kaki_imprime: "Kaki imprimé",
};

export const NIVEAUX: Record<string, string> = {
  matiere_premiere: "Matière première",
  semi_fini: "Semi-fini acheté",
  produit_fini: "Produit fini",
};

export const DEVISES = ["USD", "EUR", "GNF", "CNY"] as const;

export const DROITS_DELEGABLES: Record<string, string> = {
  "achats.valider": "Valider les commandes d'achat",
  "stock.valider_ajustement": "Valider les ajustements de stock",
  "stock.valider_sortie_exceptionnelle": "Valider les sorties exceptionnelles",
  "stock.valider_entree_directe": "Valider les entrées directes de produits finis",
  "finances.valider": "Valider les dépenses et transferts",
  "ventes.valider_engagement": "Valider les engagements commerciaux",
  "production.valider": "Valider les résultats de fabrication",
  "doctor_rewinder.valider": "Valider le traitement Doctor Rewinder",
};

export const STATUTS_ENCOURS: Record<string, { libelle: string; ton: Ton }> = {
  en_cours: { libelle: "Chez le Doctor Rewinder", ton: "info" },
  a_valider: { libelle: "Traitement à valider", ton: "alerte" },
  traite: { libelle: "Traité", ton: "ok" },
};

export const STATUTS_OF: Record<string, { libelle: string; ton: Ton }> = {
  brouillon: { libelle: "Brouillon", ton: "neutre" },
  soumis: { libelle: "Matières à sortir", ton: "alerte" },
  matieres_validees: { libelle: "Prêt à démarrer", ton: "info" },
  en_cours: { libelle: "En fabrication", ton: "info" },
  resultat_saisi: { libelle: "Résultat à valider", ton: "alerte" },
  resultat_valide: { libelle: "À clôturer", ton: "info" },
  cloture: { libelle: "Clôturé", ton: "ok" },
  annule: { libelle: "Annulé", ton: "danger" },
};
