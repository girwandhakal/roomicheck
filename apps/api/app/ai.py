"""Stage 2 AI contracts and provider adapters.

The provider interprets a single sanitized response.  All profile arithmetic and
control flow remain in the service layer.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError

from roomicheck.v2.config import DIMENSION_IDS, SUBDIMENSION_IDS
from .prompts import ADAPT_PROMPT, EXTRACT_PROMPT, SUMMARY_PROMPT


class ProviderError(RuntimeError):
    def __init__(self, category: str, *, retryable: bool = False) -> None:
        self.category = category
        self.retryable = retryable
        super().__init__(category)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubdimensionExtraction(StrictModel):
    subdimension: Literal[
        "actual_behavior", "personal_preference", "importance", "flexibility"
    ]
    label: Literal["very_low", "low", "moderate", "high", "very_high"]
    confidence: Literal["low", "moderate", "high"]
    weight: float = Field(default=0.5, ge=0.2, le=1)
    supporting_quote: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=400)


class ExtractionDimension(StrictModel):
    dimension: str
    label: Literal["very_low", "low", "moderate", "high", "very_high"]
    confidence: Literal["low", "moderate", "high"]
    weight: float = Field(default=0.5, ge=0.2, le=1)
    supporting_quote: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=400)
    unknowns: list[str] = Field(default_factory=list, max_length=4)
    clarification_needed: bool = False
    preference_strength_known: bool = False
    scenario_evidence: bool = False
    subdimensions: list[SubdimensionExtraction] = Field(default_factory=list, max_length=4)
    contradiction_response_ids: list[str] = Field(default_factory=list, max_length=4)
    _score_override: int | None = PrivateAttr(default=None)


class ExtractionResult(StrictModel):
    dimensions: list[ExtractionDimension] = Field(default_factory=list, max_length=8)


class AdaptedQuestion(StrictModel):
    text: str = Field(min_length=1, max_length=280)


class QuestionOption(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=180)


class AdaptiveQuestion(StrictModel):
    id: str = Field(min_length=1, max_length=96)
    text: str = Field(min_length=1, max_length=280)
    question_type: Literal["scenario", "single_choice", "free_text"] = "scenario"
    options: list[QuestionOption] = Field(default_factory=list, max_length=5)
    primary_dimension: str
    secondary_dimensions: list[str] = Field(default_factory=list, max_length=7)
    target_subdimensions: list[Literal[
        "actual_behavior", "personal_preference", "importance", "flexibility"
    ]] = Field(default_factory=list, max_length=4)
    rationale: str = Field(min_length=1, max_length=400)
    evidence_gap: str = Field(min_length=1, max_length=280)


class AdaptiveHypothesis(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    statement: str = Field(min_length=1, max_length=400)
    evidence_response_ids: list[str] = Field(default_factory=list, max_length=8)
    aligned_dimensions: list[str] = Field(default_factory=list, max_length=8)
    conflicting_dimensions: list[str] = Field(default_factory=list, max_length=8)
    target_subdimensions: list[Literal[
        "actual_behavior", "personal_preference", "importance", "flexibility"
    ]] = Field(default_factory=list, max_length=4)
    alternative_explanation: str = Field(min_length=1, max_length=400)
    discriminating_evidence_gap: str = Field(min_length=1, max_length=280)
    confidence: Literal["low", "moderate", "high"]
    priority: int = Field(ge=1, le=3)
    questions: list[AdaptiveQuestion] = Field(min_length=2, max_length=3)


class AdaptiveBundle(StrictModel):
    hypotheses: list[AdaptiveHypothesis] = Field(min_length=2, max_length=3)


class SummaryResult(StrictModel):
    ideal_roommate: str = Field(min_length=1, max_length=1000)


class AdaptiveProvider(Protocol):
    name: str

    def extract(self, payload: dict[str, Any]) -> ExtractionResult: ...
    def adapt_question(self, payload: dict[str, Any]) -> AdaptedQuestion: ...
    def generate_adaptive_bundle(self, payload: dict[str, Any]) -> AdaptiveBundle: ...
    def summarize(self, payload: dict[str, Any]) -> SummaryResult: ...


LABEL_TO_SCORE = {"very_low": 10, "low": 20, "moderate": 50, "high": 80, "very_high": 90}
CONFIDENCE_TO_SCORE = {"low": 0.4, "moderate": 0.65, "high": 0.9}


def _strict_schema(model: type[StrictModel]) -> dict[str, Any]:
    """Make Pydantic defaulted fields explicit for strict JSON-schema output."""
    schema = model.model_json_schema()

    def normalize(node: Any) -> None:
        if not isinstance(node, dict):
            return
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["required"] = list(properties)
        for value in node.values():
            if isinstance(value, (dict, list)):
                normalize(value)

    normalize(schema)
    return schema


@dataclass
class FallbackAdaptiveProvider:
    name: str = "curated-fallback"

    def extract(self, payload: dict[str, Any]) -> ExtractionResult:
        answer_payload = payload["answer"]
        answer = (
            str(answer_payload.get("normalized_text", "")).strip()
            if isinstance(answer_payload, dict)
            else str(answer_payload).strip()
        )
        targets = payload["allowed_dimensions"]
        # The fallback deliberately stays low-confidence and neutral; it never
        # manufactures semantic traits from free text.
        return ExtractionResult(
            dimensions=[
                ExtractionDimension(
                    dimension=dimension,
                    label="moderate",
                    confidence="moderate",
                    weight=0.5,
                    supporting_quote=answer[:500],
                    summary="A response was recorded for this co-living dimension.",
                    unknowns=["Preference strength requires clarification."],
                    clarification_needed=True,
                    preference_strength_known=False,
                    scenario_evidence=False,
                )
                for dimension in targets
            ]
        )

    def adapt_question(self, payload: dict[str, Any]) -> AdaptedQuestion:
        return AdaptedQuestion(text=str(payload["bank_question"]))

    def generate_adaptive_bundle(self, payload: dict[str, Any]) -> AdaptiveBundle:
        answer = str(payload.get("seed_answer", "")).strip() or "the participant's shared-home preferences"
        round_number = int(payload.get("round", 1))
        first = AdaptiveHypothesis(
            id="h_alignment",
            statement="The participant's response reflects a stable preference that may affect both daily routines and shared-space expectations.",
            evidence_response_ids=list(payload.get("response_ids", []))[-2:],
            aligned_dimensions=["physical_environment", "study_daily_routine", "household_structure"],
            conflicting_dimensions=[],
            target_subdimensions=["personal_preference", "importance"],
            alternative_explanation="The preference may matter only in high-pressure or unusually busy situations.",
            discriminating_evidence_gap="How strongly should this preference shape shared-home agreements?",
            confidence="moderate",
            priority=1,
            questions=[
                AdaptiveQuestion(
                    id="alignment_scenario",
                    text="When a shared-home condition affects your focus or comfort, what response would feel most natural to you?",
                    question_type="single_choice",
                    options=[
                        QuestionOption(id="adjust", label="I would make a small adjustment and keep going."),
                        QuestionOption(id="agreement", label="I would want us to agree on a clear shared expectation."),
                        QuestionOption(id="separate", label="I would use another space or change my plans."),
                        QuestionOption(id="depends", label="It would depend on how important the situation was."),
                        QuestionOption(id="other", label="Something else."),
                    ],
                    primary_dimension="physical_environment",
                    secondary_dimensions=["study_daily_routine", "rule_flexibility"],
                    target_subdimensions=["personal_preference", "flexibility"],
                    rationale="Tests whether the reported preference generalizes across environment, routine, and rules.",
                    evidence_gap="Preferred response and flexibility in a shared condition.",
                ),
                AdaptiveQuestion(
                    id="alignment_importance",
                    text="How much would it matter if a roommate could not consistently meet that preference?",
                    question_type="single_choice",
                    options=[
                        QuestionOption(id="low", label="I could adapt without much difficulty."),
                        QuestionOption(id="moderate", label="It would matter, but we could work around it."),
                        QuestionOption(id="high", label="It would be important to set a reliable agreement."),
                        QuestionOption(id="depends", label="It would depend on the specific situation."),
                        QuestionOption(id="other", label="Something else."),
                    ],
                    primary_dimension="study_daily_routine",
                    secondary_dimensions=["physical_environment", "household_structure"],
                    target_subdimensions=["importance", "flexibility"],
                    rationale="Separates preference strength from the existence of a preference.",
                    evidence_gap="Importance and willingness to adapt.",
                ),
            ],
        )
        second = AdaptiveHypothesis(
            id="h_conflict",
            statement="The response may conflict with earlier answers by indicating different expectations for private time, communication, or changing rules.",
            evidence_response_ids=list(payload.get("response_ids", []))[-4:],
            aligned_dimensions=["personal_boundaries", "communication_style"],
            conflicting_dimensions=["social_interaction", "rule_flexibility"],
            target_subdimensions=["actual_behavior", "flexibility"],
            alternative_explanation="The apparent conflict may be context-dependent rather than a stable contradiction.",
            discriminating_evidence_gap="Whether the participant prefers a consistent boundary or a case-by-case compromise.",
            confidence="moderate",
            priority=2,
            questions=[
                AdaptiveQuestion(
                    id="conflict_boundary",
                    text="If a roommate's needs differed from yours, how would you prefer to work out the shared-space arrangement?",
                    question_type="single_choice",
                    options=[
                        QuestionOption(id="direct", label="Talk about it directly and agree on a plan."),
                        QuestionOption(id="trial", label="Try a temporary compromise and revisit it."),
                        QuestionOption(id="separate", label="Keep some activities or belongings separate."),
                        QuestionOption(id="flexible", label="Handle each situation as it comes up."),
                        QuestionOption(id="other", label="Something else."),
                    ],
                    primary_dimension="personal_boundaries",
                    secondary_dimensions=["communication_style", "rule_flexibility", "social_interaction"],
                    target_subdimensions=["personal_preference", "flexibility"],
                    rationale="Distinguishes boundary needs from communication and flexibility preferences.",
                    evidence_gap="Preferred conflict response across boundaries and shared activity.",
                ),
                AdaptiveQuestion(
                    id="conflict_behavior",
                    text="When a shared agreement becomes inconvenient, what are you most likely to do first?",
                    question_type="single_choice",
                    options=[
                        QuestionOption(id="keep", label="Follow it unless we formally change it together."),
                        QuestionOption(id="ask", label="Ask before making a temporary change."),
                        QuestionOption(id="adjust", label="Adapt it to the circumstances."),
                        QuestionOption(id="pause", label="Wait and see whether the issue continues."),
                        QuestionOption(id="other", label="Something else."),
                    ],
                    primary_dimension="rule_flexibility",
                    secondary_dimensions=["communication_style", "household_structure", "personal_boundaries"],
                    target_subdimensions=["actual_behavior", "flexibility"],
                    rationale="Tests behavior and rule flexibility while preserving the conflict alternative.",
                    evidence_gap="Reported behavior when agreements and circumstances conflict.",
                ),
            ],
        )
        if round_number > 1:
            suffix = " If it happened repeatedly, would your answer change?"
            first = first.model_copy(update={
                "id": f"{first.id}_r{round_number}",
                "questions": [
                    question.model_copy(update={
                        "id": f"{question.id}_r{round_number}",
                        "text": (question.text + suffix)[:280],
                    }) for question in first.questions
                ],
            })
            second = second.model_copy(update={
                "id": f"{second.id}_r{round_number}",
                "questions": [
                    question.model_copy(update={
                        "id": f"{question.id}_r{round_number}",
                        "text": (question.text + suffix)[:280],
                    }) for question in second.questions
                ],
            })
        return AdaptiveBundle(hypotheses=[first, second])

    def summarize(self, payload: dict[str, Any]) -> SummaryResult:
        dimensions = payload.get("dimensions", {})
        summaries = [
            value.get("summary", "").strip()
            for value in dimensions.values()
            if isinstance(value, dict) and isinstance(value.get("summary"), str)
            and value.get("summary", "").strip()
            and "response was recorded" not in value.get("summary", "").casefold()
        ]
        labels = [
            value.get("label", "").replace("_", " ")
            for value in dimensions.values()
            if isinstance(value, dict) and isinstance(value.get("label"), str)
            and value.get("label", "").strip()
        ]
        first = summaries[0][:180] if summaries else "a home that feels comfortable and respectful"
        second = summaries[1][:180] if len(summaries) > 1 else "room for both shared time and personal space"
        intensity = ""
        if labels:
            intensity = f" You tend to have clear preferences around {labels[0]}, while still leaving room for context."
        ideal = (
            f"You are likely to feel most at ease with a roommate who helps create {first.lower().rstrip('.')}. "
            f"Day to day, it would help to live with someone who understands {second.lower().rstrip('.')} "
            "and can talk through differences without turning them into a bigger problem. "
            f"{intensity.strip()} The best fit is a shared home that feels considerate, practical, and easy to adjust when life changes."
        )
        return SummaryResult(ideal_roommate=" ".join(ideal.split())[:1000])


class OpenAIAdaptiveProvider:
    """Minimal REST adapter for OpenAI Responses API structured output."""

    name: str

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 30.0) -> None:
        self.api_key, self.model, self.timeout_seconds = api_key, model, timeout_seconds
        self.name = f"openai:{model}"

    def _request(self, instruction: str, payload: dict[str, Any], result_type: type[StrictModel]) -> StrictModel:
        body = {
            "model": self.model,
            "input": instruction + "\n\nINPUT:\n" + json.dumps(payload, separators=(",", ":")),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": result_type.__name__.lower(),
                    "strict": True,
                    "schema": _strict_schema(result_type),
                },
            },
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = json.loads(response.read().decode("utf-8"))
                text = raw.get("output_text")
                if not isinstance(text, str):
                    parts: list[str] = []
                    for item in raw.get("output", []):
                        if isinstance(item, dict):
                            for content in item.get("content", []):
                                if isinstance(content, dict) and content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                                    parts.append(content["text"])
                    text = "\n".join(parts) if parts else None
                if not isinstance(text, str):
                    raise ProviderError("empty_response")
                return result_type.model_validate_json(text)
            except urllib.error.HTTPError as error:
                retryable = error.code in {429, 500, 502, 503, 504}
                if retryable and attempt < 2:
                    time.sleep(0.25 * (2**attempt))
                    continue
                raise ProviderError("rate_limited" if error.code == 429 else "provider_http", retryable=retryable) from error
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt < 2:
                    time.sleep(0.25 * (2**attempt))
                    continue
                raise ProviderError("network_error", retryable=True) from error
            except (json.JSONDecodeError, ValidationError) as error:
                raise ProviderError("invalid_structured_output") from error
        raise ProviderError("provider_error")

    def extract(self, payload: dict[str, Any]) -> ExtractionResult:
        result = self._request(
            EXTRACT_PROMPT, payload, ExtractionResult,
        )
        return result  # type: ignore[return-value]

    def adapt_question(self, payload: dict[str, Any]) -> AdaptedQuestion:
        result = self._request(
            ADAPT_PROMPT, payload, AdaptedQuestion,
        )
        return result  # type: ignore[return-value]

    def generate_adaptive_bundle(self, payload: dict[str, Any]) -> AdaptiveBundle:
        result = self._request(ADAPTIVE_BUNDLE_PROMPT, payload, AdaptiveBundle)
        return result  # type: ignore[return-value]

    def summarize(self, payload: dict[str, Any]) -> SummaryResult:
        result = self._request(
            SUMMARY_PROMPT, payload, SummaryResult,
        )
        return result  # type: ignore[return-value]


def allowed_dimensions(primary: str | None, secondary: list[str]) -> list[str]:
    return list(DIMENSION_IDS) if primary is None else [primary, *secondary]


SUMMARY_FORBIDDEN_TERMS = (
    "good roommate", "bad roommate", "difficult", "antisocial", "incompatible",
    "personality disorder", "diagnosis", "mentally ill", "the questionnaire", "the questions",
    "your answers", "your responses", "the dimensions", "the subdimensions", "based on your",
)


def validate_summary(text: str, question_texts: list[str] | None = None) -> str:
    candidate = " ".join(text.split())
    lowered = candidate.casefold()
    if not candidate or len(candidate) > 1000:
        raise ProviderError("invalid_summary")
    if any(term in lowered for term in SUMMARY_FORBIDDEN_TERMS):
        raise ProviderError("summary_policy_violation")
    if "?" in candidate or "ideal_roommate:" in lowered:
        raise ProviderError("summary_format_violation")
    normalized_summary = " ".join(lowered.split())
    for question in question_texts or []:
        normalized_question = " ".join(question.casefold().split())
        if len(normalized_question) >= 40 and normalized_question in normalized_summary:
            raise ProviderError("summary_repeats_question")
        question_tokens = normalized_question.replace("?", "").split()
        summary_tokens = normalized_summary.replace("?", "").split()
        question_shingles = {
            " ".join(question_tokens[index:index + 5])
            for index in range(max(0, len(question_tokens) - 4))
        }
        if any(
            " ".join(summary_tokens[index:index + 5]) in question_shingles
            for index in range(max(0, len(summary_tokens) - 4))
        ):
            raise ProviderError("summary_repeats_question")
    return candidate
