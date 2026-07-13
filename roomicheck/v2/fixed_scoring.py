from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import DIMENSION_IDS


ROOT_DIR = Path(__file__).resolve().parents[2]
SCORING_PATH = ROOT_DIR / "questionnaire" / "scoring_rules.v2.json"


@dataclass(frozen=True)
class FixedScoreEffect:
    score: int
    label: str
    confidence: float
    summary: str

    def validate(self, dimension: str) -> None:
        if dimension not in DIMENSION_IDS:
            raise ValueError(f"Unknown fixed scoring dimension: {dimension}")
        if not isinstance(self.score, int) or isinstance(self.score, bool) or not 0 <= self.score <= 100:
            raise ValueError(f"Fixed score for {dimension} must be between 0 and 100")
        if self.label not in {"low", "moderate", "high"}:
            raise ValueError(f"Fixed label for {dimension} is invalid")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Fixed confidence for {dimension} is invalid")
        if not self.summary.strip() or len(self.summary) > 400:
            raise ValueError(f"Fixed summary for {dimension} is invalid")


@lru_cache(maxsize=1)
def load_fixed_scoring_rules() -> dict[str, Any]:
    payload = json.loads(SCORING_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"scoring_version", "scales", "options"}:
        raise ValueError("Fixed scoring rules must contain scoring_version, scales, and options")
    if payload["scoring_version"] != "co_living_scoring.v2":
        raise ValueError("Unexpected fixed scoring version")
    raw_options = payload["options"]
    if not isinstance(raw_options, dict):
        raise ValueError("Fixed scoring options must be an object")
    raw_scales = payload["scales"]
    if not isinstance(raw_scales, dict):
        raise ValueError("Fixed scoring scales must be an object")

    rules: dict[str, dict[str, dict[str, FixedScoreEffect]]] = {}
    for question_id, raw_question in raw_options.items():
        if not isinstance(raw_question, dict):
            raise ValueError(f"Fixed scoring options for {question_id} must be an object")
        rules[question_id] = {}
        for option_id, raw_effects in raw_question.items():
            if not isinstance(raw_effects, dict) or not raw_effects:
                raise ValueError(f"Fixed scoring option {question_id}/{option_id} must have effects")
            rules[question_id][option_id] = {}
            for dimension, raw_effect in raw_effects.items():
                if not isinstance(raw_effect, dict) or set(raw_effect) != {"score", "label", "confidence", "summary"}:
                    raise ValueError(f"Fixed scoring effect {question_id}/{option_id}/{dimension} is invalid")
                effect = FixedScoreEffect(**raw_effect)
                effect.validate(dimension)
                rules[question_id][option_id][dimension] = effect
    scales: dict[str, dict[str, dict[str, FixedScoreEffect]]] = {}
    for question_id, raw_question in raw_scales.items():
        if not isinstance(raw_question, dict):
            raise ValueError(f"Fixed scoring scales for {question_id} must be an object")
        scales[question_id] = {}
        for scale_value, raw_effects in raw_question.items():
            if not isinstance(raw_effects, dict) or not raw_effects:
                raise ValueError(f"Fixed scoring scale {question_id}/{scale_value} must have effects")
            scales[question_id][scale_value] = {}
            for dimension, raw_effect in raw_effects.items():
                if not isinstance(raw_effect, dict) or set(raw_effect) != {"score", "label", "confidence", "summary"}:
                    raise ValueError(f"Fixed scoring effect {question_id}/{scale_value}/{dimension} is invalid")
                effect = FixedScoreEffect(**raw_effect)
                effect.validate(dimension)
                scales[question_id][scale_value][dimension] = effect
    return {"options": rules, "scales": scales}


def fixed_option_effects(
    question_id: str,
    option_id: str | None,
    allowed_dimensions: list[str],
) -> dict[str, FixedScoreEffect] | None:
    if not option_id:
        return None
    effects = load_fixed_scoring_rules()["options"].get(question_id, {}).get(option_id)
    if effects is None:
        return None
    unauthorized = set(effects) - set(allowed_dimensions)
    if unauthorized:
        raise ValueError(f"Fixed scoring rule targets unauthorized dimensions: {sorted(unauthorized)}")
    return effects


def fixed_scale_effects(
    question_id: str,
    scale_value: int | None,
    allowed_dimensions: list[str],
) -> dict[str, FixedScoreEffect] | None:
    if scale_value is None:
        return None
    effects = load_fixed_scoring_rules()["scales"].get(question_id, {}).get(str(scale_value))
    if effects is None:
        return None
    unauthorized = set(effects) - set(allowed_dimensions)
    if unauthorized:
        raise ValueError(f"Fixed scoring rule targets unauthorized dimensions: {sorted(unauthorized)}")
    return effects
