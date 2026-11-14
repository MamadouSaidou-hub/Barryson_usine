"""Point d'entree de l'API Barryson ERP."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import engine

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    # La documentation interactive est fermee en production.
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/api/openapi.json",
)


@app.get("/healthz", tags=["Supervision"])
def liveness() -> dict:
    """Le processus repond. Ne depend d'aucun service externe."""
    return {
        "statut": "ok",
        "application": settings.app_name,
        "environnement": settings.environment,
    }


@app.get("/readyz", tags=["Supervision"])
def readiness() -> JSONResponse:
    """Verifie que la base de donnees est joignable (sonde de disponibilite)."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        base_de_donnees = "ok"
    except Exception as erreur:  # noqa: BLE001 - on expose un etat, pas la trace
        base_de_donnees = f"injoignable ({type(erreur).__name__})"

    pret = base_de_donnees == "ok"
    return JSONResponse(
        status_code=200 if pret else 503,
        content={"statut": "ok" if pret else "degrade", "base_de_donnees": base_de_donnees},
    )
