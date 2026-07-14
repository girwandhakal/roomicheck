from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .config import DIMENSION_IDS
from .models import CoverageStatus, DimensionState, ProfileV2
from .questions import QuestionBank, QuestionDefinition, load_question_bank


MINIMUM_QUESTION_COUNT = 6
TARGET_QUESTION_COUNT_MIN = 7
TARGET_QUESTION_COUNT_MAX = 25
MAXIMUM_QUESTION_COUNT = 25
SUFFICIENT_CONFIDENCE = 0.70
DETAIL_EVIDENCE_MINIMUM = 80
DETAIL_EVIDENCE_STRONG = 180
MAX_DETAIL_QUESTIONS = 2


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

    @staticmethod
    def _detail_questions_needed(state: DimensionState) -> int:
        """Return the number of additional questions justified by current evidence."""
        if not state.evidence:
            return 0
        if state.clarification_needed or state.unknowns or not state.preference_strength_known:
            return MAX_DETAIL_QUESTIONS

        evidence_length = sum(len(item.excerpt) for item in state.evidence)
        if evidence_length >= DETAIL_EVIDENCE_STRONG and state.confidence >= SUFFICIENT_CONFIDENCE:
            return 0
        if evidence_length >= DETAIL_EVIDENCE_MINIMUM and state.confidence >= SUFFICIENT_CONFIDENCE:
            return 1
        return MAX_DETAIL_QUESTIONS

    def _needs_detail(self, profile: ProfileV2, dimension: str, asked_question_ids: set[str]) -> bool:
        state = profile.dimensions[dimension]
        if not state.evidence:
            return False
        asked_for_dimension = sum(
            question.active
            and not question.is_seed
            and question.primary_dimension == dimension
            and question.id in asked_question_ids
            for question in self.question_bank.questions
        )
        available = sum(
            question.active
            and not question.is_seed
            and question.primary_dimension == dimension
            and question.id not in asked_question_ids
            for question in self.question_bank.questions
        )
        return available > 0 and asked_for_dimension < self._detail_questions_needed(state)

    def next_target_dimension(self, profile: ProfileV2, asked_question_ids: set[str] | None = None) -> str:
        for dimension in DIMENSION_IDS:
            if self._has_unresolved_major_contradiction(profile, dimension):
                return dimension

        if asked_question_ids is not None:
            for dimension in DIMENSION_IDS:
                if self._needs_detail(profile, dimension, asked_question_ids):
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

    def decide(self, profile: ProfileV2, asked_question_ids: set[str] | None = None) -> CompletionDecision:
        if profile.question_count > MAXIMUM_QUESTION_COUNT:
            raise ValueError("Question count exceeds the hard maximum")
        self.refresh_coverage(profile)
        threshold_met = (
            profile.question_count >= MINIMUM_QUESTION_COUNT
            and all(
                profile.dimensions[dimension].coverage == CoverageStatus.SUFFICIENT
                for dimension in DIMENSION_IDS
            )
            and (
                asked_question_ids is None
                or not any(
                    self._needs_detail(profile, dimension, asked_question_ids)
                    for dimension in DIMENSION_IDS
                )
            )
        )
        if threshold_met:
            return CompletionDecision(True, CompletionReason.THRESHOLD_MET)
        if profile.question_count >= MAXIMUM_QUESTION_COUNT:
            self.refresh_coverage(profile, maximum_reached=True)
            return CompletionDecision(True, CompletionReason.MAXIMUM_REACHED)
        return CompletionDecision(
            False,
            next_dimension=self.next_target_dimension(profile, asked_question_ids),
        )

    def select_next_question(
        self,
        profile: ProfileV2,
        asked_question_ids: set[str] | None = None,
    ) -> QuestionDefinition | None:
        asked = asked_question_ids or set()
        decision = self.decide(profile, asked)
        if decision.complete or decision.next_dimension is None:
            return None
        return self.question_bank.next_for_dimension(decision.next_dimension, asked)

    @classmethod
    def mark_uncertain_at_maximum(cls, profile: ProfileV2) -> None:
        if profile.question_count < MAXIMUM_QUESTION_COUNT:
            raise ValueError("Uncertainty finalization is only allowed at the hard maximum")
        cls.refresh_coverage(profile, maximum_reached=True)
