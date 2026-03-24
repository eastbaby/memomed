"""Update embedding column to use Vector(1024)

Revision ID: 2ccc2d34255b
Revises: ad1d38f25555
Create Date: 2026-03-24 14:18:13.789452

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = '2ccc2d34255b'
down_revision: Union[str, Sequence[str], None] = 'ad1d38f25555'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 删除旧的embedding列并重新创建
    op.drop_column('report_chunks', 'embedding')
    op.add_column('report_chunks', sa.Column('embedding', Vector(1024), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # 删除embedding列并重新创建1536维
    op.drop_column('report_chunks', 'embedding')
    op.add_column('report_chunks', sa.Column('embedding', Vector(1536), nullable=True))
