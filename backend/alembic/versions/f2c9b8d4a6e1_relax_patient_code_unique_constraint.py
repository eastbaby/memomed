"""Relax patient_code unique constraint

Revision ID: f2c9b8d4a6e1
Revises: e7b6c2a1f4d3
Create Date: 2026-03-28 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f2c9b8d4a6e1"
down_revision: Union[str, Sequence[str], None] = "e7b6c2a1f4d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("patients_patient_code_key", "patients", type_="unique")
    op.create_index("ix_patients_patient_code", "patients", ["patient_code"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_patients_patient_code", table_name="patients")
    op.create_unique_constraint("patients_patient_code_key", "patients", ["patient_code"])
