"""add otp attempts counter

Revision ID: a1b2c3d4e5f6
Revises: 25348828110f
Create Date: 2026-07-01 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | Sequence[str] | None = '25348828110f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default='0' — so existing rows get a value without violating NOT NULL.
    op.add_column(
        'otprequest',
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('otprequest', 'attempts')
