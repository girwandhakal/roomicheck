from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
QUESTIONNAIRE_DIR = ROOT_DIR / "questionnaire"
DATA_DIR = ROOT_DIR / "data"
ENV_FILES = (ROOT_DIR / ".env.local", ROOT_DIR / ".env")

DIMENSIONS = (
    "living_and_cleanliness",
    "studying_and_sleep_habits",
    "socializing_and_guests",
    "sharing_space_and_boundaries",
    "communication_and_conflict_handling",
)

DIMENSION_LABELS = {
    "living_and_cleanliness": "Living & Cleanliness",
    "studying_and_sleep_habits": "Studying & Sleep Habits",
    "socializing_and_guests": "Socializing & Guests",
    "sharing_space_and_boundaries": "Sharing Space & Boundaries",
    "communication_and_conflict_handling": "Communication & Conflict",
}


def load_env_files() -> None:
    for env_path in ENV_FILES:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ[key] = value


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def load_questions() -> list[dict[str, Any]]:
    payload = load_json(QUESTIONNAIRE_DIR / "seed_questions.v1.json")
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("The seed questionnaire must contain at least one question")
    return questions


def load_scoring_rules() -> dict[str, Any]:
    return load_json(QUESTIONNAIRE_DIR / "scoring_rules.v1.json")


def load_fallback_followups() -> dict[str, Any]:
    return load_json(QUESTIONNAIRE_DIR / "fallback_followups.v1.json")

