"""Point d'entree de l'API Barryson ERP."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import engine
from app.core.securite_http import installer_securite_http
from app.modules.identite import routes as identite

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    # Description de l'API publiee en developpement local uniquement (pas en recette exposee).
    docs_url="/api/docs" if settings.docs_publiques else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.docs_publiques else None,
)

installer_securite_http(app, settings)
identite.installer_gestionnaires(app)
app.include_router(identite.router)


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
