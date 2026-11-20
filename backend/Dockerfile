FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Correctifs de securite du systeme de base appliques a chaque construction
# (l'image officielle Python peut avoir quelques jours de retard).
# libpq5 : client PostgreSQL du systeme, maintenu par Debian, plutot que la
# copie embarquee dans la roue psycopg-binary.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# L'application ne tourne jamais en root.
RUN adduser --disabled-password --gecos "" --uid 1000 appuser

# L'image de production ne contient ni pytest, ni ruff, ni les tests, ni meme
# pip et setuptools : inutiles une fois l'application installee, ils ne feraient
# qu'elargir la surface d'attaque.
ARG INSTALLER_DEV=false
COPY requirements.txt requirements-dev.txt ./
RUN pip install --upgrade pip setuptools \
    && pip install -r requirements.txt \
    && if [ "$INSTALLER_DEV" = "true" ]; then \
           pip install -r requirements-dev.txt; \
       else \
           pip uninstall -y setuptools && python -m pip uninstall -y pip; \
       fi

COPY . .
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
