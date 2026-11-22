"""types de mouvement manuels (saisie sans circuit de validation)

Revision ID: d3f81c20a6e7
Revises: c7d2a95e41b8
Create Date: 2026-11-22 21:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = 'd3f81c20a6e7'
down_revision: str | None = 'c7d2a95e41b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOM = 'ck_mouvements_stock_type_connu'
ANCIENS = ('reception', 'entree', 'entree_directe', 'retour', 'consommation', 'sortie',
           'sortie_exceptionnelle', 'rebut_destruction', 'transformation', 'ajustement', 'inventaire')
NOUVEAUX = ANCIENS + ('entree_manuelle', 'sortie_manuelle')


def _liste(valeurs: tuple[str, ...]) -> str:
    return ', '.join(repr(v) for v in valeurs)


def upgrade() -> None:
    op.drop_constraint(op.f(NOM), 'mouvements_stock', type_='check')
    op.create_check_constraint(op.f(NOM), 'mouvements_stock', f'type IN ({_liste(NOUVEAUX)})')


def downgrade() -> None:
    op.drop_constraint(op.f(NOM), 'mouvements_stock', type_='check')
    op.create_check_constraint(op.f(NOM), 'mouvements_stock', f'type IN ({_liste(ANCIENS)})')
