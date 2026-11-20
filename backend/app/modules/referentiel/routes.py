"""Points d'entree HTTP du module referentiel. Aucune regle ici : tout est dans service.py.

Aucune route DELETE : on desactive (`actif: false`), on ne supprime pas.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.modules.identite.dependances import Contexte, exiger
from app.modules.referentiel import service
from app.modules.referentiel.models import (
    Article,
    Client,
    ConversionUnite,
    Fournisseur,
    LargeurReference,
    ModeleRuban,
    Moule,
    NiveauStock,
    ReferenceConditionnement,
)
from app.modules.referentiel.schemas import (
    ArticleCreation,
    ArticleModification,
    ArticlePublic,
    ClientCreation,
    ClientModification,
    ClientPublic,
    ConditionnementCreation,
    ConditionnementModification,
    ConditionnementPublic,
    ConversionCreation,
    ConversionModification,
    ConversionPublic,
    FournisseurCreation,
    FournisseurModification,
    FournisseurPublic,
    LargeurCreation,
    LargeurModification,
    LargeurPublic,
    ModeleCreation,
    ModeleModification,
    ModelePublic,
    MouleCreation,
    MouleModification,
    MoulePublic,
    NouvelleVersion,
    VersionPublic,
)

router = APIRouter(prefix="/api")

Actif = Annotated[bool | None, Query(description="Filtrer sur les éléments actifs ou désactivés")]
Recherche = Annotated[str | None, Query(max_length=100, description="Recherche dans le code et le nom")]


def _ctx(permission: str):
    return Annotated[Contexte, Depends(exiger(permission))]


Lecture = _ctx("referentiels.consulter")
Saisie = _ctx("referentiels.saisir")
LectureModeles = _ctx("modeles.consulter")
SaisieModeles = _ctx("modeles.saisir")
LectureClients = _ctx("clients.consulter")
SaisieClients = _ctx("clients.saisir")
LectureFournisseurs = _ctx("achats.consulter")
SaisieFournisseurs = _ctx("achats.saisir")


def _changements(demande) -> dict:
    # Seuls les champs envoyes : un champ absent n'est pas une remise a zero.
    return demande.model_dump(exclude_unset=True)


# --- Articles ----------------------------------------------------------------


@router.get("/articles", response_model=list[ArticlePublic], tags=["Référentiel"])
def lister_articles(ctx: Lecture, actif: Actif = None, recherche: Recherche = None,
                    niveau: Annotated[NiveauStock | None, Query()] = None):
    return service.lister(ctx.db, Article, ctx.utilisateur, actif=actif, recherche=recherche,
                          niveau_stock=niveau)


@router.get("/articles/{article_id}", response_model=ArticlePublic, tags=["Référentiel"])
def lire_article(article_id: uuid.UUID, ctx: Lecture):
    return service.charger(ctx.db, Article, ctx.utilisateur, article_id)


@router.post("/articles", response_model=ArticlePublic, status_code=status.HTTP_201_CREATED,
             tags=["Référentiel"])
def creer_article(demande: ArticleCreation, ctx: Saisie):
    return service.creer_article(ctx.db, ctx.utilisateur, demande.model_dump())


@router.patch("/articles/{article_id}", response_model=ArticlePublic, tags=["Référentiel"])
def modifier_article(article_id: uuid.UUID, demande: ArticleModification, ctx: Saisie):
    return service.modifier_article(ctx.db, ctx.utilisateur, article_id, _changements(demande))


# --- Conversions d'unites ----------------------------------------------------


@router.get("/conversions-unites", response_model=list[ConversionPublic], tags=["Référentiel"])
def lister_conversions(ctx: Lecture, actif: Actif = None):
    return service.lister(ctx.db, ConversionUnite, ctx.utilisateur, actif=actif,
                          tri=ConversionUnite.unite_source)


@router.post("/conversions-unites", response_model=ConversionPublic, status_code=status.HTTP_201_CREATED,
             tags=["Référentiel"])
def creer_conversion(demande: ConversionCreation, ctx: Saisie):
    return service.creer_conversion(ctx.db, ctx.utilisateur, demande.model_dump())


@router.patch("/conversions-unites/{conversion_id}", response_model=ConversionPublic, tags=["Référentiel"])
def modifier_conversion(conversion_id: uuid.UUID, demande: ConversionModification, ctx: Saisie):
    return service.modifier_conversion(ctx.db, ctx.utilisateur, conversion_id, _changements(demande))


# --- Moules ------------------------------------------------------------------


@router.get("/moules", response_model=list[MoulePublic], tags=["Production — références"])
def lister_moules(ctx: LectureModeles, actif: Actif = None, recherche: Recherche = None):
    return service.lister(ctx.db, Moule, ctx.utilisateur, actif=actif, recherche=recherche)


@router.post("/moules", response_model=MoulePublic, status_code=status.HTTP_201_CREATED,
             tags=["Production — références"])
def creer_moule(demande: MouleCreation, ctx: SaisieModeles):
    return service.creer_simple(ctx.db, ctx.utilisateur, Moule, demande.model_dump())


@router.patch("/moules/{moule_id}", response_model=MoulePublic, tags=["Production — références"])
def modifier_moule(moule_id: uuid.UUID, demande: MouleModification, ctx: SaisieModeles):
    return service.modifier_simple(ctx.db, ctx.utilisateur, Moule, moule_id, _changements(demande))


# --- References de production ------------------------------------------------


@router.get("/references/largeurs", response_model=list[LargeurPublic], tags=["Production — références"])
def lister_largeurs(ctx: LectureModeles):
    return service.lister(ctx.db, LargeurReference, ctx.utilisateur, tri=LargeurReference.largeur_mm)


@router.post("/references/largeurs", response_model=LargeurPublic, status_code=status.HTTP_201_CREATED,
             tags=["Production — références"])
def creer_largeur(demande: LargeurCreation, ctx: SaisieModeles):
    return service.creer_largeur(ctx.db, ctx.utilisateur, demande.model_dump())


@router.patch("/references/largeurs/{reference_id}", response_model=LargeurPublic,
              tags=["Production — références"])
def modifier_largeur(reference_id: uuid.UUID, demande: LargeurModification, ctx: SaisieModeles):
    return service.modifier_simple(ctx.db, ctx.utilisateur, LargeurReference, reference_id,
                                   _changements(demande))


@router.get("/references/conditionnements", response_model=list[ConditionnementPublic],
            tags=["Production — références"])
def lister_conditionnements(ctx: LectureModeles):
    return service.lister(ctx.db, ReferenceConditionnement, ctx.utilisateur,
                          tri=(ReferenceConditionnement.famille, ReferenceConditionnement.largeur_mm,
                               ReferenceConditionnement.longueur_m))


@router.post("/references/conditionnements", response_model=ConditionnementPublic,
             status_code=status.HTTP_201_CREATED, tags=["Production — références"])
def creer_conditionnement(demande: ConditionnementCreation, ctx: SaisieModeles):
    return service.creer_conditionnement(ctx.db, ctx.utilisateur, demande.model_dump())


@router.patch("/references/conditionnements/{reference_id}", response_model=ConditionnementPublic,
              tags=["Production — références"])
def modifier_conditionnement(reference_id: uuid.UUID, demande: ConditionnementModification,
                             ctx: SaisieModeles):
    return service.modifier_simple(ctx.db, ctx.utilisateur, ReferenceConditionnement, reference_id,
                                   _changements(demande))


# --- Modeles de ruban ---------------------------------------------------------


def _modele_public(ctx: Contexte, modele: ModeleRuban) -> ModelePublic:
    courante = service.version_courante(ctx.db, modele.id)
    return ModelePublic(id=modele.id, code=modele.code, nom=modele.nom, famille=modele.famille,
                        actif=modele.actif, version_courante=VersionPublic.model_validate(courante),
                        complet=service.est_complet(courante))


@router.get("/modeles-ruban", response_model=list[ModelePublic], tags=["Production — modèles"])
def lister_modeles(ctx: LectureModeles, actif: Actif = None, recherche: Recherche = None):
    modeles = service.lister(ctx.db, ModeleRuban, ctx.utilisateur, actif=actif, recherche=recherche)
    return [_modele_public(ctx, m) for m in modeles]


@router.get("/modeles-ruban/{modele_id}", response_model=ModelePublic, tags=["Production — modèles"])
def lire_modele(modele_id: uuid.UUID, ctx: LectureModeles):
    return _modele_public(ctx, service.charger(ctx.db, ModeleRuban, ctx.utilisateur, modele_id))


@router.get("/modeles-ruban/{modele_id}/versions", response_model=list[VersionPublic],
            tags=["Production — modèles"])
def lister_versions(modele_id: uuid.UUID, ctx: LectureModeles):
    return service.historique(ctx.db, ctx.utilisateur, modele_id)


@router.post("/modeles-ruban", response_model=ModelePublic, status_code=status.HTTP_201_CREATED,
             tags=["Production — modèles"])
def creer_modele(demande: ModeleCreation, ctx: SaisieModeles):
    return _modele_public(ctx, service.creer_modele(ctx.db, ctx.utilisateur, demande.model_dump()))


@router.post("/modeles-ruban/{modele_id}/versions", response_model=ModelePublic,
             status_code=status.HTTP_201_CREATED, tags=["Production — modèles"])
def creer_version(modele_id: uuid.UUID, demande: NouvelleVersion, ctx: SaisieModeles):
    modele = service.nouvelle_version(ctx.db, ctx.utilisateur, modele_id, _changements(demande))
    return _modele_public(ctx, modele)


@router.patch("/modeles-ruban/{modele_id}", response_model=ModelePublic, tags=["Production — modèles"])
def modifier_modele(modele_id: uuid.UUID, demande: ModeleModification, ctx: SaisieModeles):
    return _modele_public(ctx, service.modifier_modele(ctx.db, ctx.utilisateur, modele_id,
                                                       _changements(demande)))


# --- Clients ------------------------------------------------------------------


@router.get("/clients", response_model=list[ClientPublic], tags=["Clients et fournisseurs"])
def lister_clients(ctx: LectureClients, actif: Actif = None, recherche: Recherche = None):
    return service.lister(ctx.db, Client, ctx.utilisateur, actif=actif, recherche=recherche)


@router.get("/clients/{client_id}", response_model=ClientPublic, tags=["Clients et fournisseurs"])
def lire_client(client_id: uuid.UUID, ctx: LectureClients):
    return service.charger(ctx.db, Client, ctx.utilisateur, client_id)


@router.post("/clients", response_model=ClientPublic, status_code=status.HTTP_201_CREATED,
             tags=["Clients et fournisseurs"])
def creer_client(demande: ClientCreation, ctx: SaisieClients):
    return service.creer_simple(ctx.db, ctx.utilisateur, Client, demande.model_dump())


@router.patch("/clients/{client_id}", response_model=ClientPublic, tags=["Clients et fournisseurs"])
def modifier_client(client_id: uuid.UUID, demande: ClientModification, ctx: SaisieClients):
    return service.modifier_simple(ctx.db, ctx.utilisateur, Client, client_id, _changements(demande))


# --- Fournisseurs -------------------------------------------------------------


@router.get("/fournisseurs", response_model=list[FournisseurPublic], tags=["Clients et fournisseurs"])
def lister_fournisseurs(ctx: LectureFournisseurs, actif: Actif = None, recherche: Recherche = None):
    return service.lister(ctx.db, Fournisseur, ctx.utilisateur, actif=actif, recherche=recherche)


@router.get("/fournisseurs/{fournisseur_id}", response_model=FournisseurPublic,
            tags=["Clients et fournisseurs"])
def lire_fournisseur(fournisseur_id: uuid.UUID, ctx: LectureFournisseurs):
    return service.charger(ctx.db, Fournisseur, ctx.utilisateur, fournisseur_id)


@router.post("/fournisseurs", response_model=FournisseurPublic, status_code=status.HTTP_201_CREATED,
             tags=["Clients et fournisseurs"])
def creer_fournisseur(demande: FournisseurCreation, ctx: SaisieFournisseurs):
    return service.creer_simple(ctx.db, ctx.utilisateur, Fournisseur, demande.model_dump())


@router.patch("/fournisseurs/{fournisseur_id}", response_model=FournisseurPublic,
              tags=["Clients et fournisseurs"])
def modifier_fournisseur(fournisseur_id: uuid.UUID, demande: FournisseurModification,
                         ctx: SaisieFournisseurs):
    return service.modifier_simple(ctx.db, ctx.utilisateur, Fournisseur, fournisseur_id,
                                   _changements(demande))
