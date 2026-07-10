import unittest

from roomicheck.ai_provider import GeminiProvider, ResilientAI
from roomicheck.config import DIMENSIONS
from roomicheck.questionnaire import DemoAnswerSource, QuestionnaireEngine


class QuestionnaireIntegrationTests(unittest.TestCase):
    def test_offline_demo_completes_with_a_valid_profile(self) -> None:
        ai = ResilientAI(primary=GeminiProvider(api_key=""))
        engine = QuestionnaireEngine(ai=ai)
        output: list[str] = []

        session = engine.run(DemoAnswerSource(), emit=output.append)
        payload = session.profile.to_dict()

        self.assertEqual(set(payload["dimensions"]), set(DIMENSIONS))
        self.assertEqual(payload["profile_origin"], "fallback_scored")
        self.assertGreater(session.telemetry["fallback_count"], 0)
        self.assertTrue(any("CONTINUITY FOLLOW-UP" in line for line in output))
        for dimension in payload["dimensions"].values():
            self.assertGreaterEqual(dimension["score"], 1)
            self.assertLessEqual(dimension["score"], 5)
            self.assertTrue(dimension["evidence"])

    def test_demo_free_text_is_scored_by_continuity_rules(self) -> None:
        ai = ResilientAI(primary=GeminiProvider(api_key=""))
        session = QuestionnaireEngine(ai=ai).run(DemoAnswerSource(), emit=lambda _: None)

        sleep = session.profile.dimensions["studying_and_sleep_habits"]
        self.assertEqual(sleep.score, 4)
        self.assertGreater(sleep.confidence, 0.4)

    def test_preferences_and_dealbreakers_are_semantically_scoped(self) -> None:
        ai = ResilientAI(primary=GeminiProvider(api_key=""))
        session = QuestionnaireEngine(ai=ai).run(DemoAnswerSource(), emit=lambda _: None)

        cleanliness = session.profile.dimensions["living_and_cleanliness"]
        self.assertFalse(any("sleep" in item.casefold() for item in cleanliness.preferences))
        self.assertFalse(any("trash" in item.casefold() for item in session.profile.dealbreakers))
        self.assertTrue(any("firm boundary" in item.casefold() for item in session.profile.dealbreakers))


if __name__ == "__main__":
    unittest.main()
