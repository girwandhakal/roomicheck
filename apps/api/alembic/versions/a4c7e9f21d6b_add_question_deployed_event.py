"""Add question deployment analytics events.

Revision ID: a4c7e9f21d6b
Revises: f5b9d2e8c741
Create Date: 2026-07-11 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a4c7e9f21d6b"
down_revision: Union[str, Sequence[str], None] = "f5b9d2e8c741"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_analytics_events_name", "analytics_events", type_="check")
    op.create_check_constraint(
        "ck_analytics_events_name",
        "analytics_events",
        "event_name IN ('questionnaire_opened', 'session_started', 'seed_started', "
        "'seed_submitted', 'question_displayed', 'answer_submitted', 'answer_edited', "
        "'back_clicked', 'session_abandoned', 'questionnaire_completed', "
        "'final_profile_viewed', 'questionnaire_restarted', 'application_error_shown', "
        "'question_deployed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_analytics_events_name", "analytics_events", type_="check")
    op.create_check_constraint(
        "ck_analytics_events_name",
        "analytics_events",
        "event_name IN ('questionnaire_opened', 'session_started', 'seed_started', "
        "'seed_submitted', 'question_displayed', 'answer_submitted', 'answer_edited', "
        "'back_clicked', 'session_abandoned', 'questionnaire_completed', "
        "'final_profile_viewed', 'questionnaire_restarted', 'application_error_shown')",
    )
