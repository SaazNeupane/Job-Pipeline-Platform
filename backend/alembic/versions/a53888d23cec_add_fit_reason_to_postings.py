"""add fit_reason to postings

Revision ID: a53888d23cec
Revises: 0dffb73d5478
Create Date: 2026-08-19 00:02:47.250687

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a53888d23cec'
down_revision: Union[str, Sequence[str], None] = '0dffb73d5478'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default='' needed against a table with existing rows -- see the identical note
    # on the previous migration (0dffb73d5478).
    op.add_column('postings', sa.Column('fit_reason', sa.Text(), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('postings', 'fit_reason')
