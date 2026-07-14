import unittest
from uuid import uuid4

from roomicheck.v2.config import DIMENSION_IDS
from roomicheck.v2.controller import (
    AdaptiveController,
    CompletionReason,
    MAXIMUM_QUESTION_COUNT,
    MINIMUM_QUESTION_COUNT,
)
from roomicheck.v2.models import (
    Contradiction,
    CoverageStatus,
    DimensionState,
    EvidenceKind,
    EvidenceReference,
    ProfileV2,
)


def direct_state(
    confidence: float = 0.8,
    *,
    clarification_needed: bool = False,
    preference_strength_known: bool = True,
    scenario_evidence: bool = True,
) -> DimensionState:
    return DimensionState(
        score=50,
        label="Balanced preference",
        confidence=confidence,
        coverage=CoverageStatus.PARTIAL,
        summary="Evidence-grounded preference.",
        evidence=[EvidenceReference(str(uuid4()), EvidenceKind.DIRECT, "Direct response evidence.")],
        clarification_needed=clarification_needed,
        preference_strength_known=preference_strength_known,
        scenario_evidence=scenario_evidence,
    )


def filled_profile(confidence: float = 0.8) -> ProfileV2:
    profile = ProfileV2.empty()
    profile.dimensions = {
        dimension: direct_state(confidence) for dimension in DIMENSION_IDS
    }
    return profile


class AdaptiveControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = AdaptiveController()

    def test_empty_profile_targets_first_unknown_dimension(self) -> None:
        decision = self.controller.decide(ProfileV2.empty())

        self.assertFalse(decision.complete)
        self.assertEqual(decision.next_dimension, "noise_environment")

    def test_unresolved_major_contradiction_has_highest_priority(self) -> None:
        profile = ProfileV2.empty()
        response_id = str(uuid4())
        profile.contradictions.append(
            Contradiction(
                id=str(uuid4()),
                dimension="social_interaction",
                response_ids=[response_id],
                description="Conflicting desired interaction levels.",
            )
        )

        decision = self.controller.decide(profile)

        self.assertEqual(decision.next_dimension, "social_interaction")

    def test_clarification_precedes_low_confidence_partial_dimension(self) -> None:
        profile = filled_profile(0.6)
        profile.dimensions["study_daily_routine"].clarification_needed = True
        profile.dimensions["cultural_openness"].confidence = 0.1

        decision = self.controller.decide(profile)

        self.assertEqual(decision.next_dimension, "study_daily_routine")

    def test_lowest_confidence_partial_uses_canonical_tie_break(self) -> None:
        profile = filled_profile(0.6)
        profile.dimensions["social_interaction"].confidence = 0.2
        profile.dimensions["study_daily_routine"].confidence = 0.2

        decision = self.controller.decide(profile)

        self.assertEqual(decision.next_dimension, "social_interaction")

    def test_missing_strength_or_scenario_guides_required_extra_questions(self) -> None:
        profile = filled_profile(0.9)
        profile.dimensions["noise_environment"].preference_strength_known = False
        profile.question_count = MINIMUM_QUESTION_COUNT - 1

        decision = self.controller.decide(profile)

        self.assertFalse(decision.complete)
        self.assertEqual(decision.next_dimension, "noise_environment")

    def test_threshold_completion_requires_minimum_and_sufficient_dimensions(self) -> None:
        profile = filled_profile(0.8)
        profile.question_count = MINIMUM_QUESTION_COUNT

        decision = self.controller.decide(profile)

        self.assertTrue(decision.complete)
        self.assertEqual(decision.reason, CompletionReason.THRESHOLD_MET)
        self.assertTrue(
            all(state.coverage == CoverageStatus.SUFFICIENT for state in profile.dimensions.values())
        )

    def test_hard_maximum_marks_incomplete_dimensions_uncertain(self) -> None:
        profile = filled_profile(0.8)
        profile.dimensions["cultural_openness"] = DimensionState(
            unknowns=["No direct evidence was collected."]
        )
        profile.question_count = MAXIMUM_QUESTION_COUNT

        decision = self.controller.decide(profile)

        self.assertTrue(decision.complete)
        self.assertEqual(decision.reason, CompletionReason.MAXIMUM_REACHED)
        self.assertEqual(
            profile.dimensions["cultural_openness"].coverage,
            CoverageStatus.UNCERTAIN,
        )
        self.assertIsNone(profile.dimensions["cultural_openness"].score)

    def test_question_selection_skips_already_asked_bank_question(self) -> None:
        profile = ProfileV2.empty()
        first = self.controller.select_next_question(profile)
        self.assertIsNotNone(first)

        second = self.controller.select_next_question(profile, {first.id})

        self.assertIsNotNone(second)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(first.primary_dimension, second.primary_dimension)

    def test_detail_followups_are_dynamic_for_each_dimension(self) -> None:
        for dimension in DIMENSION_IDS:
            with self.subTest(dimension=dimension):
                sparse_profile = filled_profile(0.8)
                sparse_profile.question_count = MINIMUM_QUESTION_COUNT
                sparse_profile.dimensions[dimension].evidence = [
                    EvidenceReference(str(uuid4()), EvidenceKind.DIRECT, "social")
                ]
                asked = {
                    question.id
                    for question in self.controller.question_bank.questions
                    if not question.is_seed and question.primary_dimension != dimension
                }
                sparse_decision = self.controller.decide(sparse_profile, asked)
                self.assertEqual(sparse_decision.next_dimension, dimension)

                rich_profile = filled_profile(0.8)
                rich_profile.question_count = MINIMUM_QUESTION_COUNT
                for state in rich_profile.dimensions.values():
                    state.evidence = [
                        EvidenceReference(str(uuid4()), EvidenceKind.DIRECT, "A detailed answer " * 20)
                    ]
                rich_decision = self.controller.decide(rich_profile, set())
                self.assertTrue(rich_decision.complete)

    def test_medium_detail_requires_one_followup(self) -> None:
        profile = filled_profile(0.8)
        profile.dimensions["social_interaction"].evidence = [
            EvidenceReference(
                str(uuid4()),
                EvidenceKind.DIRECT,
                "I enjoy friendly roommate conversation, occasional shared activities, and checking in after a long day.",
            )
        ]
        for dimension, state in profile.dimensions.items():
            if dimension != "social_interaction":
                state.evidence = [
                    EvidenceReference(str(uuid4()), EvidenceKind.DIRECT, "A detailed answer " * 20)
                ]
        asked = {
            question.id
            for question in self.controller.question_bank.questions
            if question.primary_dimension != "social_interaction" and not question.is_seed
        }

        decision = self.controller.decide(profile, asked)

        self.assertFalse(decision.complete)
        self.assertEqual(decision.next_dimension, "social_interaction")


if __name__ == "__main__":
    unittest.main()
