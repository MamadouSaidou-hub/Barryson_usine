"""Erreurs metier communes a tous les modules et leur traduction HTTP.

Les services levent ces erreurs sans rien savoir de HTTP ; un gestionnaire
unique les traduit en reponse JSON `{"detail": ...}` avec le code porte par
la classe.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ErreurMetier(Exception):
    message = "Opération refusée."
    code_http = 400
    # Champs ajoutes a la reponse, pour que l'interface reagisse sans analyser le texte.
    details: dict[str, Any] = {}

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message


class DonneesInvalides(ErreurMetier):
    code_http = 400


class OperationInterdite(ErreurMetier):
    code_http = 403


class Introuvable(ErreurMetier):
    # Aussi pour une ressource d'une autre entreprise : on ne confirme pas son existence.
    message = "Ressource introuvable."
    code_http = 404


class Conflit(ErreurMetier):
    code_http = 409


def installer_gestionnaire(app: FastAPI) -> None:
    def gerer(_request: Request, erreur: Exception) -> JSONResponse:
        assert isinstance(erreur, ErreurMetier)
        contenu = {"detail": erreur.message, **erreur.details}
        return JSONResponse(status_code=erreur.code_http, content=contenu)

    app.add_exception_handler(ErreurMetier, gerer)
