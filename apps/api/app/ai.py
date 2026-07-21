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

from roomicheck.v2.config import DIMENSION_IDS
from .prompts import ADAPT_PROMPT, EXTRACT_PROMPT, SUMMARY_PROMPT


class ProviderError(RuntimeError):
    def __init__(self, category: str, *, retryable: bool = False) -> None:
        self.category = category
        self.retryable = retryable
        super().__init__(category)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    contradiction_response_ids: list[str] = Field(default_factory=list, max_length=4)
    _score_override: int | None = PrivateAttr(default=None)


class ExtractionResult(StrictModel):
    dimensions: list[ExtractionDimension] = Field(default_factory=list, max_length=8)


class AdaptedQuestion(StrictModel):
    text: str = Field(min_length=1, max_length=280)


class SummaryResult(StrictModel):
    cross_dimension_insights: list[str] = Field(default_factory=list, max_length=4)
    tradeoffs: list[str] = Field(default_factory=list, max_length=4)
    suggestions: list[str] = Field(default_factory=list, max_length=4)
    overall_summary: str = Field(min_length=1, max_length=1000)


class AdaptiveProvider(Protocol):
    name: str

    def extract(self, payload: dict[str, Any]) -> ExtractionResult: ...
    def adapt_question(self, payload: dict[str, Any]) -> AdaptedQuestion: ...
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
                for dimension in targets[:1]
            ]
        )

    def adapt_question(self, payload: dict[str, Any]) -> AdaptedQuestion:
        return AdaptedQuestion(text=str(payload["bank_question"]))

    def summarize(self, payload: dict[str, Any]) -> SummaryResult:
        dimensions = payload.get("dimensions", {})
        scores = {
            key: value.get("score")
            for key, value in dimensions.items()
            if isinstance(value, dict) and isinstance(value.get("score"), (int, float))
        }
        insights: list[str] = []
        tradeoffs: list[str] = []
        suggestions: list[str] = []

        if scores.get("noise_environment", 50) <= 35 and scores.get("social_interaction", 50) >= 70:
            insights.append("You may want active social connection while still needing the shared home to stay quiet and predictable.")
            tradeoffs.append("A good arrangement may separate social energy from quiet periods in the home.")
            suggestions.append("Set shared quiet hours and agree on where or when guests and group activities fit.")
        if scores.get("study_daily_routine", 50) >= 70 and scores.get("noise_environment", 50) <= 35:
            insights.append("Your focus and quiet preferences reinforce each other, so interruptions may matter most during study or rest windows.")
            suggestions.append("Make study, sleep, and noise expectations explicit before sharing the space.")
        if scores.get("household_structure", 50) >= 70 and scores.get("communication_style", 50) >= 70:
            insights.append("You appear to value both clear household standards and direct communication when those standards need attention.")
            suggestions.append("Use a simple recurring check-in to keep chores and shared expectations visible.")

        if not insights:
            insights.append("The profile is best understood as a combination of preferences that should be discussed together rather than evaluated separately.")
        if not suggestions:
            suggestions.append("Discuss the strongest preferences, uncertainty areas, and practical routines before sharing a home.")

        return SummaryResult(
            cross_dimension_insights=insights,
            tradeoffs=tradeoffs,
            suggestions=suggestions,
            overall_summary="You will likely feel best in a home that gives you privacy but still leaves room to spend time with others. Agree on house rules and talk openly when something is not working.",
        )


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

    def summarize(self, payload: dict[str, Any]) -> SummaryResult:
        result = self._request(
            SUMMARY_PROMPT, payload, SummaryResult,
        )
        return result  # type: ignore[return-value]


def allowed_dimensions(primary: str | None, secondary: list[str]) -> list[str]:
    return list(DIMENSION_IDS) if primary is None else [primary, *secondary]


SUMMARY_FORBIDDEN_TERMS = (
    "good roommate", "bad roommate", "difficult", "antisocial", "incompatible",
    "personality disorder", "diagnosis", "mentally ill",
)


def validate_summary(text: str) -> str:
    candidate = " ".join(text.split())
    lowered = candidate.casefold()
    if not candidate or len(candidate) > 1000:
        raise ProviderError("invalid_summary")
    if any(term in lowered for term in SUMMARY_FORBIDDEN_TERMS):
        raise ProviderError("summary_policy_violation")
    return candidate
