"""Contrat d'API du module referentiel.

Modification partielle (PATCH) : seuls les champs envoyes sont modifies, et
`null` explicite efface une valeur facultative. Les champs fixes a vie (code,
niveau de stock, unite, famille) n'existent pas dans les schemas de
modification : impossible de les changer par erreur ou par malveillance.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, ClassVar

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

from app.modules.referentiel.models import FamilleRuban, NiveauStock, TypeClient, Unite

# Normalise avant de valider : Pydantic controle le motif avant ses propres transformations.
Code = Annotated[str, BeforeValidator(lambda v: v.strip().upper() if isinstance(v, str) else v),
                 StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9._-]{1,39}$")]
Nom = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=150)]
NomLong = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
Texte = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Telephone = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\+?[0-9 ()./-]{6,40}$")]
Email = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200,
                                         pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
# Decimales exactes en entree ; nombres JSON en sortie, plus simples pour l'interface.
Nombre = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]
Positif = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3)]
PositifOuNul = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]
Largeur = Annotated[Decimal, Field(gt=0, le=2000, decimal_places=2)]
Facteur = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6)]
Pieces = Annotated[int, Field(gt=0, le=100_000)]
Jours = Annotated[int, Field(ge=0, le=365)]


class _Entree(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Modification(_Entree):
    """Un champ obligatoire peut etre omis, pas vide : `null` n'est admis que pour l'effacer
    s'il est facultatif."""

    _non_effacables: ClassVar[frozenset[str]] = frozenset({"nom", "actif", "facteur", "pieces_par_tour",
                                                          "pieces_par_carton", "type_client"})

    @model_validator(mode="after")
    def _refuser_effacement_obligatoire(self) -> "_Modification":
        vides = sorted(c for c in self.model_fields_set & self._non_effacables if getattr(self, c) is None)
        if vides:
            raise ValueError(f"Champ(s) obligatoire(s), ne peuvent pas être vidés : {', '.join(vides)}")
        return self


class _Sortie(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Articles ----------------------------------------------------------------


class ArticleCreation(_Entree):
    code: Code
    nom: Nom
    niveau_stock: NiveauStock
    unite_gestion: Unite
    seuil_min: PositifOuNul | None = None
    seuil_max: PositifOuNul | None = None


class ArticleModification(_Modification):
    nom: Nom | None = None
    seuil_min: PositifOuNul | None = None
    seuil_max: PositifOuNul | None = None
    actif: bool | None = None


class ArticlePublic(_Sortie):
    id: uuid.UUID
    code: str
    nom: str
    niveau_stock: str
    unite_gestion: str
    seuil_min: Nombre | None
    seuil_max: Nombre | None
    actif: bool


# --- Conversions d'unites ----------------------------------------------------


class ConversionCreation(_Entree):
    article_id: uuid.UUID | None = None
    unite_source: Unite
    unite_cible: Unite
    facteur: Facteur


class ConversionModification(_Modification):
    facteur: Facteur | None = None
    actif: bool | None = None


class ConversionPublic(_Sortie):
    id: uuid.UUID
    article_id: uuid.UUID | None
    unite_source: str
    unite_cible: str
    facteur: Nombre
    actif: bool


# --- Moules ------------------------------------------------------------------


class MouleCreation(_Entree):
    code: Code
    nom: Nom
    description: Texte | None = None


class MouleModification(_Modification):
    nom: Nom | None = None
    description: Texte | None = None
    actif: bool | None = None


class MoulePublic(_Sortie):
    id: uuid.UUID
    code: str
    nom: str
    description: str | None
    actif: bool


# --- References de production ------------------------------------------------


class LargeurCreation(_Entree):
    largeur_mm: Largeur
    pieces_par_tour: Pieces


class LargeurModification(_Entree):
    pieces_par_tour: Pieces


class LargeurPublic(_Sortie):
    id: uuid.UUID
    largeur_mm: Nombre
    pieces_par_tour: int


class ConditionnementCreation(_Entree):
    famille: FamilleRuban
    largeur_mm: Largeur
    longueur_m: Positif
    pieces_par_carton: Pieces


class ConditionnementModification(_Entree):
    pieces_par_carton: Pieces


class ConditionnementPublic(_Sortie):
    id: uuid.UUID
    famille: str
    largeur_mm: Nombre
    longueur_m: Nombre
    pieces_par_carton: int


# --- Modeles de ruban (versionnes) ------------------------------------------


class _CaracteristiquesVersion(_Entree):
    moule_id: uuid.UUID | None = None
    article_produit_fini_id: uuid.UUID | None = None
    article_tube_id: uuid.UUID | None = None
    # Facultatifs : deduits des references usine (largeur -> pieces/tour, famille +
    # dimensions -> pieces/carton) quand ils ne sont pas fournis.
    pieces_par_tour: Pieces | None = None
    pieces_par_carton: Pieces | None = None


class ModeleCreation(_CaracteristiquesVersion):
    code: Code
    nom: Nom
    famille: FamilleRuban
    largeur_mm: Largeur
    longueur_rouleau_m: Positif


class NouvelleVersion(_CaracteristiquesVersion):
    """Les champs absents sont repris de la version en vigueur."""

    largeur_mm: Largeur | None = None
    longueur_rouleau_m: Positif | None = None
    motif: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=300)]


class ModeleModification(_Modification):
    nom: Nom | None = None
    actif: bool | None = None


class VersionPublic(_Sortie):
    id: uuid.UUID
    numero: int
    largeur_mm: Nombre
    longueur_rouleau_m: Nombre
    pieces_par_tour: int
    pieces_par_carton: int
    moule_id: uuid.UUID | None
    article_produit_fini_id: uuid.UUID | None
    article_tube_id: uuid.UUID | None
    motif: str
    cree_par: uuid.UUID | None
    cree_le: datetime


class ModelePublic(BaseModel):
    id: uuid.UUID
    code: str
    nom: str
    famille: str
    actif: bool
    version_courante: VersionPublic
    # Vrai quand moule, produit fini et tube sont connus : condition pour lancer un ordre.
    complet: bool


# --- Clients et fournisseurs ------------------------------------------------


class ClientCreation(_Entree):
    code: Code
    nom: NomLong
    type_client: TypeClient
    telephone: Telephone | None = None
    adresse: Texte | None = None
    zone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    plafond_encours_gnf: Annotated[int, Field(ge=0, le=10**15)] | None = None
    delai_paiement_jours: Jours | None = None


class ClientModification(_Modification):
    nom: NomLong | None = None
    type_client: TypeClient | None = None
    telephone: Telephone | None = None
    adresse: Texte | None = None
    zone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    plafond_encours_gnf: Annotated[int, Field(ge=0, le=10**15)] | None = None
    delai_paiement_jours: Jours | None = None
    actif: bool | None = None


class ClientPublic(_Sortie):
    id: uuid.UUID
    code: str
    nom: str
    type_client: str
    telephone: str | None
    adresse: str | None
    zone: str | None
    plafond_encours_gnf: int | None
    delai_paiement_jours: int | None
    actif: bool


class FournisseurCreation(_Entree):
    code: Code
    nom: NomLong
    pays: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    telephone: Telephone | None = None
    email: Email | None = None
    adresse: Texte | None = None
    conditions_paiement: Texte | None = None
    delai_livraison_jours: Jours | None = None


class FournisseurModification(_Modification):
    nom: NomLong | None = None
    pays: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    telephone: Telephone | None = None
    email: Email | None = None
    adresse: Texte | None = None
    conditions_paiement: Texte | None = None
    delai_livraison_jours: Jours | None = None
    actif: bool | None = None


class FournisseurPublic(_Sortie):
    id: uuid.UUID
    code: str
    nom: str
    pays: str | None
    telephone: str | None
    email: str | None
    adresse: str | None
    conditions_paiement: str | None
    delai_livraison_jours: int | None
    actif: bool
