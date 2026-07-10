from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from roomicheck.privacy import PrivacyGuard
from roomicheck.v2.config import DIMENSION_IDS, PROFILE_SCHEMA_VERSION, QUESTIONNAIRE_VERSION
from roomicheck.v2.controller import AdaptiveController, CompletionReason
from roomicheck.v2.models import (
    CoverageStatus,
    DimensionState,
    EvidenceKind,
    EvidenceReference,
    ProfileStatus,
    ProfileV2,
)
from roomicheck.v2.questions import QuestionDefinition, load_question_bank

from . import models
from .schemas import AnswerSubmission, ProgressOut, QuestionOut, SessionOut


privacy = PrivacyGuard()
question_bank = load_question_bank()
controller = AdaptiveController(question_bank)

SEED_SIGNAL_PATTERNS = {
    "noise_environment": re.compile(r"\b(?:quiet|noise|music|calls?|light|temperature|sleep)\b", re.I),
    "social_interaction": re.compile(r"\b(?:social|friends?|hang out|alone|privacy|own space)\b", re.I),
    "study_daily_routine": re.compile(r"\b(?:study|work|schedule|routine|weekday|weekend|wake|sleep)\b", re.I),
    "cultural_openness": re.compile(r"\b(?:culture|cultural|language|tradition|different background|food)\b", re.I),
    "household_structure": re.compile(r"\b(?:clean|chores?|supplies|sharing|guests?|common area|rules?)\b", re.I),
    "communication_conflict": re.compile(r"\b(?:communicat|conflict|compromise|discuss|talk|problem)\w*\b", re.I),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def seed_question_bank(db: Session) -> None:
    for question in question_bank.questions:
        item = db.get(models.QuestionBankItem, question.id)
        values = {
            "question_version": question.version,
            "questionnaire_version": QUESTIONNAIRE_VERSION,
            "primary_dimension": question.primary_dimension,
            "secondary_dimensions": list(question.secondary_dimensions),
            "question_type": question.question_type.value,
            "question_text": question.prompt,
            "options_json": [{"id": item.id, "label": item.label} for item in question.options],
            "scale_min": question.scale_min,
            "scale_max": question.scale_max,
            "is_seed": question.is_seed,
            "active": question.active,
        }
        if item is None:
            db.add(models.QuestionBankItem(id=question.id, **values))
        else:
            for key, value in values.items():
                setattr(item, key, value)
    db.flush()


def _confidence_map(profile: ProfileV2) -> dict[str, float]:
    return {key: float(value.confidence) for key, value in profile.dimensions.items()}


def _present_question(
    db: Session,
    session: models.QuestionnaireSession,
    question: QuestionDefinition,
    profile: ProfileV2,
    reason: str,
) -> models.SessionQuestion:
    presented = models.SessionQuestion(
        session_id=session.id,
        question_id=question.id,
        question_order=session.total_questions + 1,
        exact_question_text=question.prompt,
        question_type=question.question_type.value,
        primary_dimension=question.primary_dimension,
        secondary_dimensions=list(question.secondary_dimensions),
        options_json=[{"id": item.id, "label": item.label} for item in question.options],
        scale_min=question.scale_min,
        scale_max=question.scale_max,
        selection_reason=reason,
        source="bank",
        confidence_before_json=_confidence_map(profile),
    )
    db.add(presented)
    db.flush()
    return presented


def _latest_profile(db: Session, session: models.QuestionnaireSession) -> ProfileV2:
    snapshot = db.scalar(
        select(models.ProfileSnapshot)
        .where(models.ProfileSnapshot.session_id == session.id)
        .order_by(models.ProfileSnapshot.version.desc())
        .limit(1)
    )
    return ProfileV2.from_dict(snapshot.profile_json) if snapshot else ProfileV2.empty(str(session.id))


def _current_question(db: Session, session_id: UUID) -> models.SessionQuestion | None:
    return db.scalar(
        select(models.SessionQuestion)
        .where(
            models.SessionQuestion.session_id == session_id,
            models.SessionQuestion.answered_at.is_(None),
        )
        .order_by(models.SessionQuestion.question_order.desc())
        .limit(1)
    )


def _question_out(question: models.SessionQuestion | None) -> QuestionOut | None:
    if question is None:
        return None
    return QuestionOut(
        id=question.id,
        source_question_id=question.question_id,
        order=question.question_order,
        text=question.exact_question_text,
        question_type=question.question_type,
        primary_dimension=question.primary_dimension,
        options=question.options_json,
        scale_min=question.scale_min,
        scale_max=question.scale_max,
    )


def public_session(db: Session, session: models.QuestionnaireSession) -> SessionOut:
    return SessionOut(
        session_id=session.id,
        status=session.status,
        progress=ProgressOut(answered=session.total_questions),
        current_question=_question_out(_current_question(db, session.id)),
        final_profile=session.final_profile_json if session.status == "complete" else None,
        final_summary=session.final_summary if session.status == "complete" else None,
    )


def create_session(db: Session) -> SessionOut:
    seed_question_bank(db)
    session = models.QuestionnaireSession(
        questionnaire_version=QUESTIONNAIRE_VERSION,
        profile_schema_version=PROFILE_SCHEMA_VERSION,
    )
    db.add(session)
    db.flush()
    profile = ProfileV2.empty(str(session.id))
    _present_question(db, session, question_bank.seed, profile, "required_seed")
    db.add(models.AnalyticsEvent(session_id=session.id, event_name="session_started"))
    db.commit()
    return public_session(db, session)


def get_session_or_404(db: Session, session_id: UUID) -> models.QuestionnaireSession:
    session = db.get(models.QuestionnaireSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Questionnaire session not found")
    return session


def get_public_session(db: Session, session_id: UUID) -> SessionOut:
    return public_session(db, get_session_or_404(db, session_id))


def _normalize_answer(question: models.SessionQuestion, submission: AnswerSubmission) -> str:
    answer = submission.answer
    if question.question_type in {"free_text", "scenario"}:
        if answer.free_text is None or not answer.free_text.strip():
            raise HTTPException(status_code=422, detail="This question requires a written response")
        return answer.free_text.strip()
    if question.question_type == "scale":
        if answer.scale_value is None:
            raise HTTPException(status_code=422, detail="This question requires a scale value")
        return str(answer.scale_value)
    if question.question_type == "single_choice":
        valid_ids = {item["id"] for item in question.options_json}
        if answer.selected_option_id not in valid_ids:
            raise HTTPException(status_code=422, detail="Select one of the available options")
        if answer.selected_option_id == "other":
            if answer.free_text is None or not answer.free_text.strip():
                raise HTTPException(status_code=422, detail="Describe your answer for Other")
            return answer.free_text.strip()
        return next(item["label"] for item in question.options_json if item["id"] == answer.selected_option_id)
    raise HTTPException(status_code=422, detail="Unsupported question type")


def _mock_extract(
    profile: ProfileV2,
    question: models.SessionQuestion,
    response_id: UUID,
    sanitized_text: str,
    ai_allowed: bool,
) -> dict[str, Any]:
    updated: list[str] = []
    if not ai_allowed:
        return {"dimensions_updated": updated, "withheld": True}
    if question.primary_dimension:
        targets = [question.primary_dimension]
    else:
        targets = [
            dimension for dimension, pattern in SEED_SIGNAL_PATTERNS.items() if pattern.search(sanitized_text)
        ]
    excerpt = sanitized_text[:500]
    for dimension in targets:
        prior = profile.dimensions[dimension]
        evidence = list(prior.evidence)
        evidence.append(EvidenceReference(str(response_id), EvidenceKind.DIRECT, excerpt))
        confidence = min(0.92, max(0.74, prior.confidence + 0.18))
        profile.dimensions[dimension] = DimensionState(
            score=50,
            label="Preference recorded; awaiting live interpretation",
            confidence=confidence,
            coverage=CoverageStatus.PARTIAL,
            summary="The response contains direct evidence for this co-living dimension.",
            evidence=evidence,
            unknowns=[],
            clarification_needed=False,
            preference_strength_known=question.question_type in {"scale", "single_choice"},
            scenario_evidence=question.question_type == "scenario",
        )
        updated.append(dimension)
    return {"dimensions_updated": updated, "withheld": False}


def _deterministic_summary(profile: ProfileV2) -> str:
    sufficient = sum(
        state.coverage == CoverageStatus.SUFFICIENT for state in profile.dimensions.values()
    )
    uncertain = len(DIMENSION_IDS) - sufficient
    if uncertain:
        return (
            f"RoomiCheck recorded evidence across the co-living profile. {sufficient} dimensions "
            f"have sufficient confidence and {uncertain} remain uncertain."
        )
    return (
        "RoomiCheck recorded direct evidence across all six co-living dimensions. "
        "Live AI interpretation will replace this Stage 1 development summary."
    )


def _selection_reason(profile: ProfileV2, dimension: str) -> str:
    state = profile.dimensions[dimension]
    if state.coverage == CoverageStatus.UNKNOWN:
        return f"unknown_dimension:{dimension}"
    if state.clarification_needed:
        return f"clarification_needed:{dimension}"
    return f"lowest_confidence:{dimension}"


def submit_answer(db: Session, session_id: UUID, submission: AnswerSubmission) -> SessionOut:
    replay = db.scalar(
        select(models.QuestionnaireResponse).where(
            models.QuestionnaireResponse.session_id == session_id,
            models.QuestionnaireResponse.idempotency_key == submission.idempotency_key,
        )
    )
    if replay is not None:
        return public_session(db, get_session_or_404(db, session_id))

    session = get_session_or_404(db, session_id)
    if session.status not in {"active", "needs_retry"}:
        raise HTTPException(status_code=409, detail="Session is not accepting answers")
    question = _current_question(db, session.id)
    if question is None or question.id != submission.session_question_id:
        raise HTTPException(status_code=409, detail="Answer does not target the current question")
    normalized = _normalize_answer(question, submission)
    sanitized = privacy.sanitize_answer(normalized)
    now = utc_now()
    response = models.QuestionnaireResponse(
        session_id=session.id,
        session_question_id=question.id,
        idempotency_key=submission.idempotency_key,
        raw_response=submission.answer.model_dump(mode="json"),
        normalized_response=normalized,
        sanitized_model_input=sanitized.text,
        validation_status="pending",
    )
    db.add(response)
    db.flush()

    session.status = "processing"
    profile = _latest_profile(db, session)
    profile.question_count = session.total_questions + 1
    extraction = _mock_extract(
        profile, question, response.id, sanitized.text, sanitized.ai_allowed
    )
    response.extracted_information_json = extraction
    response.validation_status = "valid"
    question.answered_at = now
    question.response_time_seconds = max(0.0, (now - question.displayed_at).total_seconds())
    session.total_questions = profile.question_count
    session.last_activity_at = now

    decision = controller.decide(profile)
    question.confidence_after_json = _confidence_map(profile)
    snapshot_version = db.scalar(
        select(func.count(models.ProfileSnapshot.id)).where(
            models.ProfileSnapshot.session_id == session.id
        )
    ) + 1
    db.add(
        models.ProfileSnapshot(
            session_id=session.id,
            version=snapshot_version,
            triggering_response_id=response.id,
            profile_json=profile.to_dict(),
            coverage_json={key: value.coverage.value for key, value in profile.dimensions.items()},
            confidence_json=_confidence_map(profile),
            missing_information_json={key: value.unknowns for key, value in profile.dimensions.items()},
        )
    )
    db.add(
        models.AIRun(
            session_id=session.id,
            triggering_response_id=response.id,
            operation_type="mock_extract_and_select",
            prompt_version="mock.v1",
            model_name="deterministic-mock",
            status="succeeded",
            output_json=extraction,
            success=True,
            fallback_used=True,
            completed_at=now,
        )
    )
    db.add(models.AnalyticsEvent(session_id=session.id, event_name="answer_submitted"))

    if decision.complete:
        profile.status = ProfileStatus.COMPLETE
        profile.written_summary = _deterministic_summary(profile)
        # Replace the snapshot payload after final completion fields are known.
        pending_snapshot = next(
            item for item in db.new if isinstance(item, models.ProfileSnapshot)
        )
        pending_snapshot.profile_json = profile.to_dict()
        session.status = "complete"
        session.completion_reason = decision.reason.value if decision.reason else None
        session.completed_at = now
        session.session_duration_seconds = max(0, int((now - session.started_at).total_seconds()))
        session.final_profile_json = profile.to_dict()
        session.final_summary = profile.written_summary
        db.add(models.AnalyticsEvent(session_id=session.id, event_name="questionnaire_completed"))
    else:
        session.status = "active"
        asked = set(
            db.scalars(
                select(models.SessionQuestion.question_id).where(
                    models.SessionQuestion.session_id == session.id
                )
            ).all()
        )
        next_question = question_bank.next_for_dimension(decision.next_dimension, asked)
        if next_question is None:
            db.rollback()
            raise HTTPException(status_code=503, detail="No safe fallback question is available")
        _present_question(
            db,
            session,
            next_question,
            profile,
            _selection_reason(profile, decision.next_dimension),
        )

    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="The answer was already submitted") from error
    return public_session(db, session)


def retry_session(db: Session, session_id: UUID) -> SessionOut:
    session = get_session_or_404(db, session_id)
    if session.status != "needs_retry":
        raise HTTPException(status_code=409, detail="Session does not require retry")
    session.status = "active"
    session.last_activity_at = utc_now()
    db.commit()
    return public_session(db, session)


def restart_session(db: Session, session_id: UUID) -> SessionOut:
    session = get_session_or_404(db, session_id)
    if session.status != "abandoned":
        session.status = "abandoned"
        session.abandoned = True
        session.last_activity_at = utc_now()
        db.add(models.AnalyticsEvent(session_id=session.id, event_name="questionnaire_restarted"))
        db.commit()
    return create_session(db)
