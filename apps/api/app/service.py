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
from .ai import (
    LABEL_TO_SCORE,
    AdaptiveProvider,
    FallbackAdaptiveProvider,
    GeminiAdaptiveProvider,
    ProviderError,
    allowed_dimensions,
)
from .config import get_settings
from .schemas import AnswerSubmission, ProgressOut, QuestionOut, SessionOut


privacy = PrivacyGuard()
question_bank = load_question_bank()
controller = AdaptiveController(question_bank)
fallback_provider = FallbackAdaptiveProvider()
settings = get_settings()
ai_provider: AdaptiveProvider = (
    GeminiAdaptiveProvider(settings.gemini_api_key, settings.gemini_model, settings.ai_timeout_seconds)
    if settings.ai_mode == "gemini" and settings.gemini_api_key
    else fallback_provider
)

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
    *,
    displayed_text: str | None = None,
    source: str = "bank",
) -> models.SessionQuestion:
    presented = models.SessionQuestion(
        session_id=session.id,
        question_id=question.id,
        question_order=session.total_questions + 1,
        exact_question_text=displayed_text or question.prompt,
        question_type=question.question_type.value,
        primary_dimension=question.primary_dimension,
        secondary_dimensions=list(question.secondary_dimensions),
        options_json=[{"id": item.id, "label": item.label} for item in question.options],
        scale_min=question.scale_min,
        scale_max=question.scale_max,
        selection_reason=reason,
        source=source,
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
    db.add(models.AnalyticsEvent(session_id=session.id, event_name="seed_started"))
    db.commit()
    return public_session(db, session)


def get_session_or_404(db: Session, session_id: UUID) -> models.QuestionnaireSession:
    session = db.get(models.QuestionnaireSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Questionnaire session not found")
    return session


def get_public_session(db: Session, session_id: UUID) -> SessionOut:
    return public_session(db, get_session_or_404(db, session_id))


def record_question_deployed(db: Session, session_id: UUID, question_id: UUID) -> None:
    session = get_session_or_404(db, session_id)
    question = db.get(models.SessionQuestion, question_id)
    if question is None or question.session_id != session.id:
        raise HTTPException(status_code=404, detail="Question not found for this session")
    existing = db.scalar(
        select(models.AnalyticsEvent).where(
            models.AnalyticsEvent.session_id == session.id,
            models.AnalyticsEvent.event_name == "question_deployed",
            models.AnalyticsEvent.event_properties_json["session_question_id"].as_string() == str(question.id),
        )
    )
    if existing is None:
        db.add(models.AnalyticsEvent(
            session_id=session.id,
            event_name="question_deployed",
            event_properties_json={"session_question_id": str(question.id), "question_order": question.question_order},
        ))
        db.commit()


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


def _record_ai_run(
    db: Session,
    session: models.QuestionnaireSession,
    response: models.QuestionnaireResponse | None,
    *,
    operation: str,
    provider_name: str,
    success: bool,
    input_json: dict[str, Any] | None = None,
    output_json: dict[str, Any] | None = None,
    error_category: str | None = None,
    fallback_used: bool = False,
    started_at: datetime | None = None,
) -> None:
    now = utc_now()
    latency = int((now - started_at).total_seconds() * 1000) if started_at else None
    db.add(models.AIRun(
        session_id=session.id,
        triggering_response_id=response.id if response else None,
        operation_type=operation,
        prompt_version="adaptive.v1",
        model_name=provider_name,
        attempt=1,
        status="succeeded" if success else "failed",
        input_json=input_json,
        output_json=output_json,
        latency_ms=max(latency or 0, 0) if latency is not None else None,
        success=success,
        error_category=error_category,
        fallback_used=fallback_used,
        completed_at=now,
    ))


def _apply_extraction(
    profile: ProfileV2,
    response: models.QuestionnaireResponse,
    question: models.SessionQuestion,
    extracted: Any,
) -> dict[str, Any]:
    allowed = set(allowed_dimensions(question.primary_dimension, question.secondary_dimensions))
    seen: set[str] = set()
    answer = response.sanitized_model_input
    for item in extracted.dimensions:
        if item.dimension not in allowed or item.dimension in seen:
            raise ProviderError("unauthorized_dimension")
        if item.label not in LABEL_TO_SCORE:
            raise ProviderError("invalid_rubric_label")
        if item.supporting_quote not in answer:
            raise ProviderError("invalid_evidence_quote")
        seen.add(item.dimension)
        prior = profile.dimensions[item.dimension]
        evidence = list(prior.evidence)
        evidence.append(EvidenceReference(str(response.id), EvidenceKind.DIRECT, item.supporting_quote))
        weight = max(0.2, min(1.0, item.confidence))
        old_score = prior.score if prior.score is not None else LABEL_TO_SCORE[item.label]
        score = round((old_score * (1 - weight)) + (LABEL_TO_SCORE[item.label] * weight))
        profile.dimensions[item.dimension] = DimensionState(
            score=score,
            label=item.label,
            confidence=max(prior.confidence, item.confidence),
            coverage=CoverageStatus.PARTIAL,
            summary=item.summary,
            evidence=evidence,
            unknowns=list(dict.fromkeys(item.unknowns))[:4],
            clarification_needed=item.clarification_needed,
            preference_strength_known=item.preference_strength_known,
            scenario_evidence=item.scenario_evidence,
        )
    controller.refresh_coverage(profile)
    return extracted.model_dump(mode="json")


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


def _process_response(
    db: Session,
    session: models.QuestionnaireSession,
    question: models.SessionQuestion,
    response: models.QuestionnaireResponse,
) -> None:
    now = utc_now()
    session.status = "processing"
    profile = _latest_profile(db, session)
    profile.question_count = session.total_questions + 1
    extraction_input = {
        "question": question.exact_question_text,
        "answer": response.sanitized_model_input,
        "allowed_dimensions": allowed_dimensions(question.primary_dimension, question.secondary_dimensions),
    }
    started = utc_now()
    provider = ai_provider
    fallback_used = provider is fallback_provider
    try:
        extracted = provider.extract(extraction_input)
    except ProviderError as error:
        _record_ai_run(
            db, session, response, operation="extract_response", provider_name=provider.name,
            success=False, input_json=extraction_input, error_category=error.category, started_at=started,
        )
        provider = fallback_provider
        fallback_used = True
        extracted = provider.extract(extraction_input)
    try:
        extraction = _apply_extraction(profile, response, question, extracted)
    except ProviderError as error:
        _record_ai_run(
            db, session, response, operation="extract_response", provider_name=provider.name,
            success=False, input_json=extraction_input, error_category=error.category,
            fallback_used=provider is fallback_provider, started_at=started,
        )
        if provider is fallback_provider:
            raise
        provider = fallback_provider
        fallback_used = True
        extracted = provider.extract(extraction_input)
        extraction = _apply_extraction(profile, response, question, extracted)
    _record_ai_run(
        db, session, response, operation="extract_response", provider_name=provider.name,
        success=True, input_json=extraction_input, output_json=extraction,
        fallback_used=fallback_used, started_at=started,
    )
    response.extracted_information_json = extraction
    response.validation_status = "valid"
    question.answered_at = now
    question.response_time_seconds = max(0.0, (now - question.displayed_at).total_seconds())
    session.total_questions = profile.question_count
    session.last_activity_at = now

    decision = controller.decide(profile)
    question.confidence_after_json = _confidence_map(profile)
    snapshot = models.ProfileSnapshot(
        session_id=session.id,
        version=db.scalar(
            select(func.count(models.ProfileSnapshot.id)).where(
                models.ProfileSnapshot.session_id == session.id
            )
        ) + 1,
        triggering_response_id=response.id,
        profile_json=profile.to_dict(),
        coverage_json={key: value.coverage.value for key, value in profile.dimensions.items()},
        confidence_json=_confidence_map(profile),
        missing_information_json={key: value.unknowns for key, value in profile.dimensions.items()},
    )
    db.add(snapshot)
    db.add(models.AnalyticsEvent(
        session_id=session.id,
        event_name="seed_submitted" if question.question_id == question_bank.seed.id else "answer_submitted",
    ))

    if decision.complete:
        summary_input = {
            "dimensions": {key: value.to_dict() for key, value in profile.dimensions.items()},
            "contradictions": [item.to_dict() for item in profile.contradictions],
        }
        summary_started = utc_now()
        try:
            summary = ai_provider.summarize(summary_input).summary
            if not summary.strip():
                raise ProviderError("invalid_summary")
            profile.written_summary = summary.strip()
            _record_ai_run(db, session, response, operation="summarize_profile", provider_name=ai_provider.name,
                           success=True, input_json=summary_input, output_json={"summary": profile.written_summary},
                           fallback_used=ai_provider is fallback_provider, started_at=summary_started)
        except ProviderError as error:
            profile.written_summary = _deterministic_summary(profile)
            _record_ai_run(db, session, response, operation="summarize_profile", provider_name=ai_provider.name,
                           success=False, input_json=summary_input, error_category=error.category,
                           fallback_used=True, started_at=summary_started)
        profile.status = ProfileStatus.COMPLETE
        snapshot.profile_json = profile.to_dict()
        session.status = "complete"
        session.completion_reason = decision.reason.value if decision.reason else None
        session.completed_at = now
        session.session_duration_seconds = max(0, int((now - session.started_at).total_seconds()))
        session.final_profile_json = profile.to_dict()
        session.final_summary = profile.written_summary
        db.add(models.AnalyticsEvent(session_id=session.id, event_name="questionnaire_completed"))
        return

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
        # A target can need more clarification than the two bank questions
        # assigned to it. Keep the interview moving with the first remaining
        # curated question instead of leaving a stored answer in retry forever.
        next_question = next(
            (
                candidate
                for candidate in question_bank.questions
                if candidate.active and not candidate.is_seed and candidate.id not in asked
            ),
            None,
        )
        if next_question is None:
            raise HTTPException(status_code=503, detail="No safe fallback question is available")
        selection_reason = f"bank_exhausted_for_target:{decision.next_dimension}"
    else:
        selection_reason = _selection_reason(profile, decision.next_dimension)
    adaptation_input = {
        "target_dimension": decision.next_dimension,
        "bank_question": next_question.prompt,
        "last_answer": response.sanitized_model_input,
    }
    adaptation_started = utc_now()
    displayed_text, source = next_question.prompt, "bank"
    try:
        adapted = ai_provider.adapt_question(adaptation_input).text.strip()
        valid, _ = privacy.validate_generated_question(adapted)
        if not valid:
            raise ProviderError("unsafe_or_invalid_question")
        displayed_text, source = adapted, "ai_adapted"
        _record_ai_run(db, session, response, operation="adapt_question", provider_name=ai_provider.name,
                       success=True, input_json=adaptation_input, output_json={"text": adapted},
                       fallback_used=ai_provider is fallback_provider, started_at=adaptation_started)
    except ProviderError as error:
        _record_ai_run(db, session, response, operation="adapt_question", provider_name=ai_provider.name,
                       success=False, input_json=adaptation_input, error_category=error.category,
                       fallback_used=True, started_at=adaptation_started)
    _present_question(
        db, session, next_question, profile, selection_reason,
        displayed_text=displayed_text, source=source,
    )


def _mark_processing_failure(
    db: Session,
    session: models.QuestionnaireSession,
    response: models.QuestionnaireResponse,
    operation_type: str,
) -> None:
    """Keep a submitted answer available for a safe retry after processing fails."""
    now = utc_now()
    session.status = "needs_retry"
    session.error_occurred = True
    session.last_activity_at = now
    response.validation_status = "needs_retry"
    db.add(
        models.AIRun(
            session_id=session.id,
            triggering_response_id=response.id,
            operation_type=operation_type,
            prompt_version="mock.v1",
            model_name="deterministic-mock",
            status="failed",
            error_category="processing_failed",
            success=False,
            fallback_used=False,
            completed_at=now,
        )
    )
    db.add(models.AnalyticsEvent(session_id=session.id, event_name="application_error_shown"))


def _process_or_mark_retry(
    db: Session,
    session: models.QuestionnaireSession,
    question: models.SessionQuestion,
    response: models.QuestionnaireResponse,
    operation_type: str,
) -> None:
    """Contain processing writes so an unsuccessful attempt cannot alter profile state."""
    try:
        with db.begin_nested():
            _process_response(db, session, question, response)
    except Exception:
        # The submitted response was flushed before this savepoint. Preserve it,
        # but roll back all tentative profile, question, and audit mutations.
        db.expire_all()
        persisted_session = get_session_or_404(db, session.id)
        persisted_response = db.get(models.QuestionnaireResponse, response.id)
        if persisted_response is None:
            raise RuntimeError("Submitted response was not persisted")
        _mark_processing_failure(db, persisted_session, persisted_response, operation_type)
    db.commit()


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
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="The answer was already submitted") from error
    _process_or_mark_retry(db, session, question, response, "mock_extract_and_select")
    return public_session(db, get_session_or_404(db, session_id))


def retry_session(db: Session, session_id: UUID) -> SessionOut:
    session = get_session_or_404(db, session_id)
    if session.status != "needs_retry":
        raise HTTPException(status_code=409, detail="Session does not require retry")
    response = db.scalar(
        select(models.QuestionnaireResponse)
        .where(
            models.QuestionnaireResponse.session_id == session.id,
            models.QuestionnaireResponse.validation_status == "needs_retry",
        )
        .order_by(models.QuestionnaireResponse.submitted_at.desc())
        .limit(1)
    )
    if response is None:
        raise HTTPException(status_code=409, detail="No pending response is available for retry")
    question = db.get(models.SessionQuestion, response.session_question_id)
    if question is None or question.answered_at is not None:
        raise HTTPException(status_code=409, detail="The pending response cannot be retried")
    _process_or_mark_retry(db, session, question, response, "mock_extract_and_select_retry")
    return public_session(db, get_session_or_404(db, session_id))


def restart_session(db: Session, session_id: UUID) -> SessionOut:
    session = get_session_or_404(db, session_id)
    if session.status != "abandoned":
        session.status = "abandoned"
        session.abandoned = True
        session.last_activity_at = utc_now()
        db.add(models.AnalyticsEvent(session_id=session.id, event_name="questionnaire_restarted"))
        db.commit()
    return create_session(db)
