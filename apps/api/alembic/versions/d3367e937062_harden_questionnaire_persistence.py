"""Harden Stage 1 questionnaire persistence.

Revision ID: d3367e937062
Revises: b071e92464b2
Create Date: 2026-07-10 16:39:20.324779
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd3367e937062'
down_revision: Union[str, Sequence[str], None] = 'b071e92464b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_session_current_question",
        "session_questions",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("answered_at IS NULL"),
    )
    op.create_check_constraint(
        "ck_analytics_events_name",
        "analytics_events",
        "event_name IN ('questionnaire_opened', 'session_started', 'seed_started', "
        "'seed_submitted', 'question_displayed', 'answer_submitted', 'answer_edited', "
        "'back_clicked', 'session_abandoned', 'questionnaire_completed', "
        "'final_profile_viewed', 'questionnaire_restarted', 'application_error_shown')",
    )
    for table in (
        "question_bank",
        "questionnaire_sessions",
        "session_questions",
        "questionnaire_responses",
        "profile_snapshots",
        "ai_runs",
        "analytics_events",
    ):
        op.execute(f'REVOKE ALL ON TABLE "{table}" FROM anon, authenticated')
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    for table in (
        "analytics_events",
        "ai_runs",
        "profile_snapshots",
        "questionnaire_responses",
        "session_questions",
        "questionnaire_sessions",
        "question_bank",
    ):
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.drop_constraint("ck_analytics_events_name", "analytics_events", type_="check")
    op.drop_index("uq_session_current_question", table_name="session_questions")
