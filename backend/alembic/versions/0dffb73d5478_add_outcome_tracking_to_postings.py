"""add outcome tracking to postings

Revision ID: 0dffb73d5478
Revises: 37469073b317
Create Date: 2026-08-18 23:55:35.865122

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0dffb73d5478'
down_revision: Union[str, Sequence[str], None] = '37469073b317'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default='' needed here (not in models.py's own default=, which is Python-side
    # only) -- ADD COLUMN ... NOT NULL with no default fails against Postgres on a table
    # that already has rows (203 real ones for the real account), since existing rows have
    # no value to backfill from otherwise.
    op.add_column('postings', sa.Column('outcome', sa.String(), nullable=False, server_default=''))
    op.add_column('postings', sa.Column('outcome_updated_at', sa.String(), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('postings', 'outcome_updated_at')
    op.drop_column('postings', 'outcome')
