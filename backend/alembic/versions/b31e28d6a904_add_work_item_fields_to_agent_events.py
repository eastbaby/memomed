"""add_work_item_fields_to_agent_events

Revision ID: b31e28d6a904
Revises: 9f2a7c1d4b83
Create Date: 2026-05-17 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b31e28d6a904"
down_revision: Union[str, Sequence[str], None] = "9f2a7c1d4b83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mm_agent_events", sa.Column("turn_id", sa.String(length=100), nullable=True))
    op.add_column("mm_agent_events", sa.Column("work_item_id", sa.String(length=100), nullable=True))
    op.add_column("mm_agent_events", sa.Column("work_item_type", sa.String(length=60), nullable=True))
    op.create_index("idx_mm_agent_events_turn_id", "mm_agent_events", ["turn_id"], unique=False)
    op.create_index("idx_mm_agent_events_work_item_id", "mm_agent_events", ["work_item_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_mm_agent_events_work_item_id", table_name="mm_agent_events")
    op.drop_index("idx_mm_agent_events_turn_id", table_name="mm_agent_events")
    op.drop_column("mm_agent_events", "work_item_type")
    op.drop_column("mm_agent_events", "work_item_id")
    op.drop_column("mm_agent_events", "turn_id")
