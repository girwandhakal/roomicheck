import unittest

from roomicheck.v2.config import DIMENSION_IDS
from roomicheck.v2.fixed_scoring import load_fixed_scoring_rules
from roomicheck.v2.questions import QuestionType, load_question_bank


class FixedScoringTests(unittest.TestCase):
    def test_every_known_choice_has_a_valid_primary_mapping(self) -> None:
        rules = load_fixed_scoring_rules()
        bank = load_question_bank()

        for question in bank.questions:
            if question.is_seed:
                continue
            self.assertEqual(question.question_type, QuestionType.SINGLE_CHOICE)
            question_rules = rules["options"].get(question.id, {})
            for option in question.options:
                if option.id == "other":
                    self.assertNotIn(option.id, question_rules)
                    continue
                with self.subTest(question=question.id, option=option.id):
                    effects = question_rules[option.id]
                    self.assertIn(question.primary_dimension, effects)
                    self.assertTrue(set(effects).issubset({question.primary_dimension, *question.secondary_dimensions}))
                    for dimension, effect in effects.items():
                        self.assertIn(dimension, DIMENSION_IDS)
                        self.assertIn(effect.label, {"low", "moderate", "high"})
                        self.assertGreaterEqual(effect.confidence, 0.7)


if __name__ == "__main__":
    unittest.main()
