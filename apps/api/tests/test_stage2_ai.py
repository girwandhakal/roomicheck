from __future__ import annotations

import urllib.error
import json
from uuid import uuid4

import pytest

from app.ai import (
    AdaptedQuestion,
    ExtractionDimension,
    ExtractionResult,
    GeminiAdaptiveProvider,
    ProviderError,
    SummaryResult,
    validate_summary,
)
from app.service import _apply_extraction, _extraction_answer_payload, _fixed_choice_extraction
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
        weight=0.5,
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


def test_summary_policy_rejects_judgmental_claims() -> None:
    with pytest.raises(ProviderError, match="summary_policy_violation"):
        validate_summary("This person would be a bad roommate.")


def test_extraction_rejects_unknown_contradiction_reference() -> None:
    profile = ProfileV2.empty()
    result = ExtractionResult(dimensions=[ExtractionDimension(
        dimension="noise_environment", label="high", confidence=0.8,
        supporting_quote="Real answer", summary="Conflicts with prior evidence.",
        contradiction_response_ids=[str(uuid4())],
    )])
    with pytest.raises(ProviderError, match="invalid_contradiction_reference"):
        _apply_extraction(profile, _response("Real answer"), _question(), result)


def test_gemini_provider_classifies_rate_limit(monkeypatch) -> None:
    provider = GeminiAdaptiveProvider("test-key", "gemini-test")

    def fail(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://example.test", 429, "quota", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(ProviderError, match="rate_limited"):
        provider.extract({"answer": "quiet", "allowed_dimensions": ["noise_environment"]})


def test_extraction_contract_rejects_unknown_label() -> None:
    with pytest.raises(ValueError):
        ExtractionDimension(
            dimension="noise_environment",
            label="extreme",
            confidence=0.8,
            supporting_quote="quiet",
            summary="Unsupported label.",
        )


def test_extraction_contract_rejects_invalid_weight() -> None:
    with pytest.raises(ValueError):
        ExtractionDimension(
            dimension="noise_environment",
            label="high",
            confidence=0.8,
            weight=0.1,
            supporting_quote="quiet",
            summary="Weight is below the allowed range.",
        )


def test_provider_classifies_malformed_structured_output(monkeypatch) -> None:
    provider = GeminiAdaptiveProvider("test-key", "gemini-test")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"output_text": "not-json"}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    with pytest.raises(ProviderError, match="invalid_structured_output"):
        provider.extract({"answer": "quiet", "allowed_dimensions": ["noise_environment"]})


def test_provider_classifies_timeout_after_retries(monkeypatch) -> None:
    provider = GeminiAdaptiveProvider("test-key", "gemini-test")

    def fail(*_args, **_kwargs):
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    monkeypatch.setattr("time.sleep", lambda *_args: None)
    with pytest.raises(ProviderError, match="network_error"):
        provider.extract({"answer": "quiet", "allowed_dimensions": ["noise_environment"]})


def test_other_ai_contracts_are_strict() -> None:
    with pytest.raises(ValueError):
        AdaptedQuestion(text="")
    with pytest.raises(ValueError):
        SummaryResult(summary="")


def test_privacy_withheld_extraction_does_not_add_evidence() -> None:
    profile = ProfileV2.empty()
    question = _question()
    response = _response("[SENSITIVE_RESPONSE_WITHHELD]")
    from app.service import _mock_extract

    result = _mock_extract(profile, question, response.id, response.sanitized_model_input, False)
    assert result == {"dimensions_updated": [], "withheld": True}
    assert not profile.dimensions["noise_environment"].evidence


def test_extraction_payload_preserves_question_context() -> None:
    question = _question()
    question.options_json = [
        {"id": "quiet", "label": "I need a quiet room."},
        {"id": "other", "label": "Something else."},
    ]
    response = _response("I need a quiet room.")
    response.raw_response = {
        "free_text": None,
        "scale_value": None,
        "selected_option_id": "quiet",
    }
    payload = _extraction_answer_payload(question, response)
    assert payload == {
        "normalized_text": "I need a quiet room.",
        "selected_option_id": "quiet",
        "selected_option_label": "I need a quiet room.",
        "scale_value": None,
    }


def test_known_choice_uses_deterministic_mapping() -> None:
    profile = ProfileV2.empty()
    question = _question()
    question.options_json = [
        {"id": "quiet", "label": "I'd be distracted until the room was quiet."},
        {"id": "other", "label": "Something else."},
    ]
    response = _response("I'd be distracted until the room was quiet.")
    response.raw_response = {
        "free_text": None,
        "scale_value": None,
        "selected_option_id": "quiet",
    }
    extracted = _fixed_choice_extraction(question, response)
    assert extracted is not None
    assert extracted.dimensions[0].label == "low"
    assert extracted.dimensions[0].confidence == 0.95
    _apply_extraction(profile, response, question, extracted)
    assert profile.dimensions["noise_environment"].score == 20
