from __future__ import annotations

import urllib.error
import json
from uuid import uuid4

import pytest

from app.ai import (
    AdaptiveBundle,
    FallbackAdaptiveProvider,
    AdaptedQuestion,
    ExtractionDimension,
    ExtractionResult,
    OpenAIAdaptiveProvider,
    ProviderError,
    SummaryResult,
    validate_summary,
)
from app.service import (
    _apply_extraction,
    _extraction_answer_payload,
    _fixed_choice_extraction,
    _validate_adaptive_bundle,
)
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
        primary_dimension="physical_environment", secondary_dimensions=["study_daily_routine"], options_json=[],
        selection_reason="unknown_dimension:physical_environment", source="bank", confidence_before_json={},
    )


def test_extraction_maps_rubric_label_with_deterministic_math() -> None:
    profile = ProfileV2.empty()
    response, question = _response("I need quiet to study."), _question()
    result = ExtractionResult(dimensions=[ExtractionDimension(
        dimension="physical_environment", label="very_low", confidence="high",
        weight=0.5,
        supporting_quote="I need quiet to study.", summary="Prefers quiet for focused work.",
        preference_strength_known=True, scenario_evidence=True,
    )])
    _apply_extraction(profile, response, question, result)
    state = profile.dimensions["physical_environment"]
    assert state.score == 10
    assert state.confidence == 0.9
    assert state.evidence[0].excerpt == "I need quiet to study."


def test_extraction_preserves_supported_subdimensions() -> None:
    profile = ProfileV2.empty()
    response, question = _response("I need quiet to study."), _question()
    result = ExtractionResult(dimensions=[ExtractionDimension(
        dimension="physical_environment", label="low", confidence="high",
        weight=1.0, supporting_quote="I need quiet to study.", summary="Quiet matters.",
        subdimensions=[{
            "subdimension": "importance", "label": "very_high", "confidence": "high",
            "weight": 1.0, "supporting_quote": "I need quiet to study.",
            "summary": "Quiet is important for this participant.",
        }],
    )])
    _apply_extraction(profile, response, question, result)
    state = profile.dimensions["physical_environment"].subdimensions["importance"]
    assert state.score == 90
    assert state.label == "very_high"
    assert state.evidence[0].excerpt == "I need quiet to study."


def test_extraction_rejects_quote_not_present_in_sanitized_answer() -> None:
    profile = ProfileV2.empty()
    result = ExtractionResult(dimensions=[ExtractionDimension(
        dimension="physical_environment", label="very_high", confidence="high",
        supporting_quote="Invented quote", summary="Unsupported.",
    )])
    with pytest.raises(ProviderError, match="invalid_evidence_quote"):
        _apply_extraction(profile, _response("Real answer"), _question(), result)


def test_summary_policy_rejects_judgmental_claims() -> None:
    with pytest.raises(ProviderError, match="summary_policy_violation"):
        validate_summary("This person would be a bad roommate.")


def test_summary_policy_rejects_questionnaire_recap() -> None:
    with pytest.raises(ProviderError, match="summary_policy_violation"):
        validate_summary("Based on your answers to the questions, you prefer quiet rooms.")
    with pytest.raises(ProviderError, match="summary_repeats_question"):
        validate_summary(
            "You would feel most at ease when your roommate starts watching videos out loud.",
            ["You're trying to finish an important assignment when your roommate starts watching videos out loud. What would that be like for you?"],
        )


def test_extraction_rejects_unknown_contradiction_reference() -> None:
    profile = ProfileV2.empty()
    result = ExtractionResult(dimensions=[ExtractionDimension(
        dimension="physical_environment", label="very_high", confidence="high",
        supporting_quote="Real answer", summary="Conflicts with prior evidence.",
        contradiction_response_ids=[str(uuid4())],
    )])
    with pytest.raises(ProviderError, match="invalid_contradiction_reference"):
        _apply_extraction(profile, _response("Real answer"), _question(), result)


def test_contradictory_evidence_lowers_confidence_and_requires_clarification() -> None:
    profile = ProfileV2.empty()
    prior = _response("I prefer quiet.")
    prior_question = _question()
    _apply_extraction(profile, prior, prior_question, ExtractionResult(dimensions=[ExtractionDimension(
        dimension="physical_environment", label="low", confidence="high",
        supporting_quote="I prefer quiet.", summary="Quiet is preferred.",
    )]))
    current = _response("I prefer lively background noise.")
    result = ExtractionResult(dimensions=[ExtractionDimension(
        dimension="physical_environment", label="high", confidence="high",
        supporting_quote="I prefer lively background noise.", summary="The answer conflicts with earlier evidence.",
        contradiction_response_ids=[str(prior.id)],
    )])
    _apply_extraction(profile, current, prior_question, result)
    state = profile.dimensions["physical_environment"]
    assert state.confidence == 0.55
    assert state.clarification_needed


def test_openai_provider_classifies_rate_limit(monkeypatch) -> None:
    provider = OpenAIAdaptiveProvider("test-key", "gpt-test")

    def fail(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://example.test", 429, "quota", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(ProviderError, match="rate_limited"):
        provider.extract({"answer": "quiet", "allowed_dimensions": ["physical_environment"]})


def test_extraction_contract_rejects_unknown_label() -> None:
    with pytest.raises(ValueError):
        ExtractionDimension(
            dimension="physical_environment",
            label="extreme",
            confidence="high",
            supporting_quote="quiet",
            summary="Unsupported label.",
        )


def test_extraction_contract_rejects_invalid_weight() -> None:
    with pytest.raises(ValueError):
        ExtractionDimension(
            dimension="physical_environment",
            label="high",
            confidence="high",
            weight=0.1,
            supporting_quote="quiet",
            summary="Weight is below the allowed range.",
        )


def test_provider_classifies_malformed_structured_output(monkeypatch) -> None:
    provider = OpenAIAdaptiveProvider("test-key", "gpt-test")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"output_text": "not-json"}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    with pytest.raises(ProviderError, match="invalid_structured_output"):
        provider.extract({"answer": "quiet", "allowed_dimensions": ["physical_environment"]})


def test_provider_classifies_timeout_after_retries(monkeypatch) -> None:
    provider = OpenAIAdaptiveProvider("test-key", "gpt-test")

    def fail(*_args, **_kwargs):
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    monkeypatch.setattr("time.sleep", lambda *_args: None)
    with pytest.raises(ProviderError, match="network_error"):
        provider.extract({"answer": "quiet", "allowed_dimensions": ["physical_environment"]})


def test_other_ai_contracts_are_strict() -> None:
    with pytest.raises(ValueError):
        AdaptedQuestion(text="")
    with pytest.raises(ValueError):
        SummaryResult(ideal_roommate="")


def test_fallback_summary_describes_the_ideal_roommate_from_dimensions() -> None:
    from app.ai import FallbackAdaptiveProvider

    result = FallbackAdaptiveProvider().summarize({
        "dimensions": {
            "physical_environment": {"summary": "Prefers a quiet, predictable physical environment."},
            "social_interaction": {"score": 80},
        },
        "contradictions": [],
    })

    assert result.ideal_roommate
    assert "quiet" in result.ideal_roommate.lower()
    assert "physical environment:" not in result.ideal_roommate.lower()
    assert "question" not in result.ideal_roommate.lower()


def test_privacy_withheld_extraction_does_not_add_evidence() -> None:
    profile = ProfileV2.empty()
    question = _question()
    response = _response("[SENSITIVE_RESPONSE_WITHHELD]")
    from app.service import _mock_extract

    result = _mock_extract(profile, question, response.id, response.sanitized_model_input, False)
    assert result == {"dimensions_updated": [], "withheld": True}
    assert not profile.dimensions["physical_environment"].evidence


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
    assert extracted.dimensions[0].confidence == "high"
    _apply_extraction(profile, response, question, extracted)
    assert profile.dimensions["physical_environment"].score == 20
    assert profile.dimensions["study_daily_routine"].score == 85


def test_ai_adapted_wording_keeps_source_bank_scoring() -> None:
    question = _question()
    question.exact_question_text = "AI-adapted wording: how would you protect your focus?"
    question.options_json = [
        {"id": "quiet", "label": "I need the room quiet."},
        {"id": "other", "label": "Something else."},
    ]
    response = _response("I need the room quiet.")
    response.raw_response = {
        "free_text": None,
        "scale_value": None,
        "selected_option_id": "quiet",
    }

    extracted = _fixed_choice_extraction(question, response)

    assert extracted is not None
    assert {item.dimension for item in extracted.dimensions} == {
        "physical_environment",
        "study_daily_routine",
    }


def test_fallback_adaptive_bundle_has_multiple_hypotheses_and_cross_dimension_questions() -> None:
    bundle = FallbackAdaptiveProvider().generate_adaptive_bundle({"round": 1, "seed_answer": "quiet"})
    validated = _validate_adaptive_bundle(bundle, answered_texts=set())
    assert isinstance(validated, AdaptiveBundle)
    assert 2 <= len(validated.hypotheses) <= 3
    assert all(2 <= len(item.questions) <= 3 for item in validated.hypotheses)
    assert any(question.secondary_dimensions for item in validated.hypotheses for question in item.questions)


def test_adaptive_bundle_rejects_duplicate_question_text() -> None:
    bundle = FallbackAdaptiveProvider().generate_adaptive_bundle({"round": 1, "seed_answer": "quiet"})
    duplicate_text = bundle.hypotheses[0].questions[0].text
    with pytest.raises(ProviderError, match="duplicate_generated_question_text"):
        _validate_adaptive_bundle(bundle, answered_texts={duplicate_text.casefold()})
