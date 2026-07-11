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
