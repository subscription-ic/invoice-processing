"""Initial schema — create all tables

Revision ID: 001_initial
Revises:
Create Date: 2026-06-02
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Import Base here to get all models registered
    from app.core.base import Base
    import app.models.models  # noqa: F401 — registers all models on Base
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from app.core.base import Base
    import app.models.models  # noqa: F401
    Base.metadata.drop_all(bind=op.get_bind())