from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .ai_provider import ResilientAI
from .config import load_questions
from .models import AnswerRecord, CoLivingProfile, PrivacyEvent, ScoreContribution, TurnAnalysis
from .privacy import PrivacyGuard
from .scoring import ScoringEngine


class AnswerSource(Protocol):
    def get_answer(
        self,
        *,
        question_id: str,
        prompt: str,
        options: list[dict[str, Any]],
        is_follow_up: bool,
    ) -> str: ...


class ConsoleAnswerSource:
    def get_answer(
        self,
        *,
        question_id: str,
        prompt: str,
        options: list[dict[str, Any]],
        is_follow_up: bool,
    ) -> str:
        del question_id, prompt, options, is_follow_up
        answer = input("Your answer: ").strip()
        while not answer:
            answer = input("Please provide an answer: ").strip()
        return answer


class DemoAnswerSource:
    seed_answers = {
        "scenario_01": "2",
        "scenario_02": "I usually sleep around 11 PM. A desk lamp is fine, but calls after midnight would make it hard to sleep.",
        "scenario_03": "3",
        "scenario_04": "2",
        "scenario_05": "Overnight guests are okay about once a month with two days of notice; frequent stays would be a firm boundary.",
    }
    follow_up_answers = {
        "scenario_01": "Shared surfaces should stay clear, and food or trash should be handled the same day.",
        "scenario_02": "Quiet calls after 11 PM and headphones after midnight would work for me.",
        "scenario_03": "A quick text a few hours ahead is enough unless it is late at night.",
        "scenario_04": "I prefer a calm face-to-face conversation before the issue becomes a pattern.",
        "scenario_05": "Two nights in a month is my comfortable maximum during the semester.",
    }

    def get_answer(
        self,
        *,
        question_id: str,
        prompt: str,
        options: list[dict[str, Any]],
        is_follow_up: bool,
    ) -> str:
        del prompt, options
        base_id = question_id.removesuffix("_followup")
        return self.follow_up_answers[base_id] if is_follow_up else self.seed_answers[base_id]


@dataclass
class QuestionnaireSession:
    profile: CoLivingProfile
    answers: list[AnswerRecord]
    analyses: list[TurnAnalysis]
    contributions: list[ScoreContribution]
    telemetry: dict[str, Any]


class QuestionnaireEngine:
    def __init__(
        self,
        ai: ResilientAI | None = None,
        privacy: PrivacyGuard | None = None,
        scoring: ScoringEngine | None = None,
        questions: list[dict[str, Any]] | None = None,
    ) -> None:
        self.ai = ai or ResilientAI()
        self.privacy = privacy or PrivacyGuard()
        self.scoring = scoring or ScoringEngine()
        self.questions = questions or load_questions()

    def run(
        self,
        answer_source: AnswerSource,
        emit: Callable[[str], None] = print,
    ) -> QuestionnaireSession:
        answers: list[AnswerRecord] = []
        analyses: list[TurnAnalysis] = []
        contributions: list[ScoreContribution] = []
        privacy_events: list[PrivacyEvent] = []

        for index, question in enumerate(self.questions, 1):
            emit(f"\nQUESTION {index} OF {len(self.questions)}")
            emit(question["prompt"])
            options = question.get("options", [])
            for option_index, option in enumerate(options, 1):
                emit(f"  {option_index}. {option['label']}")

            raw_answer = answer_source.get_answer(
                question_id=question["id"],
                prompt=question["prompt"],
                options=options,
                is_follow_up=False,
            )
            emit(f"> {raw_answer}")
            answer = self._normalize_answer(question, raw_answer)
            answers.append(answer)
            privacy_events.extend(answer.privacy_events)
            fixed = self.scoring.fixed_contributions(answer)
            contributions.extend(fixed)

            emit("Analyzing context and deciding whether clarification is useful...")
            analysis = self.ai.analyze_turn(answer, answers[:-1], allow_follow_up=True)
            analysis = self._guard_follow_up(answer, analysis, answers)
            analyses.append(analysis)
            contributions.extend(analysis.contributions)

            if analysis.follow_up_question:
                follow_up_label = "AI FOLLOW-UP" if analysis.source == "ai" else "CONTINUITY FOLLOW-UP"
                emit(f"\n{follow_up_label}\n{analysis.follow_up_question}")
                follow_up_raw = answer_source.get_answer(
                    question_id=f"{question['id']}_followup",
                    prompt=analysis.follow_up_question,
                    options=[],
                    is_follow_up=True,
                )
                emit(f"> {follow_up_raw}")
                follow_up = self._make_follow_up_answer(answer, analysis, follow_up_raw)
                answers.append(follow_up)
                privacy_events.extend(follow_up.privacy_events)
                follow_up_analysis = self.ai.analyze_turn(follow_up, answers[:-1], allow_follow_up=False)
                analyses.append(follow_up_analysis)
                contributions.extend(follow_up_analysis.contributions)

        emit("\nSynthesizing the complete co-living profile...")
        profile = self.scoring.build_profile(
            self.ai,
            answers,
            analyses,
            contributions,
            privacy_events,
        )
        return QuestionnaireSession(
            profile=profile,
            answers=answers,
            analyses=analyses,
            contributions=contributions,
            telemetry=self.ai.telemetry(),
        )

    def _normalize_answer(self, question: dict[str, Any], raw_answer: str) -> AnswerRecord:
        options = question.get("options", [])
        selected_option = None
        if raw_answer.strip().isdigit():
            choice = int(raw_answer.strip())
            if 1 <= choice <= len(options):
                selected_option = options[choice - 1]

        answer_text = selected_option["label"] if selected_option else raw_answer.strip()
        privacy_result = self.privacy.sanitize_answer(answer_text)
        return AnswerRecord(
            question_id=question["id"],
            prompt=question["prompt"],
            answer=privacy_result.text,
            target_dimensions=list(question.get("target_dimensions", ["general"])),
            selected_option_id=selected_option["id"] if selected_option else None,
            privacy_events=privacy_result.events,
            ai_allowed=privacy_result.ai_allowed,
        )

    def _make_follow_up_answer(
        self,
        parent: AnswerRecord,
        analysis: TurnAnalysis,
        raw_answer: str,
    ) -> AnswerRecord:
        privacy_result = self.privacy.sanitize_answer(raw_answer)
        return AnswerRecord(
            question_id=f"{parent.question_id}_followup",
            prompt=analysis.follow_up_question or "Follow-up",
            answer=privacy_result.text,
            target_dimensions=[analysis.follow_up_dimension or parent.target_dimensions[0]],
            is_follow_up=True,
            privacy_events=privacy_result.events,
            ai_allowed=privacy_result.ai_allowed,
        )

    def _guard_follow_up(
        self,
        answer: AnswerRecord,
        analysis: TurnAnalysis,
        prior_answers: list[AnswerRecord],
    ) -> TurnAnalysis:
        if not analysis.follow_up_question:
            return analysis
        is_valid, reason = self.privacy.validate_generated_question(analysis.follow_up_question)
        normalized = analysis.follow_up_question.casefold().strip()
        repeated = any(record.prompt.casefold().strip() == normalized for record in prior_answers)
        if is_valid and not repeated:
            return analysis

        self.ai.fallback_count += 1
        self.ai.errors.append("unsafe_follow_up" if not is_valid else "repeated_follow_up")
        fallback = self.ai.fallback.analyze_turn(answer, prior_answers, allow_follow_up=True)
        fallback.contributions = analysis.contributions
        fallback.preferences = analysis.preferences
        fallback.dealbreakers = analysis.dealbreakers
        fallback.unresolved = analysis.unresolved
        if reason:
            fallback.source = f"fallback:{reason}"
        return fallback
