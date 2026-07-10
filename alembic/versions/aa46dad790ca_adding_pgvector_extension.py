"""adding pgvector extension

Revision ID: aa46dad790ca
Revises: f3e41f5a3c06
Create Date: 2026-07-10 09:57:43.437968

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import sqlmodel 

# revision identifiers, used by Alembic.
revision: str = 'aa46dad790ca'
down_revision: Union[str, Sequence[str], None] = 'f3e41f5a3c06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP EXTENSION IF EXISTS vector")
