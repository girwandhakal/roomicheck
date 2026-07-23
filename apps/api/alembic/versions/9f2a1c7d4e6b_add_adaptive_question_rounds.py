"""Persist adaptive hypothesis bundles and generated-question metadata.

Revision ID: 9f2a1c7d4e6b
Revises: 8d7c1f2a4b6e
Create Date: 2026-07-22 21:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "9f2a1c7d4e6b"
down_revision: Union[str, Sequence[str], None] = "8d7c1f2a4b6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "questionnaire_sessions",
        sa.Column("adaptive_round", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "questionnaire_sessions",
        sa.Column("active_adaptive_bundle_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "session_questions",
        sa.Column("adaptive_metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.alter_column("questionnaire_sessions", "adaptive_round", server_default=None)


def downgrade() -> None:
    op.drop_column("session_questions", "adaptive_metadata_json")
    op.drop_column("questionnaire_sessions", "active_adaptive_bundle_json")
    op.drop_column("questionnaire_sessions", "adaptive_round")
