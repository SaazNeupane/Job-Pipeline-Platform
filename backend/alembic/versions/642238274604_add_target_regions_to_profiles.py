"""add target_regions to profiles

Revision ID: 642238274604
Revises: ade72aa6b716
Create Date: 2026-08-19 21:51:39.175868

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '642238274604'
down_revision: Union[str, Sequence[str], None] = 'ade72aa6b716'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default so the existing profiles table (real rows already in it) doesn't
    # fail a bare NOT NULL add-column. Same unrelated NOT NULL drift autogenerate keeps
    # proposing on older columns is left out here, same reasoning as ade72aa6b716.
    op.add_column('profiles', sa.Column('target_regions_json', sa.JSON(), nullable=False, server_default=sa.text("'[]'")))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('profiles', 'target_regions_json')
