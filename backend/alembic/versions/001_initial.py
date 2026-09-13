"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-09-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tables created via Base.metadata.create_all on startup for MVP;
    # this revision documents the baseline for Postgres deployments.
    pass


def downgrade() -> None:
    pass
