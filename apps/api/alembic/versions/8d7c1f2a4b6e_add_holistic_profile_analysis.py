"""Store structured whole-profile analysis.

Revision ID: 8d7c1f2a4b6e
Revises: f5b9d2e8c741, c82b1e4d6f90
Create Date: 2026-07-19 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "8d7c1f2a4b6e"
down_revision: Union[str, Sequence[str], None] = ("f5b9d2e8c741", "c82b1e4d6f90")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "questionnaire_sessions",
        sa.Column("final_analysis_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("questionnaire_sessions", "final_analysis_json")
