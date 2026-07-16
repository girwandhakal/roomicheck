from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ai_provider import OpenAIProvider, ResilientAI
from .config import DIMENSION_LABELS, load_env_files
from .questionnaire import ConsoleAnswerSource, DemoAnswerSource, QuestionnaireEngine
from .storage import save_feedback, save_profile


def _bar(score: int) -> str:
    return "#" * score + "." * (5 - score)


def render_profile(profile_dict: dict, telemetry: dict) -> None:
    print("\n" + "=" * 68)
    print("ROOMICHECK CO-LIVING PROFILE")
    print("=" * 68)
    print(f"Profile: {profile_dict['profile_origin']} | Provider: {profile_dict['provider']}")
    print(f"Session: {profile_dict['session_id'][:12]} | Scoring: {profile_dict['scoring_version']}")

    for key, dimension in profile_dict["dimensions"].items():
        print(f"\n{DIMENSION_LABELS[key].upper()}")
        print(f"  [{_bar(dimension['score'])}] {dimension['score']}/5   confidence {dimension['confidence']:.0%}")
        for evidence in dimension["evidence"][:2]:
            print(f"  - {evidence}")
        for preference in dimension["preferences"][:2]:
            print(f"    Preference: {preference}")

    if profile_dict["dealbreakers"]:
        print("\nEXPLICIT DEALBREAKERS")
        for item in profile_dict["dealbreakers"]:
            print(f"  - {item}")

    if profile_dict["unresolved_questions"]:
        print("\nNEEDS CLARIFICATION")
        for item in profile_dict["unresolved_questions"][:4]:
            print(f"  - {item}")

    privacy_count = sum(event["count"] for event in profile_dict["privacy_events"])
    print("\nTRUST & RESILIENCE")
    print(f"  Privacy interventions: {privacy_count}")
    print(f"  Fallback operations: {telemetry['fallback_count']}")
    if telemetry["fallback_reasons"]:
        print(f"  Fallback reasons: {', '.join(dict.fromkeys(telemetry['fallback_reasons']))}")
    print("=" * 68)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate an AI-native RoomiCheck co-living profile.")
    parser.add_argument("--demo", action="store_true", help="Run the prepared, non-sensitive demonstration scenario.")
    parser.add_argument("--offline", action="store_true", help="Disable OpenAI and exercise the continuity path.")
    parser.add_argument("--no-save", action="store_true", help="Do not save the generated profile.")
    parser.add_argument("--json", action="store_true", help="Print the full profile JSON after the summary.")
    parser.add_argument("--feedback", action="store_true", help="Prompt for an anonymous profile-accuracy rating.")
    parser.add_argument("--output-dir", type=Path, help="Override the profile output directory.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_files()
    primary = OpenAIProvider(api_key="") if args.offline else OpenAIProvider()
    ai = ResilientAI(primary=primary)
    engine = QuestionnaireEngine(ai=ai)
    source = DemoAnswerSource() if args.demo else ConsoleAnswerSource()

    print("\nROOMICHECK / AI-NATIVE CO-LIVING ASSESSMENT")
    if ai.ai_available:
        print(f"Mode: AI primary ({ai.provider_name}) with guarded fallback")
    else:
        print("Mode: Resilient offline fallback (OpenAI unavailable or disabled)")
    print("Privacy: identifiers are redacted; sensitive topics are withheld from AI.")
    if args.demo:
        print("Demo: using a prepared synthetic student scenario.")

    try:
        session = engine.run(source)
    except KeyboardInterrupt:
        print("\nAssessment cancelled.")
        return 130

    profile_dict = session.profile.to_dict()
    render_profile(profile_dict, session.telemetry)

    if not args.no_save:
        destination = save_profile(session.profile, args.output_dir)
        print(f"Profile saved: {destination}")
    if args.json:
        print(json.dumps(profile_dict, indent=2))

    if args.feedback and not args.demo:
        rating_text = input("\nHow accurate is this profile (1-5, or Enter to skip)? ").strip()
        if rating_text.isdigit() and 1 <= int(rating_text) <= 5:
            notes = input("What should RoomiCheck improve? (optional): ").strip()
            feedback_path = save_feedback(session.profile, int(rating_text), notes)
            print(f"Anonymous feedback saved: {feedback_path}")

    return 0
