from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .config import DIMENSION_IDS, QUESTIONNAIRE_VERSION, load_question_bank_payload


class QuestionType(StrEnum):
    FREE_TEXT = "free_text"
    SCENARIO = "scenario"
    SCALE = "scale"
    SINGLE_CHOICE = "single_choice"


class QuestionSource(StrEnum):
    BANK = "bank"
    AI_ADAPTED = "ai_adapted"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class QuestionOption:
    id: str
    label: str

    def validate(self) -> None:
        if not self.id or not self.id.strip() or not self.label or not self.label.strip():
            raise ValueError("Question options require non-empty IDs and labels")


@dataclass(frozen=True)
class QuestionDefinition:
    id: str
    version: str
    prompt: str
    question_type: QuestionType
    primary_dimension: str | None
    secondary_dimensions: tuple[str, ...] = ()
    options: tuple[QuestionOption, ...] = ()
    scale_min: int | None = None
    scale_max: int | None = None
    is_seed: bool = False
    active: bool = True

    def validate(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("Question ID must be non-empty")
        if not self.version or not self.version.strip():
            raise ValueError(f"Question {self.id} version must be non-empty")
        if not self.prompt or not self.prompt.strip():
            raise ValueError(f"Question {self.id} prompt must be non-empty")
        if not isinstance(self.question_type, QuestionType):
            raise ValueError(f"Question {self.id} has an invalid type")
        if self.is_seed:
            if self.primary_dimension is not None:
                raise ValueError("The seed question must not force one primary dimension")
        elif self.primary_dimension not in DIMENSION_IDS:
            raise ValueError(f"Question {self.id} has an invalid primary dimension")
        if any(dimension not in DIMENSION_IDS for dimension in self.secondary_dimensions):
            raise ValueError(f"Question {self.id} has invalid secondary dimensions")
        if self.primary_dimension in self.secondary_dimensions:
            raise ValueError(f"Question {self.id} repeats its primary dimension")
        if len(set(self.secondary_dimensions)) != len(self.secondary_dimensions):
            raise ValueError(f"Question {self.id} repeats a secondary dimension")
        if not isinstance(self.is_seed, bool) or not isinstance(self.active, bool):
            raise ValueError(f"Question {self.id} flags must be boolean")

        for option in self.options:
            option.validate()
        option_ids = [option.id for option in self.options]
        if len(set(option_ids)) != len(option_ids):
            raise ValueError(f"Question {self.id} has duplicate option IDs")

        if self.question_type == QuestionType.SINGLE_CHOICE:
            if not 2 <= len(self.options) <= 5:
                raise ValueError(f"Question {self.id} requires two through five options")
        elif self.options:
            raise ValueError(f"Question {self.id} type cannot contain options")

        if self.question_type == QuestionType.SCALE:
            if self.scale_min != 1 or self.scale_max != 5:
                raise ValueError(f"Question {self.id} must use the 1-5 demo scale")
        elif self.scale_min is not None or self.scale_max is not None:
            raise ValueError(f"Question {self.id} type cannot define a scale")


@dataclass(frozen=True)
class QuestionBank:
    questionnaire_version: str
    questions: tuple[QuestionDefinition, ...] = field(default_factory=tuple)

    @property
    def seed(self) -> QuestionDefinition:
        seeds = [question for question in self.questions if question.is_seed and question.active]
        if len(seeds) != 1:
            raise ValueError("Question bank must contain exactly one active seed")
        return seeds[0]

    def validate(self) -> None:
        if self.questionnaire_version != QUESTIONNAIRE_VERSION:
            raise ValueError("Question bank has an unexpected questionnaire version")
        ids: set[str] = set()
        for question in self.questions:
            question.validate()
            if question.id in ids:
                raise ValueError(f"Duplicate question ID: {question.id}")
            ids.add(question.id)
        self.seed
        if self.seed.question_type != QuestionType.FREE_TEXT:
            raise ValueError("The seed question must be open-ended")
        followups = [question for question in self.questions if not question.is_seed]
        if any(question.question_type != QuestionType.SINGLE_CHOICE for question in followups):
            raise ValueError("Every follow-up question must be multiple choice")
        if any(not any(option.id == "other" for option in question.options) for question in followups):
            raise ValueError("Every follow-up question must include an Other option")
        for dimension in DIMENSION_IDS:
            if not any(
                question.active and not question.is_seed and question.primary_dimension == dimension
                for question in self.questions
            ):
                raise ValueError(f"Question bank lacks fallback coverage for {dimension}")

    def next_for_dimension(
        self,
        dimension: str,
        asked_question_ids: set[str] | None = None,
    ) -> QuestionDefinition | None:
        if dimension not in DIMENSION_IDS:
            raise ValueError(f"Unknown v2 dimension: {dimension}")
        asked = asked_question_ids or set()
        return next(
            (
                question
                for question in self.questions
                if question.active
                and not question.is_seed
                and question.primary_dimension == dimension
                and question.id not in asked
            ),
            None,
        )


def _exact_keys(payload: dict[str, Any], expected: set[str], context: str) -> None:
    actual = set(payload)
    if actual != expected:
        raise ValueError(
            f"{context} fields mismatch; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def load_question_bank() -> QuestionBank:
    payload = load_question_bank_payload()
    _exact_keys(payload, {"questionnaire_version", "questions"}, "question bank")
    if not isinstance(payload["questions"], list):
        raise ValueError("question bank questions must be a list")
    questions: list[QuestionDefinition] = []
    expected = {
        "id",
        "version",
        "prompt",
        "question_type",
        "primary_dimension",
        "secondary_dimensions",
        "options",
        "scale_min",
        "scale_max",
        "is_seed",
        "active",
    }
    for index, raw in enumerate(payload["questions"]):
        if not isinstance(raw, dict):
            raise ValueError(f"questions[{index}] must be an object")
        _exact_keys(raw, expected, f"questions[{index}]")
        try:
            question_type = QuestionType(raw["question_type"])
        except (ValueError, TypeError) as error:
            raise ValueError(f"questions[{index}] has an invalid question_type") from error
        if not isinstance(raw["secondary_dimensions"], list) or not isinstance(raw["options"], list):
            raise ValueError(f"questions[{index}] dimensions and options must be lists")
        options = []
        for option_index, option in enumerate(raw["options"]):
            if not isinstance(option, dict):
                raise ValueError(f"questions[{index}].options[{option_index}] must be an object")
            _exact_keys(option, {"id", "label"}, f"questions[{index}].options[{option_index}]")
            options.append(QuestionOption(**option))
        question = QuestionDefinition(
            id=raw["id"],
            version=raw["version"],
            prompt=raw["prompt"],
            question_type=question_type,
            primary_dimension=raw["primary_dimension"],
            secondary_dimensions=tuple(raw["secondary_dimensions"]),
            options=tuple(options),
            scale_min=raw["scale_min"],
            scale_max=raw["scale_max"],
            is_seed=raw["is_seed"],
            active=raw["active"],
        )
        question.validate()
        questions.append(question)
    bank = QuestionBank(payload["questionnaire_version"], tuple(questions))
    bank.validate()
    return bank
