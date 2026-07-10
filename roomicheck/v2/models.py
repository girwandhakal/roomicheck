from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from .config import DIMENSION_IDS, PROFILE_SCHEMA_VERSION


class CoverageStatus(StrEnum):
    UNKNOWN = "unknown"
    PARTIAL = "partial"
    SUFFICIENT = "sufficient"
    UNCERTAIN = "uncertain"


class EvidenceKind(StrEnum):
    DIRECT = "direct"
    INFERRED = "inferred"


class ProfileStatus(StrEnum):
    COLLECTING = "collecting"
    COMPLETE = "complete"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_exact_keys(payload: dict[str, Any], expected: set[str], context: str) -> None:
    actual = set(payload)
    if actual != expected:
        raise ValueError(
            f"{context} fields mismatch; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _validate_uuid(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a UUID string")
    try:
        UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{field_name} must be a UUID string") from error


def _validate_timestamp(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from error


def _validate_strings(values: list[str], field_name: str) -> None:
    if not isinstance(values, list):
        raise ValueError(f"{field_name} must be a list")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{field_name} must contain non-empty strings")


@dataclass(frozen=True)
class EvidenceReference:
    response_id: str
    kind: EvidenceKind
    excerpt: str

    def validate(self) -> None:
        _validate_uuid(self.response_id, "evidence.response_id")
        if not isinstance(self.kind, EvidenceKind):
            raise ValueError("evidence.kind must be direct or inferred")
        if not isinstance(self.excerpt, str) or not self.excerpt.strip():
            raise ValueError("evidence.excerpt must be non-empty")
        if len(self.excerpt) > 500:
            raise ValueError("evidence.excerpt cannot exceed 500 characters")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EvidenceReference:
        if not isinstance(payload, dict):
            raise ValueError("evidence must be an object")
        _require_exact_keys(payload, {"response_id", "kind", "excerpt"}, "evidence")
        try:
            kind = EvidenceKind(payload["kind"])
        except (ValueError, TypeError) as error:
            raise ValueError("evidence.kind must be direct or inferred") from error
        evidence = cls(payload["response_id"], kind, payload["excerpt"])
        evidence.validate()
        return evidence

    def to_dict(self) -> dict[str, Any]:
        return {"response_id": self.response_id, "kind": self.kind.value, "excerpt": self.excerpt}


@dataclass
class DimensionState:
    score: int | None = None
    label: str | None = None
    confidence: float = 0.0
    coverage: CoverageStatus = CoverageStatus.UNKNOWN
    summary: str | None = None
    evidence: list[EvidenceReference] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    clarification_needed: bool = False
    preference_strength_known: bool = False
    scenario_evidence: bool = False

    @property
    def has_direct_evidence(self) -> bool:
        return any(item.kind == EvidenceKind.DIRECT for item in self.evidence)

    def validate(self) -> None:
        if self.score is not None and (not _is_int(self.score) or not 0 <= self.score <= 100):
            raise ValueError("dimension score must be null or an integer from 0 through 100")
        if not _is_number(self.confidence) or not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("dimension confidence must be from 0 through 1")
        if not isinstance(self.coverage, CoverageStatus):
            raise ValueError("dimension coverage is invalid")
        for field_name in ("label", "summary"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"dimension {field_name} must be null or non-empty")
        _validate_strings(self.unknowns, "dimension.unknowns")
        for flag_name in ("clarification_needed", "preference_strength_known", "scenario_evidence"):
            if not isinstance(getattr(self, flag_name), bool):
                raise ValueError(f"dimension.{flag_name} must be boolean")
        seen_evidence: set[tuple[str, str, str]] = set()
        for item in self.evidence:
            if not isinstance(item, EvidenceReference):
                raise ValueError("dimension.evidence contains an invalid item")
            item.validate()
            key = (item.response_id, item.kind.value, item.excerpt)
            if key in seen_evidence:
                raise ValueError("dimension.evidence contains a duplicate")
            seen_evidence.add(key)

        if self.coverage == CoverageStatus.UNKNOWN:
            if self.score is not None or self.evidence:
                raise ValueError("unknown dimensions cannot contain a score or evidence")
        if self.coverage == CoverageStatus.SUFFICIENT:
            if self.score is None or self.confidence < 0.70 or not self.has_direct_evidence:
                raise ValueError("sufficient dimensions require a score, direct evidence, and confidence >= 0.70")
            if self.clarification_needed:
                raise ValueError("sufficient dimensions cannot need clarification")
        if (self.score is not None or self.label is not None or self.summary is not None) and not self.evidence:
            raise ValueError("dimension claims require evidence")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DimensionState:
        if not isinstance(payload, dict):
            raise ValueError("dimension must be an object")
        expected = {
            "score",
            "label",
            "confidence",
            "coverage",
            "summary",
            "evidence",
            "unknowns",
            "clarification_needed",
            "preference_strength_known",
            "scenario_evidence",
        }
        _require_exact_keys(payload, expected, "dimension")
        try:
            coverage = CoverageStatus(payload["coverage"])
        except (ValueError, TypeError) as error:
            raise ValueError("dimension coverage is invalid") from error
        evidence_payload = payload["evidence"]
        if not isinstance(evidence_payload, list):
            raise ValueError("dimension.evidence must be a list")
        dimension = cls(
            score=payload["score"],
            label=payload["label"],
            confidence=payload["confidence"],
            coverage=coverage,
            summary=payload["summary"],
            evidence=[EvidenceReference.from_dict(item) for item in evidence_payload],
            unknowns=payload["unknowns"],
            clarification_needed=payload["clarification_needed"],
            preference_strength_known=payload["preference_strength_known"],
            scenario_evidence=payload["scenario_evidence"],
        )
        dimension.validate()
        return dimension

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "label": self.label,
            "confidence": float(self.confidence),
            "coverage": self.coverage.value,
            "summary": self.summary,
            "evidence": [item.to_dict() for item in self.evidence],
            "unknowns": list(self.unknowns),
            "clarification_needed": self.clarification_needed,
            "preference_strength_known": self.preference_strength_known,
            "scenario_evidence": self.scenario_evidence,
        }


@dataclass
class Contradiction:
    id: str
    dimension: str
    response_ids: list[str]
    description: str
    major: bool = True
    resolved: bool = False

    def validate(self) -> None:
        _validate_uuid(self.id, "contradiction.id")
        if self.dimension not in DIMENSION_IDS:
            raise ValueError("contradiction.dimension is invalid")
        if not isinstance(self.response_ids, list) or not self.response_ids:
            raise ValueError("contradiction.response_ids must not be empty")
        for response_id in self.response_ids:
            _validate_uuid(response_id, "contradiction.response_ids")
        if len(set(self.response_ids)) != len(self.response_ids):
            raise ValueError("contradiction.response_ids contains duplicates")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("contradiction.description must be non-empty")
        if not isinstance(self.major, bool) or not isinstance(self.resolved, bool):
            raise ValueError("contradiction flags must be boolean")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Contradiction:
        if not isinstance(payload, dict):
            raise ValueError("contradiction must be an object")
        expected = {"id", "dimension", "response_ids", "description", "major", "resolved"}
        _require_exact_keys(payload, expected, "contradiction")
        contradiction = cls(**payload)
        contradiction.validate()
        return contradiction

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "dimension": self.dimension,
            "response_ids": list(self.response_ids),
            "description": self.description,
            "major": self.major,
            "resolved": self.resolved,
        }


@dataclass
class ProfileV2:
    session_id: str
    dimensions: dict[str, DimensionState]
    schema_version: str = PROFILE_SCHEMA_VERSION
    status: ProfileStatus = ProfileStatus.COLLECTING
    contradictions: list[Contradiction] = field(default_factory=list)
    written_summary: str | None = None
    question_count: int = 0
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def empty(cls, session_id: str | None = None) -> ProfileV2:
        return cls(
            session_id=session_id or str(uuid4()),
            dimensions={dimension: DimensionState() for dimension in DIMENSION_IDS},
        )

    def validate(self, known_response_ids: set[str] | None = None) -> None:
        if self.schema_version != PROFILE_SCHEMA_VERSION:
            raise ValueError(f"Expected schema_version {PROFILE_SCHEMA_VERSION}")
        _validate_uuid(self.session_id, "session_id")
        if not isinstance(self.status, ProfileStatus):
            raise ValueError("profile status is invalid")
        if set(self.dimensions) != set(DIMENSION_IDS):
            raise ValueError("profile dimensions must exactly match the v2 dimension IDs")
        if not _is_int(self.question_count) or not 0 <= self.question_count <= 12:
            raise ValueError("question_count must be an integer from 0 through 12")
        _validate_timestamp(self.created_at, "created_at")
        _validate_timestamp(self.updated_at, "updated_at")
        if self.written_summary is not None and (
            not isinstance(self.written_summary, str) or not self.written_summary.strip()
        ):
            raise ValueError("written_summary must be null or non-empty")

        referenced_response_ids: set[str] = set()
        for dimension in self.dimensions.values():
            if not isinstance(dimension, DimensionState):
                raise ValueError("profile contains an invalid dimension state")
            dimension.validate()
            referenced_response_ids.update(item.response_id for item in dimension.evidence)
        contradiction_ids: set[str] = set()
        for contradiction in self.contradictions:
            if not isinstance(contradiction, Contradiction):
                raise ValueError("profile contains an invalid contradiction")
            contradiction.validate()
            if contradiction.id in contradiction_ids:
                raise ValueError("profile contains a duplicate contradiction ID")
            contradiction_ids.add(contradiction.id)
            referenced_response_ids.update(contradiction.response_ids)
        if known_response_ids is not None:
            unknown = referenced_response_ids - known_response_ids
            if unknown:
                raise ValueError(f"profile references unknown responses: {sorted(unknown)}")

        if self.status == ProfileStatus.COMPLETE:
            if self.question_count < 6:
                raise ValueError("complete profiles require at least six questions")
            if self.written_summary is None:
                raise ValueError("complete profiles require a written summary")
            if any(item.coverage not in {CoverageStatus.SUFFICIENT, CoverageStatus.UNCERTAIN} for item in self.dimensions.values()):
                raise ValueError("complete profiles require sufficient or uncertain dimensions")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ProfileV2:
        if not isinstance(payload, dict):
            raise ValueError("profile must be an object")
        expected = {
            "schema_version",
            "session_id",
            "status",
            "dimensions",
            "contradictions",
            "written_summary",
            "question_count",
            "created_at",
            "updated_at",
        }
        _require_exact_keys(payload, expected, "profile")
        raw_dimensions = payload["dimensions"]
        if not isinstance(raw_dimensions, dict):
            raise ValueError("profile.dimensions must be an object")
        if set(raw_dimensions) != set(DIMENSION_IDS):
            raise ValueError("profile dimensions must exactly match the v2 dimension IDs")
        raw_contradictions = payload["contradictions"]
        if not isinstance(raw_contradictions, list):
            raise ValueError("profile.contradictions must be a list")
        try:
            status = ProfileStatus(payload["status"])
        except (ValueError, TypeError) as error:
            raise ValueError("profile status is invalid") from error
        profile = cls(
            schema_version=payload["schema_version"],
            session_id=payload["session_id"],
            status=status,
            dimensions={
                key: DimensionState.from_dict(raw_dimensions[key]) for key in DIMENSION_IDS
            },
            contradictions=[Contradiction.from_dict(item) for item in raw_contradictions],
            written_summary=payload["written_summary"],
            question_count=payload["question_count"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
        )
        profile.validate()
        return profile

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "status": self.status.value,
            "dimensions": {key: value.to_dict() for key, value in self.dimensions.items()},
            "contradictions": [item.to_dict() for item in self.contradictions],
            "written_summary": self.written_summary,
            "question_count": self.question_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


PROFILE_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": PROFILE_SCHEMA_VERSION,
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "session_id",
        "status",
        "dimensions",
        "contradictions",
        "written_summary",
        "question_count",
        "created_at",
        "updated_at",
    ],
    "properties": {
        "schema_version": {"const": PROFILE_SCHEMA_VERSION},
        "session_id": {"type": "string", "format": "uuid"},
        "status": {"type": "string", "enum": [item.value for item in ProfileStatus]},
        "dimensions": {
            "type": "object",
            "additionalProperties": False,
            "required": list(DIMENSION_IDS),
            "properties": {
                dimension: {"$ref": "#/$defs/dimension"} for dimension in DIMENSION_IDS
            },
        },
        "contradictions": {"type": "array", "items": {"$ref": "#/$defs/contradiction"}},
        "written_summary": {"type": ["string", "null"], "minLength": 1},
        "question_count": {"type": "integer", "minimum": 0, "maximum": 12},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
    },
    "$defs": {
        "evidence": {
            "type": "object",
            "additionalProperties": False,
            "required": ["response_id", "kind", "excerpt"],
            "properties": {
                "response_id": {"type": "string", "format": "uuid"},
                "kind": {"type": "string", "enum": [item.value for item in EvidenceKind]},
                "excerpt": {"type": "string", "minLength": 1, "maxLength": 500},
            },
        },
        "dimension": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "score",
                "label",
                "confidence",
                "coverage",
                "summary",
                "evidence",
                "unknowns",
                "clarification_needed",
                "preference_strength_known",
                "scenario_evidence",
            ],
            "properties": {
                "score": {"type": ["integer", "null"], "minimum": 0, "maximum": 100},
                "label": {"type": ["string", "null"], "minLength": 1},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "coverage": {"type": "string", "enum": [item.value for item in CoverageStatus]},
                "summary": {"type": ["string", "null"], "minLength": 1},
                "evidence": {"type": "array", "items": {"$ref": "#/$defs/evidence"}},
                "unknowns": {"type": "array", "items": {"type": "string", "minLength": 1}},
                "clarification_needed": {"type": "boolean"},
                "preference_strength_known": {"type": "boolean"},
                "scenario_evidence": {"type": "boolean"},
            },
        },
        "contradiction": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "dimension", "response_ids", "description", "major", "resolved"],
            "properties": {
                "id": {"type": "string", "format": "uuid"},
                "dimension": {"type": "string", "enum": list(DIMENSION_IDS)},
                "response_ids": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "format": "uuid"},
                },
                "description": {"type": "string", "minLength": 1},
                "major": {"type": "boolean"},
                "resolved": {"type": "boolean"},
            },
        },
    },
}
