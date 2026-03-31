"""add_patient_name_to_patients

Revision ID: 1d66cfee37bc
Revises: f2c9b8d4a6e1
Create Date: 2026-03-31 11:39:23.987981

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '1d66cfee37bc'
down_revision: Union[str, Sequence[str], None] = 'f2c9b8d4a6e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 添加 patient_name 列（真实姓名/宠物名，用于报告归属匹配）
    op.add_column('patients', sa.Column('patient_name', sa.String(length=100), nullable=True))

    # 删除已废弃的旧列
    op.drop_column('patients', 'relation_type')
    op.drop_column('patients', 'legal_name')
    op.drop_column('report_chunks', 'chunk_index_legacy')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('patients', 'patient_name')
    op.add_column('report_chunks', sa.Column('chunk_index_legacy', sa.INTEGER(), nullable=True))
    op.add_column('patients', sa.Column('legal_name', sa.VARCHAR(length=100), nullable=True))
    op.add_column('patients', sa.Column('relation_type', sa.VARCHAR(length=50), nullable=True))
