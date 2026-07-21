from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class QuestionnaireSession(TimestampMixin, Base):
    __tablename__ = "questionnaire_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'processing', 'needs_retry', 'complete', 'abandoned')",
            name="ck_questionnaire_sessions_status",
        ),
        CheckConstraint("total_questions BETWEEN 0 AND 25", name="ck_session_question_count"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    anonymous_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), default=uuid4, index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    questionnaire_version: Mapped[str] = mapped_column(String(64))
    profile_schema_version: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64), default="mock.v1")
    model_version: Mapped[str] = mapped_column(String(128), default="mock")
    completion_reason: Mapped[str | None] = mapped_column(String(32))
    final_profile_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    final_summary: Mapped[str | None] = mapped_column(Text)
    final_analysis_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    session_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    error_occurred: Mapped[bool] = mapped_column(Boolean, default=False)
    abandoned: Mapped[bool] = mapped_column(Boolean, default=False)


class QuestionBankItem(Base):
    __tablename__ = "question_bank"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    question_version: Mapped[str] = mapped_column(String(32))
    questionnaire_version: Mapped[str] = mapped_column(String(64), index=True)
    primary_dimension: Mapped[str | None] = mapped_column(String(64), index=True)
    secondary_dimensions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    question_type: Mapped[str] = mapped_column(String(32))
    question_text: Mapped[str] = mapped_column(Text)
    options_json: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    scale_min: Mapped[int | None] = mapped_column(Integer)
    scale_max: Mapped[int | None] = mapped_column(Integer)
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SessionQuestion(Base):
    __tablename__ = "session_questions"
    __table_args__ = (
        UniqueConstraint("session_id", "question_order", name="uq_session_question_order"),
        Index(
            "uq_session_current_question",
            "session_id",
            unique=True,
            postgresql_where=text("answered_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("questionnaire_sessions.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("question_bank.id"), index=True
    )
    question_order: Mapped[int] = mapped_column(Integer)
    exact_question_text: Mapped[str] = mapped_column(Text)
    question_type: Mapped[str] = mapped_column(String(32))
    primary_dimension: Mapped[str | None] = mapped_column(String(64))
    secondary_dimensions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    options_json: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    scale_min: Mapped[int | None] = mapped_column(Integer)
    scale_max: Mapped[int | None] = mapped_column(Integer)
    selection_reason: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="bank")
    displayed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_time_seconds: Mapped[float | None] = mapped_column(Float)
    confidence_before_json: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)
    confidence_after_json: Mapped[dict[str, float] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class QuestionnaireResponse(Base):
    __tablename__ = "questionnaire_responses"
    __table_args__ = (
        UniqueConstraint("session_id", "idempotency_key", name="uq_response_idempotency"),
        UniqueConstraint("session_question_id", name="uq_response_session_question"),
        CheckConstraint(
            "validation_status IN ('pending', 'valid', 'invalid', 'needs_retry')",
            name="ck_response_validation_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("questionnaire_sessions.id", ondelete="CASCADE"), index=True
    )
    session_question_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("session_questions.id", ondelete="CASCADE")
    )
    idempotency_key: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    raw_response: Mapped[dict[str, Any]] = mapped_column(JSONB)
    normalized_response: Mapped[str] = mapped_column(Text)
    sanitized_model_input: Mapped[str] = mapped_column(Text)
    extracted_information_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_status: Mapped[str] = mapped_column(String(24), default="pending")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProfileSnapshot(Base):
    __tablename__ = "profile_snapshots"
    __table_args__ = (
        UniqueConstraint("session_id", "version", name="uq_profile_snapshot_version"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("questionnaire_sessions.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    triggering_response_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("questionnaire_responses.id", ondelete="CASCADE")
    )
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    coverage_json: Mapped[dict[str, str]] = mapped_column(JSONB)
    confidence_json: Mapped[dict[str, float]] = mapped_column(JSONB)
    missing_information_json: Mapped[dict[str, list[str]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AIRun(Base):
    __tablename__ = "ai_runs"
    __table_args__ = (
        CheckConstraint("attempt >= 1", name="ck_ai_runs_attempt"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("questionnaire_sessions.id", ondelete="CASCADE"), index=True
    )
    triggering_response_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("questionnaire_responses.id", ondelete="SET NULL")
    )
    operation_type: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(128))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32))
    input_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error_category: Mapped[str | None] = mapped_column(String(64))
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    __table_args__ = (
        CheckConstraint(
            "event_name IN ('questionnaire_opened', 'session_started', 'seed_started', "
            "'seed_submitted', 'question_displayed', 'answer_submitted', 'answer_edited', "
            "'back_clicked', 'session_abandoned', 'questionnaire_completed', "
            "'final_profile_viewed', 'questionnaire_restarted', 'application_error_shown', "
            "'question_deployed')",
            name="ck_analytics_events_name",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("questionnaire_sessions.id", ondelete="CASCADE"), index=True
    )
    event_name: Mapped[str] = mapped_column(String(64), index=True)
    event_properties_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
