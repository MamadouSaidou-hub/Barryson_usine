"""socle initial

Revision ID: 1b8ea6852b17
Revises: 
Create Date: 2026-11-14 14:18:05.837914

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '1b8ea6852b17'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
