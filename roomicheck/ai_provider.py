from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Any

from .config import DIMENSIONS, load_fallback_followups, load_scoring_rules
from .models import AnswerRecord, ScoreContribution, TurnAnalysis

DEFAULT_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
DEFAULT_MODEL = "gemini-3.5-flash"

CONTRIBUTION_SCHEMA = {
    "type": "object",
    "properties": {
        "dimension": {"type": "string", "enum": list(DIMENSIONS)},
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": {"type": "string"},
    },
    "required": ["dimension", "score", "confidence", "evidence"],
    "additionalProperties": False,
}

TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "contributions": {"type": "array", "items": CONTRIBUTION_SCHEMA},
        "preferences": {"type": "array", "items": {"type": "string"}},
        "dealbreakers": {"type": "array", "items": {"type": "string"}},
        "unresolved": {"type": "boolean"},
        "ask_follow_up": {"type": "boolean"},
        "follow_up_question": {"type": "string"},
        "follow_up_dimension": {"type": "string", "enum": list(DIMENSIONS)},
    },
    "required": [
        "contributions",
        "preferences",
        "dealbreakers",
        "unresolved",
        "ask_follow_up",
        "follow_up_question",
        "follow_up_dimension",
    ],
    "additionalProperties": False,
}

DIMENSION_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "dimension": {"type": "string", "enum": list(DIMENSIONS)},
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "preferences": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["dimension", "score", "confidence", "evidence", "preferences"],
    "additionalProperties": False,
}

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "dimensions": {
            "type": "array",
            "items": DIMENSION_RESULT_SCHEMA,
            "minItems": len(DIMENSIONS),
            "maxItems": len(DIMENSIONS),
        },
        "dealbreakers": {"type": "array", "items": {"type": "string"}},
        "unresolved_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["dimensions", "dealbreakers", "unresolved_questions"],
    "additionalProperties": False,
}


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str = "provider_error", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _extract_output_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    collected: list[str] = []
    for step in payload.get("steps", []):
        if not isinstance(step, dict):
            continue
        for item in step.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                collected.append(item["text"])
    if not collected:
        raise ProviderError("Gemini returned no text output", code="empty_response")
    return "\n".join(collected).strip()


def _clean_strings(values: Any, *, limit: int = 8) -> list[str]:
    if not isinstance(values, list):
        raise ValueError("Expected a list of strings")
    cleaned = []
    for value in values[:limit]:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("List values must be non-empty strings")
        cleaned.append(value.strip()[:300])
    return list(dict.fromkeys(cleaned))


class GeminiProvider:
    """Small REST client for Gemini's Interactions API with structured outputs."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        url: str = DEFAULT_URL,
        timeout: float = 45.0,
        max_retries: int = 1,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")).strip()
        self.model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        self.url = url
        self.timeout = timeout
        self.max_retries = max_retries

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def name(self) -> str:
        return f"gemini:{self.model}"

    def _request_json(self, prompt: str, schema: dict[str, Any], temperature: float) -> dict[str, Any]:
        if not self.available:
            raise ProviderError("GEMINI_API_KEY is not configured", code="missing_api_key")

        payload = {
            "model": self.model,
            "input": prompt,
            "generation_config": {"temperature": temperature},
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": schema,
            },
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "RoomiCheck/0.2",
            },
            method="POST",
        )

        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    response_payload = json.loads(response.read().decode("utf-8"))
                output = json.loads(_extract_output_text(response_payload))
                if not isinstance(output, dict):
                    raise ProviderError("Gemini output was not a JSON object", code="invalid_json")
                return output
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")[:500]
                retryable = error.code in {429, 500, 502, 503, 504}
                if retryable and attempt < self.max_retries:
                    time.sleep(0.5 * (2**attempt))
                    continue
                code = "quota_exhausted" if error.code == 429 else f"http_{error.code}"
                raise ProviderError(f"Gemini request failed ({error.code}): {body}", code=code, retryable=retryable) from error
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt < self.max_retries:
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise ProviderError(f"Gemini could not be reached: {error}", code="network_error", retryable=True) from error
            except json.JSONDecodeError as error:
                raise ProviderError("Gemini returned malformed JSON", code="invalid_json") from error
        raise ProviderError("Gemini request failed", code="provider_error")

    def healthcheck(self) -> dict[str, Any]:
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["ok"]},
                "message": {"type": "string"},
            },
            "required": ["status", "message"],
            "additionalProperties": False,
        }
        return self._request_json(
            "Return status 'ok' and a five-word confirmation that structured output works.",
            schema,
            temperature=0.0,
        )

    def analyze_turn(
        self,
        answer: AnswerRecord,
        prior_answers: list[AnswerRecord],
        *,
        allow_follow_up: bool,
    ) -> TurnAnalysis:
        rules = load_scoring_rules()
        scales = {key: value["scale"] for key, value in rules["dimensions"].items()}
        context = [record.to_ai_dict() for record in prior_answers[-4:]]
        prompt = (
            "You are RoomiCheck's co-living assessment engine. Analyze only the supplied housing habits and boundaries. "
            "Never infer identity, health, protected traits, morality, or overall personality. Score only target_dimensions. "
            "Evidence must be a concise paraphrase grounded in the answer. A dealbreaker requires explicit absolute language. "
            "If follow-ups are allowed, ask one practical, non-sensitive question only when it would materially improve the profile. "
            "Do not ask for names, contact details, addresses, medical information, protected traits, or precise locations. "
            "If no follow-up is needed, set ask_follow_up false and return an empty follow_up_question.\n\n"
            f"Dimension scales:\n{json.dumps(scales, indent=2)}\n\n"
            f"Follow-up allowed: {allow_follow_up}\n"
            f"Recent session context:\n{json.dumps(context, indent=2)}\n\n"
            f"Current answer:\n{json.dumps(answer.to_ai_dict(), indent=2)}"
        )
        payload = self._request_json(prompt, TURN_SCHEMA, temperature=0.35)
        return self._validate_turn(payload, answer, allow_follow_up)

    def _validate_turn(self, payload: dict[str, Any], answer: AnswerRecord, allow_follow_up: bool) -> TurnAnalysis:
        target_dimensions = set(answer.target_dimensions)
        raw_contributions = payload.get("contributions")
        if not isinstance(raw_contributions, list):
            raise ProviderError("Turn analysis omitted contributions", code="semantic_validation")
        contributions: list[ScoreContribution] = []
        seen_dimensions: set[str] = set()
        for item in raw_contributions:
            if not isinstance(item, dict):
                raise ProviderError("Invalid score contribution", code="semantic_validation")
            dimension = item.get("dimension")
            score = item.get("score")
            confidence = item.get("confidence")
            evidence = item.get("evidence")
            if dimension not in target_dimensions or dimension in seen_dimensions:
                raise ProviderError("AI scored an unauthorized or duplicate dimension", code="semantic_validation")
            if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
                raise ProviderError("AI score was out of bounds", code="semantic_validation")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise ProviderError("AI confidence was out of bounds", code="semantic_validation")
            if not isinstance(evidence, str) or not evidence.strip():
                raise ProviderError("AI evidence was empty", code="semantic_validation")
            contribution = ScoreContribution(
                dimension=dimension,
                score=score,
                confidence=float(confidence),
                evidence=evidence.strip()[:300],
                source="ai_interpretation",
                question_id=answer.question_id,
            )
            contribution.validate()
            contributions.append(contribution)
            seen_dimensions.add(dimension)

        ask_follow_up = payload.get("ask_follow_up") is True and allow_follow_up
        follow_up = payload.get("follow_up_question", "")
        follow_up_dimension = payload.get("follow_up_dimension")
        if ask_follow_up:
            if not isinstance(follow_up, str) or not follow_up.strip():
                raise ProviderError("AI requested a follow-up without a question", code="semantic_validation")
            if follow_up_dimension not in target_dimensions:
                raise ProviderError("AI follow-up targeted an unauthorized dimension", code="semantic_validation")

        return TurnAnalysis(
            contributions=contributions,
            preferences=_clean_strings(payload.get("preferences", [])),
            dealbreakers=_clean_strings(payload.get("dealbreakers", [])),
            unresolved=payload.get("unresolved") is True,
            follow_up_question=follow_up.strip() if ask_follow_up else None,
            follow_up_dimension=follow_up_dimension if ask_follow_up else None,
            source="ai",
        )

    def synthesize_profile(self, evidence: dict[str, Any]) -> dict[str, Any]:
        rules = load_scoring_rules()
        scales = {key: value["scale"] for key, value in rules["dimensions"].items()}
        prompt = (
            "Synthesize a RoomiCheck co-living profile from the validated evidence. Return every dimension exactly once. "
            "Use deterministic anchors as stable facts and AI interpretations for nuance. Do not infer protected traits or facts absent "
            "from the evidence. Lower confidence when evidence is sparse or contradictory. Each evidence item must be grounded in the "
            "provided contributions. Scores describe preferences, not quality or desirability.\n\n"
            f"Dimension scales:\n{json.dumps(scales, indent=2)}\n\n"
            f"Validated evidence:\n{json.dumps(evidence, indent=2)}"
        )
        payload = self._request_json(prompt, PROFILE_SCHEMA, temperature=0.2)
        self._validate_profile_payload(payload)
        return payload

    @staticmethod
    def _validate_profile_payload(payload: dict[str, Any]) -> None:
        dimensions = payload.get("dimensions")
        if not isinstance(dimensions, list) or len(dimensions) != len(DIMENSIONS):
            raise ProviderError("AI profile did not contain all dimensions", code="semantic_validation")
        seen: set[str] = set()
        for item in dimensions:
            if not isinstance(item, dict):
                raise ProviderError("Invalid profile dimension", code="semantic_validation")
            dimension = item.get("dimension")
            score = item.get("score")
            confidence = item.get("confidence")
            if dimension not in DIMENSIONS or dimension in seen:
                raise ProviderError("AI profile contained duplicate or unknown dimensions", code="semantic_validation")
            if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
                raise ProviderError("AI profile score was out of bounds", code="semantic_validation")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise ProviderError("AI profile confidence was out of bounds", code="semantic_validation")
            _clean_strings(item.get("evidence", []), limit=5)
            _clean_strings(item.get("preferences", []), limit=5)
            seen.add(dimension)
        _clean_strings(payload.get("dealbreakers", []))
        _clean_strings(payload.get("unresolved_questions", []))


class FallbackProvider:
    """Curated continuity path used only when AI cannot safely complete a turn."""

    name = "curated-fallback"
    available = True

    def __init__(self) -> None:
        self.followups = load_fallback_followups().get("questions", {})

    def analyze_turn(
        self,
        answer: AnswerRecord,
        prior_answers: list[AnswerRecord],
        *,
        allow_follow_up: bool,
    ) -> TurnAnalysis:
        del prior_answers
        question_rules = self.followups.get(answer.question_id, {})
        option_followups = question_rules.get("options", {})
        follow_up = option_followups.get(answer.selected_option_id) or question_rules.get("default")
        target = answer.target_dimensions[0] if answer.target_dimensions else None
        contributions = []
        if answer.selected_option_id is None and answer.ai_allowed:
            for dimension in answer.target_dimensions:
                score = self._heuristic_score(dimension, answer.answer)
                contributions.append(
                    ScoreContribution(
                        dimension=dimension,
                        score=score,
                        confidence=0.55,
                        evidence=answer.answer[:300],
                        source="fallback_text_rule",
                        question_id=answer.question_id,
                    )
                )
        explicit_boundary = bool(
            re.search(
                r"\b(?:dealbreaker|firm boundary|strictly against|never (?:allow|accept|okay|comfortable)|no overnight guests)\b",
                answer.answer,
                re.I,
            )
        )
        return TurnAnalysis(
            contributions=contributions,
            preferences=[answer.answer[:300]] if answer.selected_option_id is None and answer.ai_allowed else [],
            dealbreakers=[answer.answer[:300]] if explicit_boundary else [],
            unresolved=not answer.ai_allowed,
            follow_up_question=follow_up if allow_follow_up and follow_up else None,
            follow_up_dimension=target if allow_follow_up and follow_up else None,
            source="fallback",
        )

    @staticmethod
    def _heuristic_score(dimension: str, text: str) -> int:
        value = text.casefold()
        high_patterns = {
            "living_and_cleanliness": r"same day|stay clear|clean|neat|on schedule",
            "studying_and_sleep_habits": r"silence|quiet|dark|early|after 11|after midnight|headphones",
            "socializing_and_guests": r"love having|frequent guests|whenever|highly social",
            "sharing_space_and_boundaries": r"permission|firm boundary|must ask|advance notice|two days|maximum",
            "communication_and_conflict_handling": r"face-to-face|direct|calm.*conversation|talk.*before|promptly",
        }
        low_patterns = {
            "living_and_cleanliness": r"unbothered|whenever|messy|can wait",
            "studying_and_sleep_habits": r"heavy sleeper|doesn't bother|do not mind|up late",
            "socializing_and_guests": r"never|strictly against|private|no guests",
            "sharing_space_and_boundaries": r"share everything|use whatever|do not mind sharing",
            "communication_and_conflict_handling": r"avoid|hide|wouldn't say|leave instead",
        }
        if re.search(high_patterns.get(dimension, r"$^"), value):
            return 5 if dimension == "communication_and_conflict_handling" else 4
        if re.search(low_patterns.get(dimension, r"$^"), value):
            return 1 if dimension in {"socializing_and_guests", "communication_and_conflict_handling"} else 2
        return 3


class ResilientAI:
    def __init__(self, primary: GeminiProvider | None = None, fallback: FallbackProvider | None = None) -> None:
        self.primary = primary or GeminiProvider()
        self.fallback = fallback or FallbackProvider()
        self.fallback_count = 0
        self.errors: list[str] = []

    @property
    def provider_name(self) -> str:
        return self.primary.name if self.primary.available else self.fallback.name

    @property
    def ai_available(self) -> bool:
        return self.primary.available

    def analyze_turn(
        self,
        answer: AnswerRecord,
        prior_answers: list[AnswerRecord],
        *,
        allow_follow_up: bool,
    ) -> TurnAnalysis:
        if self.primary.available and answer.ai_allowed:
            try:
                return self.primary.analyze_turn(answer, prior_answers, allow_follow_up=allow_follow_up)
            except (ProviderError, ValueError) as error:
                code = error.code if isinstance(error, ProviderError) else "validation_error"
                self.errors.append(code)
        elif not answer.ai_allowed:
            self.errors.append("privacy_withheld")
        else:
            self.errors.append("missing_api_key")
        self.fallback_count += 1
        return self.fallback.analyze_turn(answer, prior_answers, allow_follow_up=allow_follow_up)

    def synthesize_profile(self, evidence: dict[str, Any]) -> dict[str, Any] | None:
        if not self.primary.available:
            self.fallback_count += 1
            return None
        try:
            return self.primary.synthesize_profile(evidence)
        except (ProviderError, ValueError) as error:
            code = error.code if isinstance(error, ProviderError) else "validation_error"
            self.errors.append(code)
            self.fallback_count += 1
            return None

    def telemetry(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "ai_available": self.ai_available,
            "fallback_count": self.fallback_count,
            "fallback_reasons": list(self.errors),
        }
