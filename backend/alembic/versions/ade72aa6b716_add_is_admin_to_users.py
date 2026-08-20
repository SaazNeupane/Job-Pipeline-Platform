"""add is_admin to users

Revision ID: ade72aa6b716
Revises: a53888d23cec
Create Date: 2026-08-19 21:43:20.365754

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ade72aa6b716'
down_revision: Union[str, Sequence[str], None] = 'a53888d23cec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default so the existing users table (real rows already in it) doesn't fail a
    # bare NOT NULL add-column -- same convention as every other added-column migration in
    # this project. Autogenerate also proposed several unrelated NOT NULL tightenings on
    # older columns (pre-existing drift between the models and the live schema); left out
    # here since they're out of scope for this change and unverified against live data.
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'is_admin')
