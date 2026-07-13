"""Integration coverage for the Stage 1 session API.

The test uses the project's configured DATABASE_URL and removes every synthetic
session it creates.
"""

from __future__ import annotations

from uuid import uuid4

import pytest


@pytest.fixture(scope="module")
def api():
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        yield client


def test_synthetic_session_is_resumable_and_idempotent(api) -> None:
    from app import models
    from app.database import SessionFactory

    session_ids: list[str] = []
    try:
        started = api.post("/api/v1/questionnaire-sessions")
        assert started.status_code == 201
        session = started.json()
        session_id = session["session_id"]
        session_ids.append(session_id)

        assert api.get(f"/api/v1/questionnaire-sessions/{session_id}").status_code == 200
        question = session["current_question"]
        deployed = api.post(
            f"/api/v1/questionnaire-sessions/{session_id}/question-deployed",
            json={"session_question_id": question["id"]},
        )
        assert deployed.status_code == 204
        assert api.post(
            f"/api/v1/questionnaire-sessions/{session_id}/question-deployed",
            json={"session_question_id": question["id"]},
        ).status_code == 204
        payload = {
            "session_question_id": question["id"],
            "idempotency_key": str(uuid4()),
            "answer": {
                "free_text": "I need quiet to study and sleep.",
                "scale_value": None,
                "selected_option_id": None,
            },
        }

        accepted = api.post(f"/api/v1/questionnaire-sessions/{session_id}/answers", json=payload)
        replay = api.post(f"/api/v1/questionnaire-sessions/{session_id}/answers", json=payload)

        assert accepted.status_code == replay.status_code == 200
        assert accepted.json()["current_question"] == replay.json()["current_question"]
        with SessionFactory() as database:
            assert database.query(models.AnalyticsEvent).filter_by(
                session_id=session_id, event_name="question_deployed"
            ).count() == 1
    finally:
        with SessionFactory() as database:
            for session_id in session_ids:
                session = database.get(models.QuestionnaireSession, session_id)
                if session is not None:
                    database.delete(session)
            database.commit()

def test_health_endpoint(api) -> None:
    response = api.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}

def test_read_questionnaire_not_found(api) -> None:
    bad_id = str(uuid4())
    response = api.get(f"/api/v1/questionnaire-sessions/{bad_id}")
    assert response.status_code == 404

def test_answer_validation_errors(api) -> None:
    from app import models
    from app.database import SessionFactory

    session_ids = []
    try:
        started = api.post("/api/v1/questionnaire-sessions")
        session_id = started.json()["session_id"]
        session_ids.append(session_id)
        question = started.json()["current_question"]

        # Missing answer value
        payload_empty = {
            "session_question_id": question["id"],
            "idempotency_key": str(uuid4()),
            "answer": {
                "free_text": None,
                "scale_value": None,
                "selected_option_id": None,
            }
        }
        res = api.post(f"/api/v1/questionnaire-sessions/{session_id}/answers", json=payload_empty)
        assert res.status_code == 422

        # 'other' without free text
        payload_other_empty = {
            "session_question_id": question["id"],
            "idempotency_key": str(uuid4()),
            "answer": {
                "free_text": None,
                "scale_value": None,
                "selected_option_id": "other",
            }
        }
        res2 = api.post(f"/api/v1/questionnaire-sessions/{session_id}/answers", json=payload_other_empty)
        assert res2.status_code == 422

        # Invalid session question ID
        payload_bad_q = {
            "session_question_id": str(uuid4()),
            "idempotency_key": str(uuid4()),
            "answer": {
                "free_text": "A valid answer to a wrong question.",
                "scale_value": None,
                "selected_option_id": None,
            }
        }
        res3 = api.post(f"/api/v1/questionnaire-sessions/{session_id}/answers", json=payload_bad_q)
        assert res3.status_code == 409

    finally:
        with SessionFactory() as database:
            for s_id in session_ids:
                session = database.get(models.QuestionnaireSession, s_id)
                if session is not None:
                    database.delete(session)
            database.commit()

def test_retry_and_restart(api) -> None:
    from app import models
    from app.database import SessionFactory

    session_ids = []
    try:
        started = api.post("/api/v1/questionnaire-sessions")
        session_id = started.json()["session_id"]
        session_ids.append(session_id)

        # Retry should fail since it's active, not needs_retry
        retry_res = api.post(f"/api/v1/questionnaire-sessions/{session_id}/retry")
        assert retry_res.status_code == 409

        # Restart should create a new session
        restart_res = api.post(f"/api/v1/questionnaire-sessions/{session_id}/restart")
        assert restart_res.status_code == 200
        new_session_id = restart_res.json()["session_id"]
        session_ids.append(new_session_id)
        assert new_session_id != session_id

    finally:
        with SessionFactory() as database:
            for s_id in session_ids:
                session = database.get(models.QuestionnaireSession, s_id)
                if session is not None:
                    database.delete(session)
            database.commit()


def test_processing_failure_preserves_answer_for_retry(api, monkeypatch) -> None:
    from app import models, service
    from app.database import SessionFactory

    session_ids = []
    original_apply = service._apply_extraction
    try:
        started = api.post("/api/v1/questionnaire-sessions")
        session_id = started.json()["session_id"]
        session_ids.append(session_id)
        question = started.json()["current_question"]

        def fail_apply(*_args, **_kwargs):
            raise TimeoutError("simulated processing failure")

        monkeypatch.setattr(service, "_apply_extraction", fail_apply)
        payload = {
            "session_question_id": question["id"],
            "idempotency_key": str(uuid4()),
            "answer": {
                "free_text": "I need quiet to study and sleep.",
                "scale_value": None,
                "selected_option_id": None,
            },
        }
        failed = api.post(f"/api/v1/questionnaire-sessions/{session_id}/answers", json=payload)
        assert failed.status_code == 200
        assert failed.json()["status"] == "needs_retry"

        with SessionFactory() as database:
            response = database.query(models.QuestionnaireResponse).filter_by(session_id=session_id).one()
            assert response.validation_status == "needs_retry"
            assert database.query(models.ProfileSnapshot).filter_by(session_id=session_id).count() == 0

        monkeypatch.setattr(service, "_apply_extraction", original_apply)
        retried = api.post(f"/api/v1/questionnaire-sessions/{session_id}/retry")
        assert retried.status_code == 200
        assert retried.json()["status"] == "active"

        with SessionFactory() as database:
            response = database.query(models.QuestionnaireResponse).filter_by(session_id=session_id).one()
            assert response.validation_status == "valid"
            assert database.query(models.ProfileSnapshot).filter_by(session_id=session_id).count() == 1
    finally:
        with SessionFactory() as database:
            for session_id in session_ids:
                session = database.get(models.QuestionnaireSession, session_id)
                if session is not None:
                    database.delete(session)
            database.commit()


def test_complete_synthetic_session_creates_one_snapshot_per_answer(api) -> None:
    from app import models
    from app.database import SessionFactory

    session_ids: list[str] = []
    try:
        started = api.post("/api/v1/questionnaire-sessions")
        assert started.status_code == 201
        session_id = started.json()["session_id"]
        session_ids.append(session_id)
        current = started.json()

        for _ in range(12):
            question = current["current_question"]
            assert question is not None
            if question["question_type"] == "free_text":
                answer = {"free_text": "I prefer a calm, respectful shared home.", "scale_value": None, "selected_option_id": None}
            else:
                answer = {"free_text": None, "scale_value": None, "selected_option_id": question["options"][0]["id"]}
            response = api.post(
                f"/api/v1/questionnaire-sessions/{session_id}/answers",
                json={"session_question_id": question["id"], "idempotency_key": str(uuid4()), "answer": answer},
            )
            assert response.status_code == 200, response.text
            current = response.json()
            if current["status"] == "complete":
                break

        assert current["status"] == "complete"
        assert 6 <= current["progress"]["answered"] <= 12
        with SessionFactory() as database:
            answered = current["progress"]["answered"]
            assert database.query(models.ProfileSnapshot).filter_by(session_id=session_id).count() == answered
            assert database.query(models.QuestionnaireResponse).filter_by(session_id=session_id).count() == answered
            events = {
                event.event_name
                for event in database.query(models.AnalyticsEvent).filter_by(session_id=session_id).all()
            }
            assert {"session_started", "seed_started", "seed_submitted", "questionnaire_completed"} <= events
    finally:
        with SessionFactory() as database:
            for session_id in session_ids:
                session = database.get(models.QuestionnaireSession, session_id)
                if session is not None:
                    database.delete(session)
            database.commit()
