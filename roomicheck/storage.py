from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .models import CoLivingProfile, utc_now


def save_profile(profile: CoLivingProfile, output_dir: Path | None = None) -> Path:
    directory = output_dir or DATA_DIR / "profiles"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{profile.session_id}.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(profile.to_dict(), indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return destination


def save_feedback(
    profile: CoLivingProfile,
    accuracy_rating: int,
    notes: str = "",
    output_dir: Path | None = None,
) -> Path:
    if not 1 <= accuracy_rating <= 5:
        raise ValueError("Accuracy rating must be between 1 and 5")
    directory = output_dir or DATA_DIR / "feedback"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "profile_feedback.jsonl"
    record: dict[str, Any] = {
        "session_id": profile.session_id,
        "created_at": utc_now(),
        "profile_version": profile.profile_version,
        "scoring_version": profile.scoring_version,
        "profile_origin": profile.profile_origin,
        "accuracy_rating": accuracy_rating,
        "notes": notes.strip()[:1000],
    }
    with destination.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record) + "\n")
    return destination

