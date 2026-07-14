"""Allow the detailed questionnaire to reach 25 questions.

Revision ID: c82b1e4d6f90
Revises: a4c7e9f21d6b
Create Date: 2026-07-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c82b1e4d6f90"
down_revision: Union[str, Sequence[str], None] = "a4c7e9f21d6b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_session_question_count", "questionnaire_sessions", type_="check")
    op.create_check_constraint(
        "ck_session_question_count",
        "questionnaire_sessions",
        "total_questions BETWEEN 0 AND 25",
    )


def downgrade() -> None:
    op.drop_constraint("ck_session_question_count", "questionnaire_sessions", type_="check")
    op.create_check_constraint(
        "ck_session_question_count",
        "questionnaire_sessions",
        "total_questions BETWEEN 0 AND 12",
    )
