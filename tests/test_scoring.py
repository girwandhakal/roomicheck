import unittest

from roomicheck.config import DIMENSIONS
from roomicheck.models import AnswerRecord, ScoreContribution
from roomicheck.scoring import ScoringEngine


class ScoringEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scoring = ScoringEngine()

    def test_fixed_choice_has_stable_score(self) -> None:
        answer = AnswerRecord(
            question_id="scenario_01",
            prompt="Cleanliness scenario",
            answer="I keep things neat.",
            target_dimensions=["living_and_cleanliness"],
            selected_option_id="strict_clean",
        )

        contributions = self.scoring.fixed_contributions(answer)

        self.assertEqual(len(contributions), 1)
        self.assertEqual(contributions[0].score, 5)
        self.assertEqual(contributions[0].source, "fixed_anchor")

    def test_fallback_profile_contains_every_dimension(self) -> None:
        contribution = ScoreContribution(
            dimension="living_and_cleanliness",
            score=4,
            confidence=0.9,
            evidence="Keeps shared surfaces clear.",
            source="test",
            question_id="scenario_01",
        )

        dimensions = self.scoring.fallback_dimensions([contribution], {})

        self.assertEqual(set(dimensions), set(DIMENSIONS))
        self.assertEqual(dimensions["living_and_cleanliness"].score, 4)
        self.assertEqual(dimensions["studying_and_sleep_habits"].score, 3)
        self.assertLess(dimensions["studying_and_sleep_habits"].confidence, 0.2)

    def test_contribution_rejects_out_of_range_score(self) -> None:
        contribution = ScoreContribution(
            dimension="living_and_cleanliness",
            score=6,
            confidence=0.9,
            evidence="Evidence",
            source="test",
            question_id="scenario_01",
        )

        with self.assertRaises(ValueError):
            contribution.validate()


if __name__ == "__main__":
    unittest.main()
