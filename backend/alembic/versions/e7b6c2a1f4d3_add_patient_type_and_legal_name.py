"""Add patient type and legal name

Revision ID: e7b6c2a1f4d3
Revises: c1f3e4a0d5b2
Create Date: 2026-03-28 11:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7b6c2a1f4d3"
down_revision: Union[str, Sequence[str], None] = "c1f3e4a0d5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("legal_name", sa.String(length=100), nullable=True))
    op.add_column(
        "patients",
        sa.Column("patient_type", sa.String(length=20), server_default="human", nullable=False),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE patients
            SET patient_type = CASE
                WHEN relation_type = 'pet' OR patient_code LIKE 'pet%' THEN 'pet'
                ELSE 'human'
            END
            """
        )
    )


def downgrade() -> None:
    op.drop_column("patients", "patient_type")
    op.drop_column("patients", "legal_name")
