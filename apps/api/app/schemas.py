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
    target_maximum: int = 10
    maximum: int = 12


class SessionOut(StrictModel):
    session_id: UUID
    status: Literal["active", "processing", "needs_retry", "complete", "abandoned"]
    progress: ProgressOut
    current_question: QuestionOut | None
    final_profile: dict[str, Any] | None = None
    final_summary: str | None = None


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


class HealthOut(StrictModel):
    status: Literal["ok", "degraded"]
    database: Literal["connected", "unavailable"]


class ErrorOut(StrictModel):
    detail: str


class InternalSnapshotOut(StrictModel):
    version: int
    triggering_response_id: UUID
    profile: dict[str, Any]
    created_at: datetime
