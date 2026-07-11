from __future__ import annotations

from uuid import uuid4

import pytest

from app.ai import ExtractionDimension, ExtractionResult, ProviderError
from app.service import _apply_extraction
from app import models
from roomicheck.v2.models import ProfileV2


def _response(answer: str) -> models.QuestionnaireResponse:
    return models.QuestionnaireResponse(
        id=uuid4(),
        session_id=uuid4(),
        session_question_id=uuid4(),
        idempotency_key=uuid4(),
        raw_response={},
        normalized_response=answer,
        sanitized_model_input=answer,
    )


def _question() -> models.SessionQuestion:
    return models.SessionQuestion(
        id=uuid4(), session_id=uuid4(), question_id="noise_focus_preference", question_order=2,
        exact_question_text="How quiet do you prefer it?", question_type="single_choice",
        primary_dimension="noise_environment", secondary_dimensions=[], options_json=[],
        selection_reason="unknown_dimension:noise_environment", source="bank", confidence_before_json={},
    )


def test_extraction_maps_rubric_label_with_deterministic_math() -> None:
    profile = ProfileV2.empty()
    response, question = _response("I need quiet to study."), _question()
    result = ExtractionResult(dimensions=[ExtractionDimension(
        dimension="noise_environment", label="low", confidence=0.8,
        supporting_quote="I need quiet to study.", summary="Prefers quiet for focused work.",
        preference_strength_known=True, scenario_evidence=True,
    )])
    _apply_extraction(profile, response, question, result)
    state = profile.dimensions["noise_environment"]
    assert state.score == 20
    assert state.confidence == 0.8
    assert state.evidence[0].excerpt == "I need quiet to study."


def test_extraction_rejects_quote_not_present_in_sanitized_answer() -> None:
    profile = ProfileV2.empty()
    result = ExtractionResult(dimensions=[ExtractionDimension(
        dimension="noise_environment", label="high", confidence=0.8,
        supporting_quote="Invented quote", summary="Unsupported.",
    )])
    with pytest.raises(ProviderError, match="invalid_evidence_quote"):
        _apply_extraction(profile, _response("Real answer"), _question(), result)
