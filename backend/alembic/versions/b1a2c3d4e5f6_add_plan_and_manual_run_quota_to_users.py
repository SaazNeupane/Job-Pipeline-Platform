"""add plan and manual run quota to users

Revision ID: b1a2c3d4e5f6
Revises: 874f15840419
Create Date: 2026-08-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1a2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '874f15840419'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('plan', sa.String(), nullable=False, server_default='free'))
    op.add_column('users', sa.Column('manual_run_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('manual_run_period', sa.String(), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('users', 'manual_run_period')
    op.drop_column('users', 'manual_run_count')
    op.drop_column('users', 'plan')
