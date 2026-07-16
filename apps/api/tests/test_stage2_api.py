from __future__ import annotations

from uuid import uuid4

import pytest


@pytest.fixture(scope="module")
def api():
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        yield client


def test_sensitive_answer_skips_provider_and_continues(api, monkeypatch) -> None:
    from app import models, service
    from app.database import SessionFactory

    class ExplodingProvider:
        name = "must-not-be-called"

        def extract(self, _payload):
            raise AssertionError("privacy-withheld answer reached extract")

        def adapt_question(self, _payload):
            raise AssertionError("privacy-withheld answer reached adaptation")

        def summarize(self, _payload):
            raise AssertionError("privacy-withheld answer reached summary")

    session_ids: list[str] = []
    monkeypatch.setattr(service, "ai_provider", ExplodingProvider())
    try:
        started = api.post("/api/v1/questionnaire-sessions")
        assert started.status_code == 201, started.text
        session_id = started.json()["session_id"]
        session_ids.append(session_id)
        question = started.json()["current_question"]

        response = api.post(
            f"/api/v1/questionnaire-sessions/{session_id}/answers",
            json={
                "session_question_id": question["id"],
                "idempotency_key": str(uuid4()),
                "answer": {
                    "free_text": "I have a medical diagnosis and prefer quiet study hours.",
                    "scale_value": None,
                    "selected_option_id": None,
                },
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "active"

        with SessionFactory() as database:
            runs = database.query(models.AIRun).filter_by(session_id=session_id).all()
            assert {run.operation_type for run in runs} >= {"extract_response", "adapt_question"}
            assert all(run.model_name == "privacy-guard" for run in runs)
            assert all(run.error_category == "privacy_withheld" for run in runs)
    finally:
        with SessionFactory() as database:
            session = database.get(models.QuestionnaireSession, session_ids[0]) if session_ids else None
            if session is not None:
                database.delete(session)
            database.commit()


def test_known_choice_does_not_call_ai_provider(api, monkeypatch) -> None:
    from app import models, service
    from app.ai import AdaptedQuestion, ExtractionDimension, ExtractionResult, SummaryResult
    from app.database import SessionFactory

    class SeedOnlyProvider:
        name = "seed-only-test-provider"

        def extract(self, payload):
            if payload["question_id"] != "seed_open_ideal_coliving":
                raise AssertionError("known choice reached AI extraction")
            return ExtractionResult(dimensions=[ExtractionDimension(
                dimension="noise_environment",
                label="moderate",
                confidence="high",
                supporting_quote=payload["answer"]["normalized_text"],
                summary="Seed evidence for the noise dimension.",
                preference_strength_known=False,
                scenario_evidence=False,
            )])

        def adapt_question(self, payload):
            return AdaptedQuestion(text=payload["bank_question"])

        def summarize(self, _payload):
            return SummaryResult(summary="A deterministic test summary.")

    session_ids: list[str] = []
    monkeypatch.setattr(service, "ai_provider", SeedOnlyProvider())
    try:
        started = api.post("/api/v1/questionnaire-sessions")
        assert started.status_code == 201, started.text
        session_id = started.json()["session_id"]
        session_ids.append(session_id)
        seed = started.json()["current_question"]
        seed_response = api.post(
            f"/api/v1/questionnaire-sessions/{session_id}/answers",
            json={
                "session_question_id": seed["id"],
                "idempotency_key": str(uuid4()),
                "answer": {
                    "free_text": "I prefer a calm shared home.",
                    "scale_value": None,
                    "selected_option_id": None,
                },
            },
        )
        assert seed_response.status_code == 200, seed_response.text
        followup = seed_response.json()["current_question"]
        chosen = next(option for option in followup["options"] if option["id"] != "other")

        fixed_response = api.post(
            f"/api/v1/questionnaire-sessions/{session_id}/answers",
            json={
                "session_question_id": followup["id"],
                "idempotency_key": str(uuid4()),
                "answer": {
                    "free_text": None,
                    "scale_value": None,
                    "selected_option_id": chosen["id"],
                },
            },
        )
        assert fixed_response.status_code == 200, fixed_response.text
        with SessionFactory() as database:
            runs = database.query(models.AIRun).filter_by(session_id=session_id).all()
            fixed_runs = [run for run in runs if run.operation_type == "fixed_choice_score"]
            assert len(fixed_runs) == 1
            assert fixed_runs[0].model_name == "deterministic-fixed-choice"
    finally:
        with SessionFactory() as database:
            session = database.get(models.QuestionnaireSession, session_ids[0]) if session_ids else None
            if session is not None:
                database.delete(session)
            database.commit()
