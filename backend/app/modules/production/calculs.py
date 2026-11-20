"""Calculs de fabrication : fonctions pures, sans base de donnees ni HTTP.

Formules du cahier des charges technique §6.3 et §6.4. Elles sont isolees ici
parce que la formule du resultat reel doit etre reconfirmee en atelier avec le
chef de production : on doit pouvoir l'ajuster sans toucher au cycle de vie de
l'ordre de fabrication. `VERSION_FORMULE` est stockee avec chaque resultat
valide pour savoir, plus tard, avec quelle regle il a ete calcule.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

VERSION_FORMULE = "2026-11-20-v1"


class ErreurCalcul(ValueError):
    """Donnees impossibles physiquement (ex. plus de tours defectueux que de tours)."""


@dataclass(frozen=True)
class Prevision:
    tours_complets: int
    pieces_theoriques: int
    cartons_complets: int
    pieces_restantes: int


@dataclass(frozen=True)
class SaisieResultat:
    tours_totaux: int
    tours_defectueux: int
    pieces_defectueuses_supplementaires: int
    quantite_doctor_rewinder: int
    pertes_definitives: int


@dataclass(frozen=True)
class Resultat:
    pieces_brutes: int
    pieces_non_conformes: int
    # Non conformes - (Doctor Rewinder + pertes) : doit valoir 0. Positif = piece oubliee,
    # negatif = piece comptee deux fois.
    ecart_comptage: int
    pieces_conformes: int
    cartons_complets: int
    pieces_restantes: int
    ecart_pieces: int
    ecart_pourcentage: Decimal
    rendement: Decimal

    @property
    def coherent(self) -> bool:
        return self.ecart_comptage == 0


def prevoir(metrage_engage: Decimal, longueur_rouleau_m: Decimal, pieces_par_tour: int,
            pieces_par_carton: int) -> Prevision:
    """Prevision theorique sur le metrage reel de la bobine, jamais sur un metrage standard."""
    if metrage_engage <= 0 or longueur_rouleau_m <= 0 or pieces_par_tour <= 0 or pieces_par_carton <= 0:
        raise ErreurCalcul("Metrage, longueur de rouleau et pieces par tour/carton doivent etre positifs.")
    tours_complets = int(metrage_engage // longueur_rouleau_m)
    pieces_theoriques = tours_complets * pieces_par_tour
    cartons_complets = pieces_theoriques // pieces_par_carton
    return Prevision(tours_complets, pieces_theoriques, cartons_complets,
                     pieces_theoriques - cartons_complets * pieces_par_carton)


def _arrondi(valeur: Decimal, decimales: str) -> Decimal:
    return valeur.quantize(Decimal(decimales), rounding=ROUND_HALF_UP)


def calculer_resultat(saisie: SaisieResultat, pieces_par_tour: int, pieces_par_carton: int,
                      pieces_theoriques: int) -> Resultat:
    valeurs = (saisie.tours_totaux, saisie.tours_defectueux, saisie.pieces_defectueuses_supplementaires,
               saisie.quantite_doctor_rewinder, saisie.pertes_definitives)
    if min(valeurs) < 0:
        raise ErreurCalcul("Aucune quantite saisie ne peut etre negative.")
    if saisie.tours_defectueux > saisie.tours_totaux:
        raise ErreurCalcul("Il ne peut pas y avoir plus de tours entierement defectueux que de tours "
                           "effectues.")

    pieces_brutes = saisie.tours_totaux * pieces_par_tour
    non_conformes = (saisie.tours_defectueux * pieces_par_tour) + saisie.pieces_defectueuses_supplementaires
    if non_conformes > pieces_brutes:
        raise ErreurCalcul("Les pieces non conformes depassent les pieces produites.")

    conformes = pieces_brutes - non_conformes
    cartons = conformes // pieces_par_carton
    ecart = conformes - pieces_theoriques
    if pieces_theoriques > 0:
        pourcentage = _arrondi(Decimal(ecart) * 100 / Decimal(pieces_theoriques), "0.01")
        rendement = _arrondi(Decimal(conformes) / Decimal(pieces_theoriques), "0.0001")
    else:
        pourcentage = rendement = Decimal(0)
    return Resultat(
        pieces_brutes=pieces_brutes,
        pieces_non_conformes=non_conformes,
        ecart_comptage=non_conformes - (saisie.quantite_doctor_rewinder + saisie.pertes_definitives),
        pieces_conformes=conformes,
        cartons_complets=cartons,
        pieces_restantes=conformes - cartons * pieces_par_carton,
        ecart_pieces=ecart,
        ecart_pourcentage=pourcentage,
        rendement=rendement,
    )
