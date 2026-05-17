"""create_mm_agent_event_store

Revision ID: 9f2a7c1d4b83
Revises: 7b9c2d4e8f10
Create Date: 2026-05-17 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "9f2a7c1d4b83"
down_revision: Union[str, Sequence[str], None] = "7b9c2d4e8f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mm_agent_conversations",
        sa.Column("id", sa.String(length=100), primary_key=True, nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), server_default="default", nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("langgraph_thread_id", sa.String(length=100), nullable=False),
        sa.Column("last_event_seq", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status in ('active', 'archived')", name="ck_mm_agent_conversations_status"),
    )
    op.create_index(
        "idx_mm_agent_conversations_owner_status",
        "mm_agent_conversations",
        ["owner_user_id", "status"],
        unique=False,
    )
    op.create_index(
        "idx_mm_agent_conversations_updated_at",
        "mm_agent_conversations",
        ["updated_at"],
        unique=False,
    )

    op.create_table(
        "mm_agent_runs",
        sa.Column("id", sa.String(length=100), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=100), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), server_default="default", nullable=False),
        sa.Column("trigger_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="running", nullable=False),
        sa.Column("langgraph_run_id", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.CheckConstraint(
            "trigger_type in ('user_message', 'resume_interrupt', 'background_job')",
            name="ck_mm_agent_runs_trigger_type",
        ),
        sa.CheckConstraint(
            "status in ('running', 'completed', 'interrupted', 'failed', 'cancelled')",
            name="ck_mm_agent_runs_status",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["mm_agent_conversations.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_mm_agent_runs_conversation_started",
        "mm_agent_runs",
        ["conversation_id", "started_at"],
        unique=False,
    )
    op.create_index("idx_mm_agent_runs_owner_status", "mm_agent_runs", ["owner_user_id", "status"], unique=False)

    op.create_table(
        "mm_agent_events",
        sa.Column("id", sa.String(length=100), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=100), nullable=False),
        sa.Column("run_id", sa.String(length=100), nullable=True),
        sa.Column("owner_user_id", sa.String(length=64), server_default="default", nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=True),
        sa.Column("visibility", sa.String(length=20), server_default="visible", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="completed", nullable=False),
        sa.Column("parent_event_id", sa.String(length=100), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "role is null or role in ('user', 'assistant', 'tool', 'system')",
            name="ck_mm_agent_events_role",
        ),
        sa.CheckConstraint(
            "visibility in ('visible', 'collapsed', 'debug', 'hidden')",
            name="ck_mm_agent_events_visibility",
        ),
        sa.CheckConstraint(
            "status in ('pending', 'streaming', 'completed', 'failed')",
            name="ck_mm_agent_events_status",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["mm_agent_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["mm_agent_runs.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "idx_mm_agent_events_conversation_seq",
        "mm_agent_events",
        ["conversation_id", "seq"],
        unique=True,
    )
    op.create_index("idx_mm_agent_events_run_id", "mm_agent_events", ["run_id"], unique=False)
    op.create_index(
        "idx_mm_agent_events_owner_conversation",
        "mm_agent_events",
        ["owner_user_id", "conversation_id"],
        unique=False,
    )
    op.create_index(
        "uq_mm_agent_events_run_dedupe_key",
        "mm_agent_events",
        ["run_id", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key is not null"),
    )


def downgrade() -> None:
    op.drop_index("uq_mm_agent_events_run_dedupe_key", table_name="mm_agent_events")
    op.drop_index("idx_mm_agent_events_owner_conversation", table_name="mm_agent_events")
    op.drop_index("idx_mm_agent_events_run_id", table_name="mm_agent_events")
    op.drop_index("idx_mm_agent_events_conversation_seq", table_name="mm_agent_events")
    op.drop_table("mm_agent_events")
    op.drop_index("idx_mm_agent_runs_owner_status", table_name="mm_agent_runs")
    op.drop_index("idx_mm_agent_runs_conversation_started", table_name="mm_agent_runs")
    op.drop_table("mm_agent_runs")
    op.drop_index("idx_mm_agent_conversations_updated_at", table_name="mm_agent_conversations")
    op.drop_index("idx_mm_agent_conversations_owner_status", table_name="mm_agent_conversations")
    op.drop_table("mm_agent_conversations")
