"""lien d'une ligne de commande vers le catalogue fournisseur

Revision ID: a4d6e1b92f37
Revises: cf43be708622
Create Date: 2026-11-20 15:50:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a4d6e1b92f37'
down_revision: str | None = 'cf43be708622'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK = 'fk_lignes_commande_achat_catalogue_id_catalogue_fournisseur'


def upgrade() -> None:
    op.add_column('lignes_commande_achat', sa.Column('catalogue_id', sa.UUID(), nullable=True))
    op.create_foreign_key(FK, 'lignes_commande_achat', 'catalogue_fournisseur', ['catalogue_id'], ['id'])
    # Golden01 et Golden03 sont deux produits distincts de meme finition : l'unicite tient compte du catalogue.
    op.drop_constraint('uq_lignes_commande_achat_article', 'lignes_commande_achat', type_='unique')
    op.create_unique_constraint('uq_lignes_commande_achat_article', 'lignes_commande_achat',
                                ['commande_id', 'article_id', 'couleur_finition', 'catalogue_id'],
                                postgresql_nulls_not_distinct=True)


def downgrade() -> None:
    op.drop_constraint('uq_lignes_commande_achat_article', 'lignes_commande_achat', type_='unique')
    op.create_unique_constraint('uq_lignes_commande_achat_article', 'lignes_commande_achat',
                                ['commande_id', 'article_id', 'couleur_finition'],
                                postgresql_nulls_not_distinct=True)
    op.drop_constraint(FK, 'lignes_commande_achat', type_='foreignkey')
    op.drop_column('lignes_commande_achat', 'catalogue_id')
