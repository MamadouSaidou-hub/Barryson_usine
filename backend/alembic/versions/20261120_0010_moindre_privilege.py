"""moindre privilege pour le compte applicatif

Le compte de l'API (membre de barryson_app_droits) n'est proprietaire de rien :
il ne peut ni modifier le schema, ni desactiver un trigger, ni toucher aux
lignes existantes des registres en ajout seul. Les tables futures recoivent
automatiquement les droits courants ; une migration qui cree un registre en
ajout seul doit retirer UPDATE/DELETE/TRUNCATE comme ci-dessous.

Revision ID: 8d41b7c0a2f6
Revises: 5c2f9a1d7e43
Create Date: 2026-11-20 00:10:00
"""
from collections.abc import Sequence

from alembic import op

revision: str = '8d41b7c0a2f6'
down_revision: str | None = '5c2f9a1d7e43'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GROUPE = "barryson_app_droits"
AJOUT_SEUL = ("journal_audit", "tentatives_connexion")
# Comptes et entreprises se desactivent, ils ne se suppriment jamais.
SANS_SUPPRESSION = ("utilisateurs", "entreprises")


def upgrade() -> None:
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{GROUPE}') "
        f"THEN CREATE ROLE {GROUPE} NOLOGIN; END IF; END $$"
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {GROUPE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {GROUPE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {GROUPE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {GROUPE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {GROUPE}")
    op.execute(f"REVOKE ALL ON alembic_version FROM {GROUPE}")
    for table in AJOUT_SEUL:
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM {GROUPE}")
    for table in SANS_SUPPRESSION:
        op.execute(f"REVOKE DELETE, TRUNCATE ON {table} FROM {GROUPE}")


def downgrade() -> None:
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {GROUPE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {GROUPE}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {GROUPE}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {GROUPE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {GROUPE}")
