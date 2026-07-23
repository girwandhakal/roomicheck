from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from roomicheck.privacy import PrivacyGuard
from roomicheck.v2.config import (
    DIMENSION_IDS,
    PROFILE_SCHEMA_VERSION,
    QUESTIONNAIRE_VERSION,
    REQUIRED_QUESTION_IDS,
    SUBDIMENSION_IDS,
)
from roomicheck.v2.controller import (
    AdaptiveController,
    CompletionDecision,
    CompletionReason,
    MAXIMUM_QUESTION_COUNT,
)
from roomicheck.v2.models import (
    CoverageStatus,
    DimensionState,
    EvidenceKind,
    EvidenceReference,
    ProfileStatus,
    ProfileV2,
    SubdimensionState,
    Contradiction,
)
from roomicheck.v2.questions import QuestionDefinition, QuestionOption, QuestionType, load_question_bank
from roomicheck.v2.fixed_scoring import fixed_option_effects, fixed_scale_effects

from . import models
from .ai import (
    CONFIDENCE_TO_SCORE,
    LABEL_TO_SCORE,
    AdaptiveProvider,
    FallbackAdaptiveProvider,
    OpenAIAdaptiveProvider,
    ExtractionDimension,
    ExtractionResult,
    SubdimensionExtraction,
    AdaptiveBundle,
    AdaptiveHypothesis,
    AdaptiveQuestion,
    ProviderError,
    SummaryResult,
    allowed_dimensions,
    validate_summary,
)
from .config import get_settings
from .prompts import (
    ADAPT_PROMPT_VERSION,
    ADAPTIVE_BUNDLE_PROMPT_VERSION,
    EXTRACT_PROMPT_VERSION,
    SUMMARY_PROMPT_VERSION,
)
from .schemas import AnswerSubmission, ProgressOut, QuestionOut, SessionOut


privacy = PrivacyGuard()
question_bank = load_question_bank()
controller = AdaptiveController(question_bank)
fallback_provider = FallbackAdaptiveProvider()
settings = get_settings()
ai_provider: AdaptiveProvider = (
    OpenAIAdaptiveProvider(settings.openai_api_key, settings.openai_model, settings.ai_timeout_seconds)
    if settings.ai_mode == "openai" and settings.openai_api_key
    else fallback_provider
)

CLIENT_EVENT_NAMES = {
    "questionnaire_opened",
    "question_displayed",
    "answer_edited",
    "back_clicked",
    "final_profile_viewed",
    "application_error_shown",
}
EVENT_PROPERTY_KEYS = {
    "questionnaire_opened": set(),
    "question_displayed": {"session_question_id", "question_order"},
    "answer_edited": {"session_question_id"},
    "back_clicked": {"session_question_id"},
    "final_profile_viewed": set(),
    "application_error_shown": {"error_type", "status"},
}

SEED_SIGNAL_PATTERNS = {
    "physical_environment": re.compile(r"\b(?:quiet|noise|music|calls?|light|temperature|sleep)\b", re.I),
    "social_interaction": re.compile(r"\b(?:social|friends?|hang out|alone|privacy|own space)\b", re.I),
    "study_daily_routine": re.compile(r"\b(?:study|work|schedule|routine|weekday|weekend|wake|sleep)\b", re.I),
    "cultural_openness": re.compile(r"\b(?:culture|cultural|language|tradition|different background|food)\b", re.I),
    "household_structure": re.compile(r"\b(?:clean|chores?|supplies|sharing|guests?|common area|rules?)\b", re.I),
    "personal_boundaries": re.compile(r"\b(?:boundar|private|privacy|belongings?|borrow|visitors?|guests?)\w*\b", re.I),
    "communication_style": re.compile(r"\b(?:communicat|conflict|compromise|discuss|talk|problem|direct|message)\w*\b", re.I),
    "rule_flexibility": re.compile(r"\b(?:rule|agreement|flexib|adapt|adjust|expectation|schedule)\w*\b", re.I),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def mark_abandoned_if_stale(db: Session, session: models.QuestionnaireSession) -> bool:
    if session.status not in {"active", "processing", "needs_retry"}:
        return False
    cutoff = utc_now() - timedelta(minutes=settings.abandonment_timeout_minutes)
    if session.last_activity_at >= cutoff:
        return False
    session.status = "abandoned"
    session.abandoned = True
    db.add(models.AnalyticsEvent(
        session_id=session.id,
        event_name="session_abandoned",
        event_properties_json={"timeout_minutes": settings.abandonment_timeout_minutes},
    ))
    return True


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
    adaptive_metadata: dict[str, Any] | None = None,
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
        adaptive_metadata_json=adaptive_metadata,
    )
    db.add(presented)
    db.flush()
    return presented


def _present_adaptive_question(
    db: Session,
    session: models.QuestionnaireSession,
    profile: ProfileV2,
    question: AdaptiveQuestion,
    hypothesis: AdaptiveHypothesis,
    *,
    source_question_id: str,
) -> models.SessionQuestion:
    return _present_question(
        db,
        session,
        QuestionDefinition(
            id=source_question_id,
            version=QUESTIONNAIRE_VERSION,
            prompt=question.text,
            question_type=QuestionType(question.question_type),
            primary_dimension=question.primary_dimension,
            secondary_dimensions=tuple(question.secondary_dimensions),
            options=tuple(QuestionOption(item.id, item.label) for item in question.options),
            scale_min=None,
            scale_max=None,
            is_seed=False,
            active=True,
        ),
        profile,
        f"adaptive_hypothesis:{hypothesis.id}",
        displayed_text=question.text,
        source="ai_generated",
        adaptive_metadata={
            "question_id": question.id,
            "hypothesis_id": hypothesis.id,
            "hypothesis_statement": hypothesis.statement,
            "target_subdimensions": question.target_subdimensions,
            "rationale": question.rationale,
            "evidence_gap": question.evidence_gap,
            "round": session.adaptive_round,
        },
    )


def _latest_profile(db: Session, session: models.QuestionnaireSession) -> ProfileV2:
    snapshot = db.scalar(
        select(models.ProfileSnapshot)
        .where(models.ProfileSnapshot.session_id == session.id)
        .order_by(models.ProfileSnapshot.version.desc())
        .limit(1)
    )
    if snapshot is None:
        return ProfileV2.empty(str(session.id))
    return ProfileV2.from_dict(_migrate_profile_payload(snapshot.profile_json))


def _migrate_profile_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Make v4/v3 snapshots readable after adding explicit subdimensions."""
    migrated = deepcopy(payload)
    dimensions = migrated.get("dimensions", {})
    if "noise_environment" in dimensions and "physical_environment" not in dimensions:
        dimensions["physical_environment"] = dimensions.pop("noise_environment")
    for dimension in dimensions.values():
        if not isinstance(dimension, dict):
            continue
        dimension.setdefault(
            "subdimensions",
            {
                key: {"score": None, "label": None, "confidence": 0.0, "summary": None, "evidence": []}
                for key in SUBDIMENSION_IDS
            },
        )
    migrated["schema_version"] = PROFILE_SCHEMA_VERSION
    return migrated


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
    current_question = _current_question(db, session.id) if session.status in {"active", "processing", "needs_retry"} else None
    return SessionOut(
        session_id=session.id,
        status=session.status,
        progress=ProgressOut(answered=session.total_questions),
        current_question=_question_out(current_question),
        final_profile=session.final_profile_json if session.status == "complete" else None,
        final_summary=session.final_summary if session.status == "complete" else None,
        final_analysis=session.final_analysis_json if session.status == "complete" else None,
    )


def create_session(db: Session) -> SessionOut:
    seed_question_bank(db)
    session = models.QuestionnaireSession(
        questionnaire_version=QUESTIONNAIRE_VERSION,
        profile_schema_version=PROFILE_SCHEMA_VERSION,
        prompt_version=EXTRACT_PROMPT_VERSION,
        model_version=ai_provider.name,
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
    session = get_session_or_404(db, session_id)
    changed = mark_abandoned_if_stale(db, session)
    if changed:
        db.commit()
    return public_session(db, session)


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


def record_client_event(
    db: Session,
    session_id: UUID,
    event_name: str,
    properties: dict[str, str | int | float | bool | None],
) -> None:
    session = get_session_or_404(db, session_id)
    if event_name not in CLIENT_EVENT_NAMES:
        raise HTTPException(status_code=422, detail="Unsupported analytics event")
    allowed_keys = EVENT_PROPERTY_KEYS[event_name]
    if set(properties) - allowed_keys:
        raise HTTPException(status_code=422, detail="Unsupported analytics event property")
    for key, value in properties.items():
        if len(key) > 64 or isinstance(value, str) and len(value) > 128:
            raise HTTPException(status_code=422, detail="Analytics event property is too large")
    question_property = properties.get("session_question_id")
    if question_property is not None:
        if not isinstance(question_property, str):
            raise HTTPException(status_code=422, detail="Invalid question reference")
        try:
            question = db.get(models.SessionQuestion, UUID(question_property))
        except ValueError as error:
            raise HTTPException(status_code=422, detail="Invalid question reference") from error
        if question is None or question.session_id != session.id:
            raise HTTPException(status_code=422, detail="Question is not part of this session")
        if "question_order" in properties and properties["question_order"] != question.question_order:
            raise HTTPException(status_code=422, detail="Question order does not match the session")
    if event_name == "final_profile_viewed" and session.status != "complete":
        raise HTTPException(status_code=409, detail="The final profile is not available")
    if event_name == "question_displayed":
        question_id = properties.get("session_question_id")
        existing = db.scalar(select(models.AnalyticsEvent).where(
            models.AnalyticsEvent.session_id == session.id,
            models.AnalyticsEvent.event_name == event_name,
            models.AnalyticsEvent.event_properties_json["session_question_id"].as_string() == str(question_id),
        ))
        if existing is not None:
            return
    if event_name == "final_profile_viewed":
        existing = db.scalar(select(models.AnalyticsEvent).where(
            models.AnalyticsEvent.session_id == session.id,
            models.AnalyticsEvent.event_name == event_name,
        ))
        if existing is not None:
            return
    db.add(models.AnalyticsEvent(
        session_id=session.id,
        event_name=event_name,
        event_properties_json=properties,
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
    prompt_versions = {
        "extract_response": EXTRACT_PROMPT_VERSION,
        "adapt_question": ADAPT_PROMPT_VERSION,
        "adaptive_bundle": ADAPTIVE_BUNDLE_PROMPT_VERSION,
        "summarize_profile": SUMMARY_PROMPT_VERSION,
        "fixed_choice_score": "co_living_scoring.v3",
    }
    db.add(models.AIRun(
        session_id=session.id,
        triggering_response_id=response.id if response else None,
        operation_type=operation,
        prompt_version=prompt_versions.get(operation, "adaptive.v1"),
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


def _adaptive_context(
    db: Session,
    session: models.QuestionnaireSession,
    profile: ProfileV2,
    triggering_response: models.QuestionnaireResponse,
) -> dict[str, Any]:
    responses = list(db.scalars(
        select(models.QuestionnaireResponse)
        .where(models.QuestionnaireResponse.session_id == session.id)
        .order_by(models.QuestionnaireResponse.submitted_at)
    ))
    questions = {
        item.id: item for item in db.scalars(
            select(models.SessionQuestion).where(models.SessionQuestion.session_id == session.id)
        )
    }
    return {
        "questionnaire_version": QUESTIONNAIRE_VERSION,
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "round": session.adaptive_round + 1,
        "seed_answer": triggering_response.sanitized_model_input,
        "response_ids": [str(item.id) for item in responses],
        "responses": [
            {
                "response_id": str(item.id),
                "question_id": questions[item.session_question_id].question_id,
                "question": questions[item.session_question_id].exact_question_text,
                "answer": item.sanitized_model_input,
            }
            for item in responses
            if item.session_question_id in questions
        ],
        "profile": profile.to_dict(),
        "dimensions": list(DIMENSION_IDS),
        "subdimensions": list(SUBDIMENSION_IDS),
    }


def _validate_adaptive_bundle(bundle: AdaptiveBundle, *, answered_texts: set[str]) -> AdaptiveBundle:
    if not 2 <= len(bundle.hypotheses) <= 3:
        raise ProviderError("invalid_hypothesis_count")
    hypothesis_ids: set[str] = set()
    question_ids: set[str] = set()
    for hypothesis in bundle.hypotheses:
        if hypothesis.id in hypothesis_ids:
            raise ProviderError("duplicate_hypothesis_id")
        hypothesis_ids.add(hypothesis.id)
        if not 2 <= len(hypothesis.questions) <= 3:
            raise ProviderError("invalid_questions_per_hypothesis")
        for question in hypothesis.questions:
            if question.id in question_ids:
                raise ProviderError("duplicate_generated_question_id")
            question_ids.add(question.id)
            if _question_text_key(question.text) in answered_texts:
                raise ProviderError("duplicate_generated_question_text")
            if question.primary_dimension not in DIMENSION_IDS:
                raise ProviderError("invalid_generated_dimension")
            if question.primary_dimension in question.secondary_dimensions:
                raise ProviderError("repeated_generated_dimension")
            if len(set(question.secondary_dimensions)) != len(question.secondary_dimensions):
                raise ProviderError("duplicate_generated_dimension")
            if any(item not in DIMENSION_IDS for item in question.secondary_dimensions):
                raise ProviderError("invalid_generated_secondary_dimension")
            if question.question_type == "single_choice":
                if not 2 <= len(question.options) <= 5:
                    raise ProviderError("invalid_generated_options")
                if len({item.id for item in question.options}) != len(question.options):
                    raise ProviderError("duplicate_generated_option")
                if not any(item.id == "other" for item in question.options):
                    raise ProviderError("missing_generated_other_option")
            elif question.options:
                raise ProviderError("unexpected_generated_options")
            if not question.target_subdimensions:
                raise ProviderError("missing_generated_subdimension_target")
            valid, _ = privacy.validate_generated_question(question.text)
            if not valid:
                raise ProviderError("generated_question_policy_violation")
    return bundle


def _generate_adaptive_bundle(
    db: Session,
    session: models.QuestionnaireSession,
    profile: ProfileV2,
    response: models.QuestionnaireResponse,
) -> AdaptiveBundle:
    answered_texts = {
        _question_text_key(item.exact_question_text)
        for item in db.scalars(
            select(models.SessionQuestion).where(models.SessionQuestion.session_id == session.id)
        )
    }
    payload = _adaptive_context(db, session, profile, response)
    provider = ai_provider if response.sanitized_model_input else fallback_provider
    generate_bundle = getattr(provider, "generate_adaptive_bundle", None)
    if not callable(generate_bundle):
        provider = fallback_provider
        generate_bundle = fallback_provider.generate_adaptive_bundle
    started = utc_now()
    try:
        bundle = generate_bundle(payload)
        _validate_adaptive_bundle(bundle, answered_texts=answered_texts)
    except (ProviderError, ValueError) as error:
        if provider is not fallback_provider:
            _record_ai_run(
                db, session, response, operation="adaptive_bundle", provider_name=provider.name,
                success=False, input_json=payload, error_category=getattr(error, "category", "invalid_bundle"),
                fallback_used=False, started_at=started,
            )
        bundle = fallback_provider.generate_adaptive_bundle(payload)
        _validate_adaptive_bundle(bundle, answered_texts=answered_texts)
        provider = fallback_provider
        fallback_used = True
    else:
        fallback_used = provider is fallback_provider
    _record_ai_run(
        db, session, response, operation="adaptive_bundle", provider_name=provider.name,
        success=True, input_json=payload, output_json=bundle.model_dump(mode="json"),
        fallback_used=fallback_used, started_at=started,
    )
    session.adaptive_round += 1
    session.active_adaptive_bundle_json = bundle.model_dump(mode="json")
    return bundle


def _next_adaptive_question(
    db: Session,
    session: models.QuestionnaireSession,
    profile: ProfileV2,
) -> models.SessionQuestion | None:
    bundle = session.active_adaptive_bundle_json
    if not isinstance(bundle, dict):
        return None
    answered_generated_ids = {
        item.adaptive_metadata_json.get("question_id")
        for item in db.scalars(
            select(models.SessionQuestion).where(
                models.SessionQuestion.session_id == session.id,
                models.SessionQuestion.source == "ai_generated",
                models.SessionQuestion.answered_at.is_not(None),
            )
        )
        if isinstance(item.adaptive_metadata_json, dict)
    }
    hypotheses = [AdaptiveHypothesis.model_validate(item) for item in bundle.get("hypotheses", [])]
    for hypothesis in sorted(hypotheses, key=lambda item: (item.priority, item.id)):
        for generated in hypothesis.questions:
            if generated.id in answered_generated_ids:
                continue
            source_question_id = question_bank.seed.id
            candidate = _present_adaptive_question(
                db, session, profile, generated, hypothesis, source_question_id=source_question_id,
            )
            return candidate
    return None


def _apply_extraction(
    profile: ProfileV2,
    response: models.QuestionnaireResponse,
    question: models.SessionQuestion,
    extracted: Any,
) -> dict[str, Any]:
    allowed = set(allowed_dimensions(question.primary_dimension, question.secondary_dimensions))
    seen: set[str] = set()
    answer = response.sanitized_model_input
    prior_response_ids = {
        evidence.response_id
        for state in profile.dimensions.values()
        for evidence in state.evidence
    }
    prior_response_ids.update(
        response_id
        for contradiction in profile.contradictions
        for response_id in contradiction.response_ids
    )
    for item in extracted.dimensions:
        if item.dimension not in allowed or item.dimension in seen:
            raise ProviderError("unauthorized_dimension")
        if item.label not in LABEL_TO_SCORE:
            raise ProviderError("invalid_rubric_label")
        if item.supporting_quote not in answer:
            raise ProviderError("invalid_evidence_quote")
        if any(ref not in prior_response_ids for ref in item.contradiction_response_ids):
            raise ProviderError("invalid_contradiction_reference")
        seen.add(item.dimension)
        prior = profile.dimensions[item.dimension]
        evidence = list(prior.evidence)
        evidence.append(EvidenceReference(str(response.id), EvidenceKind.DIRECT, item.supporting_quote))
        weight = max(0.2, min(1.0, item.weight))
        target_score = item._score_override if item._score_override is not None else LABEL_TO_SCORE[item.label]
        old_score = prior.score if prior.score is not None else target_score
        score = round((old_score * (1 - weight)) + (target_score * weight))
        subdimensions = {key: value for key, value in prior.subdimensions.items()}
        seen_subdimensions: set[str] = set()
        for subdimension_item in item.subdimensions:
            if subdimension_item.subdimension not in SUBDIMENSION_IDS or subdimension_item.subdimension in seen_subdimensions:
                raise ProviderError("invalid_subdimension")
            if subdimension_item.supporting_quote not in answer:
                raise ProviderError("invalid_subdimension_evidence_quote")
            seen_subdimensions.add(subdimension_item.subdimension)
            prior_subdimension = subdimensions[subdimension_item.subdimension]
            subdimension_evidence = list(prior_subdimension.evidence)
            subdimension_evidence.append(
                EvidenceReference(str(response.id), EvidenceKind.DIRECT, subdimension_item.supporting_quote)
            )
            subdimension_weight = max(0.2, min(1.0, subdimension_item.weight))
            subdimension_target = LABEL_TO_SCORE[subdimension_item.label]
            subdimension_old = (
                prior_subdimension.score
                if prior_subdimension.score is not None
                else subdimension_target
            )
            subdimensions[subdimension_item.subdimension] = SubdimensionState(
                score=round((subdimension_old * (1 - subdimension_weight)) + (subdimension_target * subdimension_weight)),
                label=subdimension_item.label,
                confidence=max(
                    prior_subdimension.confidence,
                    CONFIDENCE_TO_SCORE[subdimension_item.confidence],
                ),
                summary=subdimension_item.summary,
                evidence=subdimension_evidence,
            )
        profile.dimensions[item.dimension] = DimensionState(
            score=score,
            label=item.label,
            confidence=(
                min(max(prior.confidence, CONFIDENCE_TO_SCORE[item.confidence]), 0.55)
                if item.contradiction_response_ids
                else max(prior.confidence, CONFIDENCE_TO_SCORE[item.confidence])
            ),
            coverage=CoverageStatus.PARTIAL,
            summary=item.summary,
            evidence=evidence,
            unknowns=list(dict.fromkeys(item.unknowns))[:4],
            clarification_needed=item.clarification_needed or bool(item.contradiction_response_ids),
            preference_strength_known=item.preference_strength_known,
            scenario_evidence=item.scenario_evidence,
            subdimensions=subdimensions,
        )
        if item.contradiction_response_ids:
            profile.contradictions.append(Contradiction(
                id=str(uuid4()),
                dimension=item.dimension,
                response_ids=list(dict.fromkeys([*item.contradiction_response_ids, str(response.id)])),
                description=item.summary,
                major=True,
                resolved=False,
            ))
    controller.refresh_coverage(profile)
    return extracted.model_dump(mode="json")


def _deterministic_analysis(profile: ProfileV2) -> SummaryResult:
    return fallback_provider.summarize({
        "dimensions": {key: value.to_dict() for key, value in profile.dimensions.items()},
        "contradictions": [item.to_dict() for item in profile.contradictions],
    })


def _selection_reason(profile: ProfileV2, dimension: str) -> str:
    state = profile.dimensions[dimension]
    if state.coverage == CoverageStatus.UNKNOWN:
        return f"unknown_dimension:{dimension}"
    if state.clarification_needed:
        return f"clarification_needed:{dimension}"
    return f"lowest_confidence:{dimension}"


def _next_required_question(asked_question_ids: set[str]) -> QuestionDefinition | None:
    """Return the next mandatory fixed question in its stable order."""
    for required_id in REQUIRED_QUESTION_IDS:
        if required_id in asked_question_ids:
            continue
        question = next(
            (candidate for candidate in question_bank.questions if candidate.id == required_id and candidate.active),
            None,
        )
        if question is not None:
            return question
    return None


def _question_text_key(text: str) -> str:
    return " ".join(text.casefold().split())


def _record_privacy_withheld_run(
    db: Session,
    session: models.QuestionnaireSession,
    response: models.QuestionnaireResponse,
    *,
    operation: str,
    output_json: dict[str, Any] | None = None,
) -> None:
    """Audit a provider operation intentionally skipped by the privacy guard."""
    _record_ai_run(
        db,
        session,
        response,
        operation=operation,
        provider_name="privacy-guard",
        success=True,
        input_json={"withheld": True},
        output_json=output_json,
        error_category="privacy_withheld",
        fallback_used=True,
    )


def _extraction_answer_payload(
    question: models.SessionQuestion,
    response: models.QuestionnaireResponse,
) -> dict[str, Any]:
    """Build a context-rich, privacy-sanitized answer for the provider."""
    raw = response.raw_response
    answer = raw if isinstance(raw, dict) else {}
    selected_option_id = answer.get("selected_option_id")
    selected_option_label = next(
        (
            option["label"]
            for option in question.options_json
            if option["id"] == selected_option_id
        ),
        None,
    )
    return {
        "normalized_text": response.sanitized_model_input,
        "selected_option_id": selected_option_id,
        "selected_option_label": selected_option_label,
        "scale_value": answer.get("scale_value"),
    }


def _fixed_choice_extraction(
    question: models.SessionQuestion,
    response: models.QuestionnaireResponse,
) -> ExtractionResult | None:
    """Return a validated extraction for a known option, without calling AI."""
    if question.question_type != "single_choice":
        return None
    raw = response.raw_response if isinstance(response.raw_response, dict) else {}
    option_id = raw.get("selected_option_id")
    if not isinstance(option_id, str) or option_id == "other":
        return None
    effects = fixed_option_effects(
        question.question_id,
        option_id,
        allowed_dimensions(question.primary_dimension, question.secondary_dimensions),
    )
    if effects is None:
        raise ProviderError("missing_fixed_mapping")
    dimensions = []
    for dimension, effect in effects.items():
        item = ExtractionDimension(
            dimension=dimension,
            label=effect.label,
            confidence="high" if effect.confidence >= 0.85 else "moderate" if effect.confidence >= 0.7 else "low",
            weight=1.0,
            supporting_quote=response.sanitized_model_input,
            summary=effect.summary,
            preference_strength_known=True,
            scenario_evidence=True,
        )
        item._score_override = effect.score
        item.subdimensions = [SubdimensionExtraction(
            subdimension="personal_preference",
            label=effect.label,
            confidence="high" if effect.confidence >= 0.85 else "moderate" if effect.confidence >= 0.7 else "low",
            weight=1.0,
            supporting_quote=response.sanitized_model_input,
            summary=effect.summary,
        )]
        dimensions.append(item)
    return ExtractionResult(dimensions=dimensions)


def _fixed_answer_extraction(
    question: models.SessionQuestion,
    response: models.QuestionnaireResponse,
) -> ExtractionResult | None:
    if question.source == "ai_generated":
        return None
    if question.question_type == "single_choice":
        return _fixed_choice_extraction(question, response)
    if question.question_type != "scale":
        return None
    raw = response.raw_response if isinstance(response.raw_response, dict) else {}
    scale_value = raw.get("scale_value")
    if not isinstance(scale_value, int) or isinstance(scale_value, bool):
        return None
    effects = fixed_scale_effects(
        question.question_id,
        scale_value,
        allowed_dimensions(question.primary_dimension, question.secondary_dimensions),
    )
    if effects is None:
        raise ProviderError("missing_fixed_mapping")
    dimensions = []
    for dimension, effect in effects.items():
        item = ExtractionDimension(
            dimension=dimension,
            label=effect.label,
            confidence="high" if effect.confidence >= 0.85 else "moderate" if effect.confidence >= 0.7 else "low",
            weight=1.0,
            supporting_quote=response.sanitized_model_input,
            summary=effect.summary,
            preference_strength_known=True,
            scenario_evidence=False,
        )
        item._score_override = effect.score
        dimensions.append(item)
    return ExtractionResult(dimensions=dimensions)


def _process_response(
    db: Session,
    session: models.QuestionnaireSession,
    question: models.SessionQuestion,
    response: models.QuestionnaireResponse,
    *,
    ai_allowed: bool,
) -> None:
    now = utc_now()
    session.status = "processing"
    profile = _latest_profile(db, session)
    profile.question_count = session.total_questions + 1
    extraction_input = {
        "question_id": question.question_id,
        "question": question.exact_question_text,
        "question_type": question.question_type,
        "target_dimension": question.primary_dimension,
        "secondary_dimensions": question.secondary_dimensions,
        "adaptive_metadata": question.adaptive_metadata_json,
        "target_subdimensions": (
            question.adaptive_metadata_json.get("target_subdimensions", [])
            if isinstance(question.adaptive_metadata_json, dict) else []
        ),
        "evidence_type": "scenario_response" if question.question_type == "scenario" else question.question_type,
        "answer": _extraction_answer_payload(question, response),
        "options": question.options_json if question.question_type == "single_choice" else [],
        "scale": {
            "minimum": question.scale_min,
            "maximum": question.scale_max,
        } if question.question_type == "scale" else None,
        "allowed_dimensions": allowed_dimensions(question.primary_dimension, question.secondary_dimensions),
        "prior_response_ids": [
            str(item.id) for item in db.scalars(
                select(models.QuestionnaireResponse).where(
                    models.QuestionnaireResponse.session_id == session.id,
                    models.QuestionnaireResponse.id != response.id,
                )
            ).all()
        ],
    }
    fixed_extraction = _fixed_answer_extraction(question, response) if ai_allowed else None
    if fixed_extraction is not None:
        extraction = _apply_extraction(profile, response, question, fixed_extraction)
        _record_ai_run(
            db,
            session,
            response,
            operation="fixed_choice_score",
            provider_name="deterministic-fixed-choice",
            success=True,
            input_json=extraction_input,
            output_json=extraction,
            fallback_used=False,
        )
    elif not ai_allowed:
        extraction = _mock_extract(profile, question, response.id, response.sanitized_model_input, False)
        _record_privacy_withheld_run(
            db, session, response, operation="extract_response", output_json=extraction,
        )
    else:
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

    asked = set(
        db.scalars(
            select(models.SessionQuestion.question_id).where(
                models.SessionQuestion.session_id == session.id
            )
        ).all()
    )
    decision = controller.decide(profile, asked)
    required_next = _next_required_question(asked)
    if required_next is not None and profile.question_count < MAXIMUM_QUESTION_COUNT:
        # Mandatory physical-environment questions are always collected before
        # adaptive follow-ups or threshold completion can finish the session.
        decision = CompletionDecision(False, next_dimension=required_next.primary_dimension)
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
        event_name=(
            "seed_submitted"
            if question.question_id == question_bank.seed.id and question.source != "ai_generated"
            else "answer_submitted"
        ),
    ))

    adaptive_next: tuple[AdaptiveQuestion, AdaptiveHypothesis] | None = None
    if question.question_id == question_bank.seed.id and question.source != "ai_generated":
        bundle = _generate_adaptive_bundle(db, session, profile, response)
        first_hypothesis = min(bundle.hypotheses, key=lambda item: (item.priority, item.id))
        adaptive_next = (first_hypothesis.questions[0], first_hypothesis)
    elif question.source == "ai_generated":
        bundle = session.active_adaptive_bundle_json
        if isinstance(bundle, dict):
            parsed = AdaptiveBundle.model_validate(bundle)
            for hypothesis in sorted(parsed.hypotheses, key=lambda item: (item.priority, item.id)):
                answered_ids = {
                    item.adaptive_metadata_json.get("question_id")
                    for item in db.scalars(
                        select(models.SessionQuestion).where(
                            models.SessionQuestion.session_id == session.id,
                            models.SessionQuestion.source == "ai_generated",
                            models.SessionQuestion.answered_at.is_not(None),
                        )
                    )
                    if isinstance(item.adaptive_metadata_json, dict)
                }
                for generated in hypothesis.questions:
                    if generated.id not in answered_ids:
                        adaptive_next = (generated, hypothesis)
                        break
                if adaptive_next:
                    break
        if adaptive_next is None and profile.question_count < MAXIMUM_QUESTION_COUNT:
            session.active_adaptive_bundle_json = None
            bundle = _generate_adaptive_bundle(db, session, profile, response)
            first_hypothesis = min(bundle.hypotheses, key=lambda item: (item.priority, item.id))
            adaptive_next = (first_hypothesis.questions[0], first_hypothesis)

    if adaptive_next is not None and profile.question_count < MAXIMUM_QUESTION_COUNT:
        session.status = "active"
        generated, hypothesis = adaptive_next
        _present_adaptive_question(
            db,
            session,
            profile,
            generated,
            hypothesis,
            source_question_id=question_bank.seed.id,
        )
        return

    if decision.complete:
        summary_input = {
            "dimensions": {key: value.to_dict() for key, value in profile.dimensions.items()},
            "contradictions": [item.to_dict() for item in profile.contradictions],
            "question_texts": [
                item.exact_question_text for item in db.scalars(
                    select(models.SessionQuestion).where(
                        models.SessionQuestion.session_id == session.id
                    )
                )
            ],
        }
        summary_started = utc_now()
        try:
            analysis = ai_provider.summarize(summary_input)
            analysis.ideal_roommate = validate_summary(
                analysis.ideal_roommate,
                summary_input["question_texts"],
            )
            profile.written_summary = analysis.ideal_roommate
            _record_ai_run(db, session, response, operation="summarize_profile", provider_name=ai_provider.name,
                           success=True, input_json=summary_input, output_json=analysis.model_dump(mode="json"),
                           fallback_used=ai_provider is fallback_provider, started_at=summary_started)
        except ProviderError as error:
            analysis = _deterministic_analysis(profile)
            profile.written_summary = analysis.ideal_roommate
            _record_ai_run(db, session, response, operation="summarize_profile", provider_name=ai_provider.name,
                           success=False, input_json=summary_input, output_json=analysis.model_dump(mode="json"), error_category=error.category,
                           fallback_used=True, started_at=summary_started)
        profile.status = ProfileStatus.COMPLETE
        snapshot.profile_json = profile.to_dict()
        session.status = "complete"
        session.completion_reason = decision.reason.value if decision.reason else None
        session.completed_at = now
        session.session_duration_seconds = max(0, int((now - session.started_at).total_seconds()))
        session.final_profile_json = profile.to_dict()
        session.final_summary = profile.written_summary
        session.final_analysis_json = analysis.model_dump(mode="json")
        db.add(models.AnalyticsEvent(session_id=session.id, event_name="questionnaire_completed"))
        return

    session.status = "active"
    next_question = required_next
    if next_question is not None:
        selection_reason = f"required_fixed:{next_question.id}"
    else:
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
    elif required_next is None:
        selection_reason = _selection_reason(profile, decision.next_dimension)
    adaptation_input = {
        "target_dimension": decision.next_dimension,
        "bank_question": next_question.prompt,
        "last_answer": response.sanitized_model_input,
    }
    displayed_text, source = next_question.prompt, "bank"
    if not ai_allowed:
        _record_privacy_withheld_run(db, session, response, operation="adapt_question")
    elif next_question.id in REQUIRED_QUESTION_IDS or fixed_extraction is not None:
        # Known options use the curated bank wording and do not need a second
        # model call to rewrite a question.
        pass
    else:
        adaptation_started = utc_now()
        try:
            adapted = ai_provider.adapt_question(adaptation_input).text.strip()
            valid, _ = privacy.validate_generated_question(adapted)
            asked_texts = db.scalars(
                select(models.SessionQuestion.exact_question_text).where(
                    models.SessionQuestion.session_id == session.id
                )
            ).all()
            if not valid:
                raise ProviderError("unsafe_or_invalid_question")
            if _question_text_key(adapted) in {_question_text_key(item) for item in asked_texts}:
                raise ProviderError("repeated_question")
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
            prompt_version=EXTRACT_PROMPT_VERSION,
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
    *,
    ai_allowed: bool,
) -> None:
    """Contain processing writes so an unsuccessful attempt cannot alter profile state."""
    try:
        with db.begin_nested():
            _process_response(db, session, question, response, ai_allowed=ai_allowed)
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
    if mark_abandoned_if_stale(db, session):
        db.commit()
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
    _process_or_mark_retry(
        db, session, question, response, "extract_and_select", ai_allowed=sanitized.ai_allowed,
    )
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
    _process_or_mark_retry(
        db,
        session,
        question,
        response,
        "extract_and_select_retry",
        ai_allowed=response.sanitized_model_input != "[SENSITIVE_RESPONSE_WITHHELD]",
    )
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
