from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
QUESTIONNAIRE_DIR = ROOT_DIR / "questionnaire"

PROFILE_SCHEMA_VERSION = "co_living_profile.v4"
QUESTIONNAIRE_VERSION = "adaptive_demo.v4"
DIMENSION_DEFINITION_VERSION = "v4"

# These fixed questions are inserted before adaptive follow-ups for every
# questionnaire session. Keep the order stable because it is part of the
# participant experience and the audit trail.
REQUIRED_QUESTION_IDS = (
    "noise_focus_preference",
    "temperature_preference",
    "light_preference",
)

DIMENSION_IDS = (
    "physical_environment",
    "social_interaction",
    "study_daily_routine",
    "cultural_openness",
    "household_structure",
    "personal_boundaries",
    "communication_style",
    "rule_flexibility",
)


def _require_exact_keys(payload: dict[str, Any], expected: set[str], context: str) -> None:
    actual = set(payload)
    if actual != expected:
        raise ValueError(
            f"{context} fields mismatch; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


@dataclass(frozen=True)
class DimensionDefinition:
    id: str
    label: str
    description: str
    score_low: str
    score_high: str

    def validate(self) -> None:
        if self.id not in DIMENSION_IDS:
            raise ValueError(f"Unknown v2 dimension: {self.id}")
        for field_name in ("label", "description", "score_low", "score_high"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Dimension {self.id} has an empty {field_name}")


@lru_cache(maxsize=1)
def load_dimension_definitions() -> dict[str, DimensionDefinition]:
    path = QUESTIONNAIRE_DIR / "dimensions.v2.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Dimension definitions must be a JSON object")
    _require_exact_keys(payload, {"version", "profile_schema", "dimensions"}, "dimension file")
    if payload["version"] != DIMENSION_DEFINITION_VERSION:
        raise ValueError("Unexpected dimension definition version")
    if payload["profile_schema"] != PROFILE_SCHEMA_VERSION:
        raise ValueError("Dimension file targets the wrong profile schema")
    if not isinstance(payload["dimensions"], list):
        raise ValueError("dimensions must be a list")

    definitions: dict[str, DimensionDefinition] = {}
    for index, raw in enumerate(payload["dimensions"]):
        if not isinstance(raw, dict):
            raise ValueError(f"dimensions[{index}] must be an object")
        _require_exact_keys(
            raw,
            {"id", "label", "description", "score_low", "score_high"},
            f"dimensions[{index}]",
        )
        definition = DimensionDefinition(**raw)
        definition.validate()
        if definition.id in definitions:
            raise ValueError(f"Duplicate dimension: {definition.id}")
        definitions[definition.id] = definition

    if tuple(definitions) != DIMENSION_IDS:
        raise ValueError("Dimension definitions must use the canonical v2 order")
    return definitions


def load_question_bank_payload() -> dict[str, Any]:
    path = QUESTIONNAIRE_DIR / "question_bank.v2.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Question bank must be a JSON object")
    return payload
