from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionOptionOut(StrictModel):
    id: str
    label: str


class QuestionOut(StrictModel):
    id: UUID
    source_question_id: str
    order: int
    text: str
    question_type: Literal["free_text", "scenario", "scale", "single_choice"]
    primary_dimension: str | None
    options: list[QuestionOptionOut]
    scale_min: int | None
    scale_max: int | None


class ProgressOut(StrictModel):
    answered: int
    minimum: int = 6
    target_minimum: int = 7
    target_maximum: int = 25
    maximum: int = 25


class SessionOut(StrictModel):
    session_id: UUID
    status: Literal["active", "processing", "needs_retry", "complete", "abandoned"]
    progress: ProgressOut
    current_question: QuestionOut | None
    final_profile: dict[str, Any] | None = None
    final_summary: str | None = None
    final_analysis: dict[str, Any] | None = None


class AnswerValue(StrictModel):
    free_text: str | None = Field(default=None, max_length=4000)
    scale_value: int | None = Field(default=None, ge=1, le=5)
    selected_option_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def exactly_one_value(self) -> AnswerValue:
        if self.selected_option_id == "other":
            if self.free_text is None or not self.free_text.strip() or self.scale_value is not None:
                raise ValueError("The Other option requires a written response")
            return self
        values = [
            self.free_text is not None and bool(self.free_text.strip()),
            self.scale_value is not None,
            self.selected_option_id is not None and bool(self.selected_option_id.strip()),
        ]
        if sum(values) != 1 or (self.free_text is not None and self.selected_option_id is not None):
            raise ValueError("Exactly one non-empty answer value is required")
        return self


class AnswerSubmission(StrictModel):
    session_question_id: UUID
    idempotency_key: UUID
    answer: AnswerValue


class QuestionDeployedSubmission(StrictModel):
    session_question_id: UUID


ClientEventName = Literal[
    "questionnaire_opened",
    "question_displayed",
    "answer_edited",
    "back_clicked",
    "final_profile_viewed",
    "application_error_shown",
]


class AnalyticsEventSubmission(StrictModel):
    event_name: ClientEventName
    properties: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=12)


class InternalTimelineEntry(StrictModel):
    occurred_at: datetime
    kind: str
    label: str
    details: dict[str, Any] = Field(default_factory=dict)


class InternalQuestionOut(StrictModel):
    id: UUID
    order: int
    source_question_id: str
    text: str
    question_type: str
    primary_dimension: str | None
    secondary_dimensions: list[str]
    options: list[dict[str, str]]
    scale_min: int | None
    scale_max: int | None
    selection_reason: str
    source: str
    displayed_at: datetime
    answered_at: datetime | None
    response_time_seconds: float | None
    confidence_before: dict[str, float]
    confidence_after: dict[str, float] | None
    adaptive_metadata: dict[str, Any] | None


class InternalResponseOut(StrictModel):
    id: UUID
    session_question_id: UUID
    raw_response: dict[str, Any]
    normalized_response: str
    sanitized_model_input: str
    extracted_information: dict[str, Any] | None
    validation_status: str
    submitted_at: datetime


class InternalSnapshotOut(StrictModel):
    version: int
    triggering_response_id: UUID
    profile: dict[str, Any]
    coverage: dict[str, str]
    confidence: dict[str, float]
    missing_information: dict[str, list[str]]
    diff: dict[str, Any]
    created_at: datetime


class InternalAIRunOut(StrictModel):
    id: UUID
    triggering_response_id: UUID | None
    operation: str
    prompt_version: str
    model: str
    attempt: int
    status: str
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost: float | None
    success: bool
    error_category: str | None
    fallback_used: bool
    created_at: datetime
    completed_at: datetime | None


class InternalEventOut(StrictModel):
    id: UUID
    event_name: str
    properties: dict[str, Any]
    occurred_at: datetime


class InternalSessionOut(StrictModel):
    session_id: UUID
    status: str
    started_at: datetime
    last_activity_at: datetime
    completed_at: datetime | None
    abandoned: bool
    error_occurred: bool
    completion_reason: str | None
    session_duration_seconds: int | None
    questionnaire_version: str
    profile_schema_version: str
    timeline: list[InternalTimelineEntry]
    questions: list[InternalQuestionOut]
    responses: list[InternalResponseOut]
    snapshots: list[InternalSnapshotOut]
    ai_runs: list[InternalAIRunOut]
    events: list[InternalEventOut]
    final_profile: dict[str, Any] | None
    final_summary: str | None
    final_analysis: dict[str, Any] | None


class HealthOut(StrictModel):
    status: Literal["ok", "degraded"]
    database: Literal["connected", "unavailable"]

class ErrorOut(StrictModel):
    detail: str
