"""Phase 1 add patients and report metadata

Revision ID: c1f3e4a0d5b2
Revises: a37811822173
Create Date: 2026-03-27 11:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c1f3e4a0d5b2"
down_revision: Union[str, Sequence[str], None] = "a37811822173"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "patients",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.String(length=50), nullable=True),
        sa.Column("patient_code", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("relation_type", sa.String(length=50), nullable=True),
        sa.Column("gender", sa.String(length=20), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("patient_code"),
    )
    op.create_index("ix_patients_owner_user_id", "patients", ["owner_user_id"], unique=False)

    op.add_column("medical_reports", sa.Column("patient_id_v2", sa.UUID(), nullable=True))
    op.add_column("medical_reports", sa.Column("source_type", sa.String(length=30), nullable=True))
    op.add_column("medical_reports", sa.Column("source_uri", sa.Text(), nullable=True))
    op.add_column("medical_reports", sa.Column("title", sa.String(length=255), nullable=True))
    op.add_column(
        "medical_reports",
        sa.Column("ocr_pages", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "medical_reports",
        sa.Column("parse_status", sa.String(length=30), server_default="pending", nullable=False),
    )
    op.add_column("medical_reports", sa.Column("parse_notes", sa.Text(), nullable=True))
    op.add_column(
        "medical_reports",
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "medical_reports",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.add_column("report_chunks", sa.Column("patient_id", sa.UUID(), nullable=True))
    op.add_column("report_chunks", sa.Column("report_date", sa.Date(), nullable=True))
    op.add_column("report_chunks", sa.Column("report_type", sa.String(length=50), nullable=True))
    op.add_column("report_chunks", sa.Column("hospital_name", sa.String(length=255), nullable=True))
    op.add_column("report_chunks", sa.Column("chunk_index", sa.Integer(), nullable=True))
    op.add_column(
        "report_chunks",
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "report_chunks",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.add_column(
        "report_chunks",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    bind = op.get_bind()

    bind.execute(
        sa.text(
            """
            INSERT INTO patients (id, patient_code, display_name, relation_type, created_at, updated_at)
            SELECT
                gen_random_uuid(),
                legacy.patient_code,
                legacy.display_name,
                legacy.relation_type,
                now(),
                now()
            FROM (
                SELECT DISTINCT
                    mr.patient_id AS patient_code,
                    CASE
                        WHEN mr.patient_id IN ('self', 'me', '本人', '我') THEN '我'
                        WHEN mr.patient_id IN ('mother', 'mom', '妈妈', '母亲') THEN '妈妈'
                        WHEN mr.patient_id IN ('father', 'dad', '爸爸', '父亲') THEN '爸爸'
                        ELSE mr.patient_id
                    END AS display_name,
                    CASE
                        WHEN mr.patient_id IN ('self', 'me', '本人', '我') THEN 'self'
                        WHEN mr.patient_id IN ('mother', 'mom', '妈妈', '母亲') THEN 'mother'
                        WHEN mr.patient_id IN ('father', 'dad', '爸爸', '父亲') THEN 'father'
                        ELSE 'other'
                    END AS relation_type
                FROM medical_reports mr
                WHERE mr.patient_id IS NOT NULL
            ) AS legacy
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE medical_reports mr
            SET patient_id_v2 = p.id
            FROM patients p
            WHERE mr.patient_id = p.patient_code
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE report_chunks rc
            SET patient_id = mr.patient_id_v2,
                report_date = mr.report_date,
                report_type = mr.report_type,
                hospital_name = mr.hospital_name,
                chunk_index = rc.index_in_report
            FROM medical_reports mr
            WHERE rc.report_id = mr.id
            """
        )
    )

    op.create_foreign_key(
        "fk_medical_reports_patient_id_patients",
        "medical_reports",
        "patients",
        ["patient_id_v2"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_report_chunks_patient_id_patients",
        "report_chunks",
        "patients",
        ["patient_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_medical_reports_patient_id_report_date",
        "medical_reports",
        ["patient_id_v2", "report_date"],
        unique=False,
    )
    op.create_index(
        "ix_medical_reports_patient_id_report_type",
        "medical_reports",
        ["patient_id_v2", "report_type"],
        unique=False,
    )
    op.create_index(
        "ix_report_chunks_patient_id_report_date",
        "report_chunks",
        ["patient_id", "report_date"],
        unique=False,
    )
    op.create_index("ix_report_chunks_report_type", "report_chunks", ["report_type"], unique=False)

    op.alter_column("medical_reports", "patient_id_v2", existing_type=sa.UUID(), nullable=False)
    op.drop_column("medical_reports", "patient_id")
    op.alter_column("medical_reports", "patient_id_v2", new_column_name="patient_id")
    op.drop_column("medical_reports", "file_path")
    op.alter_column("report_chunks", "index_in_report", new_column_name="chunk_index_legacy")


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("report_chunks", "chunk_index_legacy", new_column_name="index_in_report")

    op.add_column("medical_reports", sa.Column("file_path", sa.Text(), nullable=True))
    op.add_column("medical_reports", sa.Column("patient_id_legacy", sa.String(length=50), nullable=True))

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE medical_reports mr
            SET patient_id_legacy = p.patient_code
            FROM patients p
            WHERE mr.patient_id = p.id
            """
        )
    )

    op.drop_index("ix_report_chunks_report_type", table_name="report_chunks")
    op.drop_index("ix_report_chunks_patient_id_report_date", table_name="report_chunks")
    op.drop_index("ix_medical_reports_patient_id_report_type", table_name="medical_reports")
    op.drop_index("ix_medical_reports_patient_id_report_date", table_name="medical_reports")

    op.drop_constraint("fk_report_chunks_patient_id_patients", "report_chunks", type_="foreignkey")
    op.drop_constraint("fk_medical_reports_patient_id_patients", "medical_reports", type_="foreignkey")

    op.drop_column("report_chunks", "created_at")
    op.drop_column("report_chunks", "updated_at")
    op.drop_column("report_chunks", "metadata")
    op.drop_column("report_chunks", "chunk_index")
    op.drop_column("report_chunks", "hospital_name")
    op.drop_column("report_chunks", "report_type")
    op.drop_column("report_chunks", "report_date")
    op.drop_column("report_chunks", "patient_id")

    op.drop_column("medical_reports", "updated_at")
    op.drop_column("medical_reports", "metadata")
    op.drop_column("medical_reports", "parse_notes")
    op.drop_column("medical_reports", "parse_status")
    op.drop_column("medical_reports", "ocr_pages")
    op.drop_column("medical_reports", "title")
    op.drop_column("medical_reports", "source_uri")
    op.drop_column("medical_reports", "source_type")

    op.drop_column("medical_reports", "patient_id")
    op.alter_column("medical_reports", "patient_id_legacy", new_column_name="patient_id")
    op.alter_column("medical_reports", "patient_id", existing_type=sa.String(length=50), nullable=False)

    op.drop_index("ix_patients_owner_user_id", table_name="patients")
    op.drop_table("patients")
