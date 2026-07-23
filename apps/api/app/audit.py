from __future__ import annotations

import secrets
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .config import get_settings
from .schemas import (
    InternalAIRunOut,
    InternalEventOut,
    InternalQuestionOut,
    InternalResponseOut,
    InternalSessionOut,
    InternalSnapshotOut,
    InternalTimelineEntry,
)
from .service import mark_abandoned_if_stale


def require_internal_audit_token(request: Request) -> None:
    configured = get_settings().internal_audit_token
    supplied = request.headers.get("X-Internal-Audit-Token", "")
    if not configured or not supplied or not secrets.compare_digest(supplied, configured):
        raise HTTPException(status_code=401, detail="Internal audit access is not authorized")


def _dimension_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            changed[key] = {"before": before.get(key), "after": after.get(key)}
    return changed


def snapshot_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_dimensions = before.get("dimensions", {}) if isinstance(before, dict) else {}
    after_dimensions = after.get("dimensions", {}) if isinstance(after, dict) else {}
    dimensions: dict[str, Any] = {}
    confidence_changes: dict[str, Any] = {}
    for dimension in sorted(set(before_dimensions) | set(after_dimensions)):
        prior = before_dimensions.get(dimension, {})
        current = after_dimensions.get(dimension, {})
        changed = _dimension_diff(prior, current)
        if changed:
            dimensions[dimension] = changed
        if prior.get("confidence") != current.get("confidence"):
            confidence_changes[dimension] = {
                "before": prior.get("confidence"),
                "after": current.get("confidence"),
            }
    return {"dimensions": dimensions, "confidence_changes": confidence_changes}


def _timeline_entry(occurred_at: datetime, kind: str, label: str, **details: Any) -> InternalTimelineEntry:
    return InternalTimelineEntry(occurred_at=occurred_at, kind=kind, label=label, details=details)


def _sorted_timeline(entries: Iterable[InternalTimelineEntry]) -> list[InternalTimelineEntry]:
    return sorted(entries, key=lambda item: (item.occurred_at, item.kind, item.label))


def get_internal_session(db: Session, session_id: UUID) -> InternalSessionOut:
    session = db.get(models.QuestionnaireSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Questionnaire session not found")
    if mark_abandoned_if_stale(db, session):
        db.commit()

    questions = list(db.scalars(
        select(models.SessionQuestion)
        .where(models.SessionQuestion.session_id == session.id)
        .order_by(models.SessionQuestion.question_order)
    ))
    responses = list(db.scalars(
        select(models.QuestionnaireResponse)
        .where(models.QuestionnaireResponse.session_id == session.id)
        .order_by(models.QuestionnaireResponse.submitted_at)
    ))
    snapshots = list(db.scalars(
        select(models.ProfileSnapshot)
        .where(models.ProfileSnapshot.session_id == session.id)
        .order_by(models.ProfileSnapshot.version)
    ))
    ai_runs = list(db.scalars(
        select(models.AIRun)
        .where(models.AIRun.session_id == session.id)
        .order_by(models.AIRun.created_at, models.AIRun.attempt)
    ))
    events = list(db.scalars(
        select(models.AnalyticsEvent)
        .where(models.AnalyticsEvent.session_id == session.id)
        .order_by(models.AnalyticsEvent.occurred_at)
    ))

    response_by_question = {item.session_question_id: item for item in responses}
    previous_profile: dict[str, Any] = {}
    snapshot_outputs: list[InternalSnapshotOut] = []
    timeline: list[InternalTimelineEntry] = []

    for question in questions:
        response = response_by_question.get(question.id)
        timeline.append(_timeline_entry(
            question.displayed_at,
            "question",
            f"Question {question.question_order} displayed",
            question_id=str(question.id),
            source_question_id=question.question_id,
            question_type=question.question_type,
            target_dimension=question.primary_dimension,
            selection_reason=question.selection_reason,
            source=question.source,
            adaptive_metadata=question.adaptive_metadata_json,
        ))
        if response is not None:
            timeline.append(_timeline_entry(
                response.submitted_at,
                "response",
                f"Answer submitted for question {question.question_order}",
                response_id=str(response.id),
                question_id=str(question.id),
                validation_status=response.validation_status,
                response_time_seconds=question.response_time_seconds,
            ))

    for snapshot in snapshots:
        diff = snapshot_diff(previous_profile, snapshot.profile_json)
        snapshot_outputs.append(InternalSnapshotOut(
            version=snapshot.version,
            triggering_response_id=snapshot.triggering_response_id,
            profile=snapshot.profile_json,
            coverage=snapshot.coverage_json,
            confidence=snapshot.confidence_json,
            missing_information=snapshot.missing_information_json,
            diff=diff,
            created_at=snapshot.created_at,
        ))
        timeline.append(_timeline_entry(
            snapshot.created_at,
            "snapshot",
            f"Profile snapshot v{snapshot.version} created",
            version=snapshot.version,
            triggering_response_id=str(snapshot.triggering_response_id),
            changed_dimensions=sorted(diff["dimensions"]),
            confidence_changes=diff["confidence_changes"],
        ))
        previous_profile = snapshot.profile_json

    for run in ai_runs:
        timeline.append(_timeline_entry(
            run.created_at,
            "ai_run",
            f"{run.operation_type} {'succeeded' if run.success else 'failed'}",
            run_id=str(run.id),
            operation=run.operation_type,
            provider=run.model_name,
            attempt=run.attempt,
            latency_ms=run.latency_ms,
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            fallback_used=run.fallback_used,
            error_category=run.error_category,
        ))

    for event in events:
        timeline.append(_timeline_entry(
            event.occurred_at,
            "event",
            event.event_name,
            event_id=str(event.id),
            properties=event.event_properties_json,
        ))

    return InternalSessionOut(
        session_id=session.id,
        status=session.status,
        started_at=session.started_at,
        last_activity_at=session.last_activity_at,
        completed_at=session.completed_at,
        abandoned=session.abandoned,
        error_occurred=session.error_occurred,
        completion_reason=session.completion_reason,
        session_duration_seconds=session.session_duration_seconds,
        questionnaire_version=session.questionnaire_version,
        profile_schema_version=session.profile_schema_version,
        timeline=_sorted_timeline(timeline),
        questions=[InternalQuestionOut(
            id=item.id,
            order=item.question_order,
            source_question_id=item.question_id,
            text=item.exact_question_text,
            question_type=item.question_type,
            primary_dimension=item.primary_dimension,
            secondary_dimensions=item.secondary_dimensions,
            options=item.options_json,
            scale_min=item.scale_min,
            scale_max=item.scale_max,
            selection_reason=item.selection_reason,
            source=item.source,
            displayed_at=item.displayed_at,
            answered_at=item.answered_at,
            response_time_seconds=item.response_time_seconds,
            confidence_before=item.confidence_before_json,
            confidence_after=item.confidence_after_json,
            adaptive_metadata=item.adaptive_metadata_json,
        ) for item in questions],
        responses=[InternalResponseOut(
            id=item.id,
            session_question_id=item.session_question_id,
            raw_response=item.raw_response,
            normalized_response=item.normalized_response,
            sanitized_model_input=item.sanitized_model_input,
            extracted_information=item.extracted_information_json,
            validation_status=item.validation_status,
            submitted_at=item.submitted_at,
        ) for item in responses],
        snapshots=snapshot_outputs,
        ai_runs=[InternalAIRunOut(
            id=item.id,
            triggering_response_id=item.triggering_response_id,
            operation=item.operation_type,
            prompt_version=item.prompt_version,
            model=item.model_name,
            attempt=item.attempt,
            status=item.status,
            input=item.input_json,
            output=item.output_json,
            latency_ms=item.latency_ms,
            input_tokens=item.input_tokens,
            output_tokens=item.output_tokens,
            estimated_cost=item.estimated_cost,
            success=item.success,
            error_category=item.error_category,
            fallback_used=item.fallback_used,
            created_at=item.created_at,
            completed_at=item.completed_at,
        ) for item in ai_runs],
        events=[InternalEventOut(
            id=item.id,
            event_name=item.event_name,
            properties=item.event_properties_json,
            occurred_at=item.occurred_at,
        ) for item in events],
        final_profile=session.final_profile_json,
        final_summary=session.final_summary,
        final_analysis=session.final_analysis_json,
    )
