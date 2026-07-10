import copy
import unittest
from uuid import uuid4

from roomicheck.v2.config import (
    DIMENSION_IDS,
    PROFILE_SCHEMA_VERSION,
    load_dimension_definitions,
)
from roomicheck.v2.models import (
    CoverageStatus,
    DimensionState,
    EvidenceKind,
    EvidenceReference,
    PROFILE_JSON_SCHEMA,
    ProfileV2,
)
from roomicheck.v2.questions import QuestionType, load_question_bank


class V2ConfigurationTests(unittest.TestCase):
    def test_dimension_definitions_use_exact_canonical_order(self) -> None:
        definitions = load_dimension_definitions()

        self.assertEqual(tuple(definitions), DIMENSION_IDS)
        self.assertNotIn("living_and_cleanliness", definitions)
        for definition in definitions.values():
            definition.validate()

    def test_question_bank_has_open_seed_and_multiple_choice_followups(self) -> None:
        bank = load_question_bank()

        self.assertEqual(bank.seed.id, "seed_open_ideal_coliving")
        self.assertEqual(bank.seed.question_type, QuestionType.FREE_TEXT)
        self.assertIn("ideal co-living experience", bank.seed.prompt)
        for question in bank.questions:
            if question.is_seed:
                continue
            self.assertEqual(question.question_type, QuestionType.SINGLE_CHOICE)
            self.assertIn("other", {option.id for option in question.options})
        for dimension in DIMENSION_IDS:
            self.assertIsNotNone(bank.next_for_dimension(dimension))


class V2ProfileModelTests(unittest.TestCase):
    def test_empty_profile_round_trips_through_strict_parser(self) -> None:
        profile = ProfileV2.empty()

        payload = profile.to_dict()
        parsed = ProfileV2.from_dict(payload)

        self.assertEqual(parsed.schema_version, PROFILE_SCHEMA_VERSION)
        self.assertEqual(tuple(parsed.dimensions), DIMENSION_IDS)
        self.assertEqual(parsed.to_dict(), payload)

    def test_parser_rejects_additional_profile_fields(self) -> None:
        payload = ProfileV2.empty().to_dict()
        payload["unexpected"] = True

        with self.assertRaisesRegex(ValueError, "extra"):
            ProfileV2.from_dict(payload)

    def test_dimension_rejects_boolean_and_out_of_range_scores(self) -> None:
        response_id = str(uuid4())
        evidence = [EvidenceReference(response_id, EvidenceKind.DIRECT, "I prefer quiet.")]

        for score in (True, -1, 101):
            with self.subTest(score=score):
                state = DimensionState(
                    score=score,
                    confidence=0.8,
                    coverage=CoverageStatus.PARTIAL,
                    evidence=evidence,
                )
                with self.assertRaises(ValueError):
                    state.validate()

    def test_sufficient_dimension_requires_direct_evidence(self) -> None:
        state = DimensionState(
            score=50,
            confidence=0.9,
            coverage=CoverageStatus.SUFFICIENT,
            evidence=[EvidenceReference(str(uuid4()), EvidenceKind.INFERRED, "Likely flexible.")],
        )

        with self.assertRaisesRegex(ValueError, "direct evidence"):
            state.validate()

    def test_profile_rejects_unknown_evidence_response(self) -> None:
        known_id = str(uuid4())
        unknown_id = str(uuid4())
        profile = ProfileV2.empty()
        profile.dimensions["noise_environment"] = DimensionState(
            score=20,
            confidence=0.5,
            coverage=CoverageStatus.PARTIAL,
            evidence=[EvidenceReference(unknown_id, EvidenceKind.DIRECT, "Quiet at night matters.")],
        )

        with self.assertRaisesRegex(ValueError, "unknown responses"):
            profile.validate({known_id})

    def test_v1_shape_cannot_be_parsed_as_v2(self) -> None:
        payload = ProfileV2.empty().to_dict()
        payload["schema_version"] = "v1"
        dimensions = copy.deepcopy(payload["dimensions"])
        payload["dimensions"] = {
            "living_and_cleanliness": dimensions["household_structure"]
        }

        with self.assertRaises(ValueError):
            ProfileV2.from_dict(payload)

    def test_exported_json_schema_is_closed_and_versioned(self) -> None:
        self.assertFalse(PROFILE_JSON_SCHEMA["additionalProperties"])
        self.assertEqual(
            PROFILE_JSON_SCHEMA["properties"]["schema_version"]["const"],
            PROFILE_SCHEMA_VERSION,
        )
        dimension_schema = PROFILE_JSON_SCHEMA["$defs"]["dimension"]
        self.assertFalse(dimension_schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
