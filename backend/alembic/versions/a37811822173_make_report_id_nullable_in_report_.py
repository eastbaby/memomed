"""Make report_id nullable in report_chunks table

Revision ID: a37811822173
Revises: 2ccc2d34255b
Create Date: 2026-03-24 14:24:10.725457

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a37811822173'
down_revision: Union[str, Sequence[str], None] = '2ccc2d34255b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('report_chunks', 'report_id',
               existing_type=sa.UUID(),
               nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('report_chunks', 'report_id',
               existing_type=sa.UUID(),
               nullable=False)
