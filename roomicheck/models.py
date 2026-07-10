from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .config import DIMENSIONS


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class PrivacyEvent:
    category: str
    action: str
    count: int = 1


@dataclass(frozen=True)
class ScoreContribution:
    dimension: str
    score: int
    confidence: float
    evidence: str
    source: str
    question_id: str

    def validate(self) -> None:
        if self.dimension not in DIMENSIONS:
            raise ValueError(f"Unknown dimension: {self.dimension}")
        if not 1 <= self.score <= 5:
            raise ValueError("Scores must be between 1 and 5")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        if not self.evidence.strip():
            raise ValueError("Score evidence cannot be empty")


@dataclass
class AnswerRecord:
    question_id: str
    prompt: str
    answer: str
    target_dimensions: list[str]
    selected_option_id: str | None = None
    is_follow_up: bool = False
    privacy_events: list[PrivacyEvent] = field(default_factory=list)
    ai_allowed: bool = True

    def to_ai_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.prompt,
            "answer": self.answer,
            "target_dimensions": self.target_dimensions,
            "selected_option_id": self.selected_option_id,
            "is_follow_up": self.is_follow_up,
        }


@dataclass
class TurnAnalysis:
    contributions: list[ScoreContribution] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    dealbreakers: list[str] = field(default_factory=list)
    unresolved: bool = False
    follow_up_question: str | None = None
    follow_up_dimension: str | None = None
    source: str = "fallback"


@dataclass
class DimensionProfile:
    score: int
    confidence: float
    evidence: list[str]
    preferences: list[str]

    def validate(self) -> None:
        if not 1 <= self.score <= 5:
            raise ValueError("Dimension scores must be between 1 and 5")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Dimension confidence must be between 0.0 and 1.0")
        if not self.evidence:
            raise ValueError("Every dimension requires evidence")


@dataclass
class CoLivingProfile:
    dimensions: dict[str, DimensionProfile]
    dealbreakers: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    privacy_events: list[PrivacyEvent] = field(default_factory=list)
    profile_version: str = "v1"
    scoring_version: str = "v1"
    profile_origin: str = "fallback_scored"
    provider: str = "offline"
    fallback_count: int = 0
    session_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: str = field(default_factory=utc_now)

    def validate(self) -> None:
        if set(self.dimensions) != set(DIMENSIONS):
            missing = set(DIMENSIONS) - set(self.dimensions)
            extra = set(self.dimensions) - set(DIMENSIONS)
            raise ValueError(f"Profile dimensions mismatch; missing={missing}, extra={extra}")
        for dimension in self.dimensions.values():
            dimension.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "profile_version": self.profile_version,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "profile_origin": self.profile_origin,
            "provider": self.provider,
            "fallback_count": self.fallback_count,
            "dimensions": {
                key: asdict(value) for key, value in self.dimensions.items()
            },
            "dealbreakers": list(dict.fromkeys(self.dealbreakers)),
            "unresolved_questions": list(dict.fromkeys(self.unresolved_questions)),
            "privacy_events": [asdict(event) for event in self.privacy_events],
            "scoring_version": self.scoring_version,
        }

