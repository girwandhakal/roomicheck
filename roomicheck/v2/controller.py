from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .config import DIMENSION_IDS
from .models import CoverageStatus, DimensionState, ProfileV2
from .questions import QuestionBank, QuestionDefinition, load_question_bank


MINIMUM_QUESTION_COUNT = 6
TARGET_QUESTION_COUNT_MIN = 7
TARGET_QUESTION_COUNT_MAX = 10
MAXIMUM_QUESTION_COUNT = 12
SUFFICIENT_CONFIDENCE = 0.70


class CompletionReason(StrEnum):
    THRESHOLD_MET = "threshold_met"
    MAXIMUM_REACHED = "maximum_reached"


@dataclass(frozen=True)
class CompletionDecision:
    complete: bool
    reason: CompletionReason | None = None
    next_dimension: str | None = None


class AdaptiveController:
    """Deterministic controller around provider-owned extraction and wording."""

    def __init__(self, question_bank: QuestionBank | None = None) -> None:
        self.question_bank = question_bank or load_question_bank()

    @staticmethod
    def _has_unresolved_major_contradiction(profile: ProfileV2, dimension: str) -> bool:
        return any(
            item.dimension == dimension and item.major and not item.resolved
            for item in profile.contradictions
        )

    @classmethod
    def refresh_coverage(cls, profile: ProfileV2, *, maximum_reached: bool = False) -> None:
        for dimension_id in DIMENSION_IDS:
            dimension = profile.dimensions[dimension_id]
            contradiction = cls._has_unresolved_major_contradiction(profile, dimension_id)
            sufficient = (
                dimension.score is not None
                and dimension.has_direct_evidence
                and dimension.confidence >= SUFFICIENT_CONFIDENCE
                and not dimension.clarification_needed
                and not contradiction
            )
            if sufficient:
                dimension.coverage = CoverageStatus.SUFFICIENT
            elif maximum_reached:
                dimension.coverage = CoverageStatus.UNCERTAIN
            elif not dimension.evidence:
                dimension.score = None
                dimension.label = None
                dimension.summary = None
                dimension.confidence = 0.0
                dimension.coverage = CoverageStatus.UNKNOWN
            else:
                dimension.coverage = CoverageStatus.PARTIAL

    def next_target_dimension(self, profile: ProfileV2) -> str:
        for dimension in DIMENSION_IDS:
            if self._has_unresolved_major_contradiction(profile, dimension):
                return dimension

        for dimension in DIMENSION_IDS:
            if profile.dimensions[dimension].coverage == CoverageStatus.UNKNOWN:
                return dimension

        for dimension in DIMENSION_IDS:
            if profile.dimensions[dimension].clarification_needed:
                return dimension

        partial = [
            dimension
            for dimension in DIMENSION_IDS
            if profile.dimensions[dimension].coverage == CoverageStatus.PARTIAL
        ]
        if partial:
            return min(partial, key=lambda item: (profile.dimensions[item].confidence, DIMENSION_IDS.index(item)))

        for dimension in DIMENSION_IDS:
            state = profile.dimensions[dimension]
            if not state.preference_strength_known or not state.scenario_evidence:
                return dimension

        return min(
            DIMENSION_IDS,
            key=lambda item: (profile.dimensions[item].confidence, DIMENSION_IDS.index(item)),
        )

    def decide(self, profile: ProfileV2) -> CompletionDecision:
        if profile.question_count > MAXIMUM_QUESTION_COUNT:
            raise ValueError("Question count exceeds the hard maximum")
        self.refresh_coverage(profile)
        threshold_met = (
            profile.question_count >= MINIMUM_QUESTION_COUNT
            and all(
                profile.dimensions[dimension].coverage == CoverageStatus.SUFFICIENT
                for dimension in DIMENSION_IDS
            )
        )
        if threshold_met:
            return CompletionDecision(True, CompletionReason.THRESHOLD_MET)
        if profile.question_count >= MAXIMUM_QUESTION_COUNT:
            self.refresh_coverage(profile, maximum_reached=True)
            return CompletionDecision(True, CompletionReason.MAXIMUM_REACHED)
        return CompletionDecision(False, next_dimension=self.next_target_dimension(profile))

    def select_next_question(
        self,
        profile: ProfileV2,
        asked_question_ids: set[str] | None = None,
    ) -> QuestionDefinition | None:
        decision = self.decide(profile)
        if decision.complete or decision.next_dimension is None:
            return None
        return self.question_bank.next_for_dimension(decision.next_dimension, asked_question_ids)

    @classmethod
    def mark_uncertain_at_maximum(cls, profile: ProfileV2) -> None:
        if profile.question_count < MAXIMUM_QUESTION_COUNT:
            raise ValueError("Uncertainty finalization is only allowed at the hard maximum")
        cls.refresh_coverage(profile, maximum_reached=True)
