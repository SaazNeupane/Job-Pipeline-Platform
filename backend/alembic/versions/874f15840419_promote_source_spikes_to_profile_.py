"""promote source spikes to profile columns

Revision ID: 874f15840419
Revises: 642238274604
Create Date: 2026-08-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '874f15840419'
down_revision: Union[str, Sequence[str], None] = '642238274604'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLUMNS = [
    'workday_boards_json',
    'smartrecruiters_companies_json',
    'workable_accounts_json',
    'recruitee_companies_json',
    'breezy_companies_json',
    'company_site_trackers_json',
]


def upgrade() -> None:
    """Upgrade schema."""
    # server_default so the existing profiles table (real rows already in it, e.g. the
    # real saazinmail@gmail.com account) doesn't fail a bare NOT NULL add-column -- same
    # pattern as 642238274604's target_regions_json.
    for column_name in _NEW_COLUMNS:
        op.add_column('profiles', sa.Column(column_name, sa.JSON(), nullable=False, server_default=sa.text("'[]'")))


def downgrade() -> None:
    """Downgrade schema."""
    for column_name in _NEW_COLUMNS:
        op.drop_column('profiles', column_name)
