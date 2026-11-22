"""prix et devise au catalogue fournisseur

Revision ID: c7d2a95e41b8
Revises: be8ef196b345
Create Date: 2026-11-22 20:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c7d2a95e41b8'
down_revision: str | None = 'be8ef196b345'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = 'catalogue_fournisseur'


def upgrade() -> None:
    op.add_column(TABLE, sa.Column('prix_unitaire', sa.Numeric(16, 4), nullable=True))
    op.add_column(TABLE, sa.Column('devise_prix', sa.String(3), nullable=True))
    op.create_check_constraint(op.f('ck_catalogue_fournisseur_prix_catalogue_positif'), TABLE, 'prix_unitaire IS NULL OR prix_unitaire >= 0')
    op.create_check_constraint(op.f('ck_catalogue_fournisseur_prix_et_devise'), TABLE, '(prix_unitaire IS NULL) = (devise_prix IS NULL)')
    op.create_check_constraint(op.f('ck_catalogue_fournisseur_devise_prix_connue'), TABLE,
                               "devise_prix IS NULL OR devise_prix IN ('USD', 'EUR', 'CNY', 'GNF')")


def downgrade() -> None:
    for nom in ('devise_prix_connue', 'prix_et_devise', 'prix_catalogue_positif'):
        op.drop_constraint(op.f(f'ck_catalogue_fournisseur_{nom}'), TABLE, type_='check')
    op.drop_column(TABLE, 'devise_prix')
    op.drop_column(TABLE, 'prix_unitaire')
