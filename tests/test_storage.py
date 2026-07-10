import json
import tempfile
import unittest
from pathlib import Path

from roomicheck.config import DIMENSIONS
from roomicheck.models import CoLivingProfile, DimensionProfile
from roomicheck.storage import save_feedback, save_profile


class StorageTests(unittest.TestCase):
    def make_profile(self) -> CoLivingProfile:
        return CoLivingProfile(
            dimensions={
                dimension: DimensionProfile(
                    score=3,
                    confidence=0.5,
                    evidence=["Synthetic test evidence"],
                    preferences=[],
                )
                for dimension in DIMENSIONS
            }
        )

    def test_saves_valid_profile_and_feedback(self) -> None:
        profile = self.make_profile()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = save_profile(profile, root / "profiles")
            feedback_path = save_feedback(profile, 4, "Mostly accurate", root / "feedback")

            payload = json.loads(profile_path.read_text(encoding="utf-8"))
            feedback = json.loads(feedback_path.read_text(encoding="utf-8").strip())

        self.assertEqual(payload["session_id"], profile.session_id)
        self.assertEqual(feedback["accuracy_rating"], 4)
        self.assertNotIn("dimensions", feedback)


if __name__ == "__main__":
    unittest.main()

