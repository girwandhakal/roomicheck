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

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    label: Literal["low", "moderate", "high"]
    confidence: float = Field(ge=0, le=1)
    weight: float = Field(default=0.5, ge=0.2, le=1)
    supporting_quote: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=400)
    unknowns: list[str] = Field(default_factory=list, max_length=4)
    clarification_needed: bool = False
    preference_strength_known: bool = False
    scenario_evidence: bool = False
    contradiction_response_ids: list[str] = Field(default_factory=list, max_length=4)


class ExtractionResult(StrictModel):
    dimensions: list[ExtractionDimension] = Field(default_factory=list, max_length=6)


class AdaptedQuestion(StrictModel):
    text: str = Field(min_length=1, max_length=280)


class SummaryResult(StrictModel):
    summary: str = Field(min_length=1, max_length=1000)


class AdaptiveProvider(Protocol):
    name: str

    def extract(self, payload: dict[str, Any]) -> ExtractionResult: ...
    def adapt_question(self, payload: dict[str, Any]) -> AdaptedQuestion: ...
    def summarize(self, payload: dict[str, Any]) -> SummaryResult: ...


LABEL_TO_SCORE = {"low": 20, "moderate": 50, "high": 80}


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
                    confidence=0.55,
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
        return SummaryResult(summary="RoomiCheck recorded evidence across the co-living profile.")


class GeminiAdaptiveProvider:
    """Minimal REST adapter for Gemini Interactions structured output."""

    name: str

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 30.0) -> None:
        self.api_key, self.model, self.timeout_seconds = api_key, model, timeout_seconds
        self.name = f"gemini:{model}"

    def _request(self, instruction: str, payload: dict[str, Any], result_type: type[StrictModel]) -> StrictModel:
        body = {
            "model": self.model.removeprefix("models/"),
            "input": instruction + "\n\nINPUT:\n" + json.dumps(payload, separators=(",", ":")),
            "generation_config": {"temperature": 0.1},
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": result_type.model_json_schema(),
            },
        }
        request = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            data=json.dumps(body).encode("utf-8"),
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            method="POST",
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = json.loads(response.read().decode("utf-8"))
                text = raw.get("output_text")
                if not isinstance(text, str):
                    parts: list[str] = []
                    for step in raw.get("steps", []):
                        if isinstance(step, dict):
                            for content in step.get("content", []):
                                if isinstance(content, dict) and content.get("type") == "text" and isinstance(content.get("text"), str):
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
