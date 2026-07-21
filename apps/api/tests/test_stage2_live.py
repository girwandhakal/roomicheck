"""Opt-in smoke coverage for the configured live Stage 2 provider.

Run with RUN_LIVE_AI_TESTS=1. This test is intentionally excluded from the
default suite because it makes external API calls and may incur provider cost.
"""

from __future__ import annotations

import os

import pytest

from app.ai import AdaptedQuestion, ExtractionResult, OpenAIAdaptiveProvider, SummaryResult
from app.config import get_settings


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AI_TESTS") != "1",
    reason="set RUN_LIVE_AI_TESTS=1 to run the live provider smoke test",
)


def test_live_provider_returns_all_stage2_contracts() -> None:
    settings = get_settings()
    if not settings.openai_api_key:
        pytest.skip("OPENAI_API_KEY is not configured")

    provider = OpenAIAdaptiveProvider(
        settings.openai_api_key,
        settings.openai_model,
        settings.ai_timeout_seconds,
    )
    extraction = provider.extract(
        {
            "question_id": "seed_open_ideal_coliving",
            "question": "What helps you feel comfortable in a shared home?",
            "question_type": "free_text",
            "target_dimension": None,
            "secondary_dimensions": [],
            "evidence_type": "free_text",
            "answer": {
                "normalized_text": "I prefer quiet study hours and clear communication about chores.",
                "selected_option_id": None,
                "selected_option_label": None,
                "scale_value": None,
            },
            "options": [],
            "scale": None,
            "allowed_dimensions": [
                "noise_environment",
                "household_structure",
                "communication_style",
                "personal_boundaries",
                "rule_flexibility",
            ],
            "prior_response_ids": [],
        }
    )
    adapted = provider.adapt_question(
        {
            "target_dimension": "household_structure",
            "bank_question": "How should shared chores be handled?",
            "last_answer": "I prefer clear communication about chores.",
        }
    )
    summary = provider.summarize(
        {
            "dimensions": {
                "household_structure": {
                    "label": "high",
                    "confidence": "high",
                    "summary": "Prefers explicit shared-home routines.",
                }
            },
            "contradictions": [],
        }
    )

    assert isinstance(extraction, ExtractionResult)
    assert isinstance(adapted, AdaptedQuestion)
    assert isinstance(summary, SummaryResult)
    assert summary.overall_summary
    assert isinstance(summary.cross_dimension_insights, list)
    assert adapted.text.endswith("?")
