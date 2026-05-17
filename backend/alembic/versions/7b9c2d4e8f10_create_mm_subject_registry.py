"""create_mm_subject_registry

Revision ID: 7b9c2d4e8f10
Revises: 1d66cfee37bc
Create Date: 2026-05-14 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "7b9c2d4e8f10"
down_revision: Union[str, Sequence[str], None] = "1d66cfee37bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mm_care_subjects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), server_default="default", nullable=False),
        sa.Column("subject_type", sa.String(length=20), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("legal_name", sa.String(length=100), nullable=True),
        sa.Column("relation_type", sa.String(length=30), nullable=True),
        sa.Column("species", sa.String(length=30), nullable=True),
        sa.Column("breed", sa.String(length=100), nullable=True),
        sa.Column("gender", sa.String(length=20), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("subject_type in ('human', 'pet')", name="ck_mm_care_subjects_subject_type"),
        sa.CheckConstraint("status in ('active', 'archived')", name="ck_mm_care_subjects_status"),
    )
    op.create_index(
        "idx_mm_care_subjects_owner_status",
        "mm_care_subjects",
        ["owner_user_id", "status"],
        unique=False,
    )
    op.create_index("idx_mm_care_subjects_type", "mm_care_subjects", ["subject_type"], unique=False)

    op.create_table(
        "mm_care_subject_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), server_default="default", nullable=False),
        sa.Column("alias", sa.String(length=100), nullable=False),
        sa.Column("normalized_alias", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=20), server_default="user", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("source in ('user', 'ai', 'system')", name="ck_mm_care_subject_aliases_source"),
        sa.CheckConstraint("status in ('active', 'archived')", name="ck_mm_care_subject_aliases_status"),
        sa.ForeignKeyConstraint(["subject_id"], ["mm_care_subjects.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_mm_care_subject_aliases_subject_id",
        "mm_care_subject_aliases",
        ["subject_id"],
        unique=False,
    )
    op.create_index(
        "idx_mm_care_subject_aliases_normalized_alias",
        "mm_care_subject_aliases",
        ["normalized_alias"],
        unique=False,
    )
    op.create_index(
        "uq_mm_care_subject_aliases_subject_alias",
        "mm_care_subject_aliases",
        ["subject_id", "normalized_alias"],
        unique=True,
    )
    op.create_index(
        "uq_mm_care_subject_aliases_owner_active_alias",
        "mm_care_subject_aliases",
        ["owner_user_id", "normalized_alias"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_mm_care_subject_aliases_owner_active_alias", table_name="mm_care_subject_aliases")
    op.drop_index("uq_mm_care_subject_aliases_subject_alias", table_name="mm_care_subject_aliases")
    op.drop_index("idx_mm_care_subject_aliases_normalized_alias", table_name="mm_care_subject_aliases")
    op.drop_index("idx_mm_care_subject_aliases_subject_id", table_name="mm_care_subject_aliases")
    op.drop_table("mm_care_subject_aliases")
    op.drop_index("idx_mm_care_subjects_type", table_name="mm_care_subjects")
    op.drop_index("idx_mm_care_subjects_owner_status", table_name="mm_care_subjects")
    op.drop_table("mm_care_subjects")
