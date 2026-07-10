import unittest

from roomicheck.ai_provider import GeminiProvider, ProviderError
from roomicheck.models import AnswerRecord


class GeminiProviderValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = GeminiProvider(api_key="test-key")
        self.answer = AnswerRecord(
            question_id="scenario_01",
            prompt="How clean is the room?",
            answer="I keep shared spaces clear.",
            target_dimensions=["living_and_cleanliness"],
        )

    def valid_payload(self) -> dict:
        return {
            "contributions": [
                {
                    "dimension": "living_and_cleanliness",
                    "score": 4,
                    "confidence": 0.8,
                    "evidence": "Keeps shared spaces clear.",
                }
            ],
            "preferences": ["Clear shared surfaces"],
            "dealbreakers": [],
            "unresolved": False,
            "ask_follow_up": True,
            "follow_up_question": "How quickly should shared messes be handled?",
            "follow_up_dimension": "living_and_cleanliness",
        }

    def test_validates_structured_turn(self) -> None:
        analysis = self.provider._validate_turn(self.valid_payload(), self.answer, True)

        self.assertEqual(analysis.source, "ai")
        self.assertEqual(analysis.contributions[0].score, 4)
        self.assertIsNotNone(analysis.follow_up_question)

    def test_rejects_unauthorized_dimension(self) -> None:
        payload = self.valid_payload()
        payload["contributions"][0]["dimension"] = "socializing_and_guests"

        with self.assertRaises(ProviderError):
            self.provider._validate_turn(payload, self.answer, True)

    def test_rejects_out_of_range_confidence(self) -> None:
        payload = self.valid_payload()
        payload["contributions"][0]["confidence"] = 1.2

        with self.assertRaises(ProviderError):
            self.provider._validate_turn(payload, self.answer, True)


if __name__ == "__main__":
    unittest.main()

