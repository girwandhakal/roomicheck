from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .ai_provider import ResilientAI
from .config import DIMENSIONS, load_scoring_rules
from .models import (
    AnswerRecord,
    CoLivingProfile,
    DimensionProfile,
    PrivacyEvent,
    ScoreContribution,
    TurnAnalysis,
)


def _unique_strings(values: list[str], limit: int = 8) -> list[str]:
    cleaned = [value.strip()[:300] for value in values if isinstance(value, str) and value.strip()]
    return list(dict.fromkeys(cleaned))[:limit]


class ScoringEngine:
    def __init__(self) -> None:
        self.rules = load_scoring_rules()
        self.scoring_version = str(self.rules.get("scoring_version", "v1"))

    def fixed_contributions(self, answer: AnswerRecord) -> list[ScoreContribution]:
        if not answer.selected_option_id:
            return []
        mappings = self.rules.get("options", {}).get(answer.question_id, {}).get(answer.selected_option_id, {})
        contributions = []
        for dimension, score in mappings.items():
            if dimension not in answer.target_dimensions:
                raise ValueError(f"Scoring rule targeted undeclared dimension {dimension}")
            contribution = ScoreContribution(
                dimension=dimension,
                score=int(score),
                confidence=0.95,
                evidence=answer.answer,
                source="fixed_anchor",
                question_id=answer.question_id,
            )
            contribution.validate()
            contributions.append(contribution)
        return contributions

    def fallback_dimensions(
        self,
        contributions: list[ScoreContribution],
        preferences_by_dimension: dict[str, list[str]],
    ) -> dict[str, DimensionProfile]:
        by_dimension: dict[str, list[ScoreContribution]] = defaultdict(list)
        for contribution in contributions:
            contribution.validate()
            by_dimension[contribution.dimension].append(contribution)

        dimensions: dict[str, DimensionProfile] = {}
        for dimension in DIMENSIONS:
            items = by_dimension.get(dimension, [])
            if not items:
                dimensions[dimension] = DimensionProfile(
                    score=3,
                    confidence=0.15,
                    evidence=["No direct evidence was collected; neutral score used as a placeholder."],
                    preferences=[],
                )
                continue
            weighted_total = sum(item.score * max(item.confidence, 0.1) for item in items)
            total_weight = sum(max(item.confidence, 0.1) for item in items)
            score = int(Decimal(str(weighted_total / total_weight)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            confidence = min(0.95, sum(item.confidence for item in items) / len(items) * (0.75 + 0.1 * min(len(items), 2)))
            dimensions[dimension] = DimensionProfile(
                score=max(1, min(5, score)),
                confidence=round(confidence, 2),
                evidence=_unique_strings([item.evidence for item in items], limit=4),
                preferences=_unique_strings(preferences_by_dimension.get(dimension, []), limit=4),
            )
        return dimensions

    def build_profile(
        self,
        ai: ResilientAI,
        answers: list[AnswerRecord],
        analyses: list[TurnAnalysis],
        contributions: list[ScoreContribution],
        privacy_events: list[PrivacyEvent],
    ) -> CoLivingProfile:
        preferences_by_dimension: dict[str, list[str]] = defaultdict(list)
        for answer, analysis in zip(answers, analyses):
            for dimension in answer.target_dimensions:
                preferences_by_dimension[dimension].extend(analysis.preferences)
        preferences = _unique_strings(
            [value for values in preferences_by_dimension.values() for value in values]
        )
        dealbreakers = _unique_strings([value for analysis in analyses for value in analysis.dealbreakers])
        unresolved = _unique_strings(
            [answer.prompt for answer, analysis in zip(answers, analyses) if analysis.unresolved]
        )
        fallback_dimensions = self.fallback_dimensions(contributions, preferences_by_dimension)
        evidence_payload = {
            "answers": [answer.to_ai_dict() for answer in answers],
            "contributions": [
                {
                    "dimension": item.dimension,
                    "score": item.score,
                    "confidence": item.confidence,
                    "evidence": item.evidence,
                    "source": item.source,
                    "question_id": item.question_id,
                }
                for item in contributions
            ],
            "deterministic_baseline": {
                key: {
                    "score": value.score,
                    "confidence": value.confidence,
                    "evidence": value.evidence,
                }
                for key, value in fallback_dimensions.items()
            },
            "preferences": preferences,
            "dealbreakers": dealbreakers,
        }
        ai_payload = ai.synthesize_profile(evidence_payload)

        if ai_payload is None:
            dimensions = fallback_dimensions
            profile_origin = "fallback_scored"
        else:
            dimensions = {}
            for item in ai_payload["dimensions"]:
                dimensions[item["dimension"]] = DimensionProfile(
                    score=item["score"],
                    confidence=round(float(item["confidence"]), 2),
                    evidence=_unique_strings(item["evidence"], limit=4),
                    preferences=_unique_strings(item["preferences"], limit=4),
                )
            dealbreakers = _unique_strings(dealbreakers + ai_payload.get("dealbreakers", []))
            unresolved = _unique_strings(unresolved + ai_payload.get("unresolved_questions", []))
            profile_origin = "ai_synthesized"

        profile = CoLivingProfile(
            dimensions=dimensions,
            dealbreakers=dealbreakers,
            unresolved_questions=unresolved,
            privacy_events=privacy_events,
            scoring_version=self.scoring_version,
            profile_origin=profile_origin,
            provider=ai.provider_name,
            fallback_count=ai.fallback_count,
        )
        profile.validate()
        return profile
