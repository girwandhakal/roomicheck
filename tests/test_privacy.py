import unittest

from roomicheck.privacy import PrivacyGuard


class PrivacyGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = PrivacyGuard()

    def test_redacts_identifiers_before_ai_use(self) -> None:
        result = self.guard.sanitize_answer(
            "Text me at 205-555-0188 or student@example.com; I live at 123 Campus Drive."
        )

        self.assertTrue(result.ai_allowed)
        self.assertNotIn("205-555-0188", result.text)
        self.assertNotIn("student@example.com", result.text)
        self.assertNotIn("123 Campus Drive", result.text)
        self.assertEqual({event.category for event in result.events}, {"phone", "email", "street_address"})

    def test_withholds_sensitive_response_from_ai(self) -> None:
        result = self.guard.sanitize_answer("My medical condition affects when I sleep.")

        self.assertFalse(result.ai_allowed)
        self.assertEqual(result.text, "[SENSITIVE_RESPONSE_WITHHELD]")
        self.assertIn("medical_or_disability", {event.category for event in result.events})

    def test_rejects_sensitive_generated_question(self) -> None:
        valid, reason = self.guard.validate_generated_question("What medical condition affects your sleep?")

        self.assertFalse(valid)
        self.assertIn("sensitive", reason)

    def test_accepts_practical_generated_question(self) -> None:
        valid, reason = self.guard.validate_generated_question(
            "What quiet-hours agreement would feel comfortable during the week?"
        )

        self.assertTrue(valid)
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()

