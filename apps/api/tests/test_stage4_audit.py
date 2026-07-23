from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import audit
from app import service
from app.schemas import AnalyticsEventSubmission


def request_with_token(token: str) -> Request:
    return Request({
        "type": "http",
        "headers": [(b"x-internal-audit-token", token.encode())],
    })


def test_snapshot_diff_reports_dimension_and_confidence_changes() -> None:
    before = {"dimensions": {"physical_environment": {"score": 20, "confidence": 0.5}}}
    after = {"dimensions": {"physical_environment": {"score": 45, "confidence": 0.9}}}

    diff = audit.snapshot_diff(before, after)

    assert diff["dimensions"]["physical_environment"]["score"] == {"before": 20, "after": 45}
    assert diff["confidence_changes"]["physical_environment"] == {"before": 0.5, "after": 0.9}


def test_client_event_schema_rejects_unapproved_event() -> None:
    with pytest.raises(ValueError):
        AnalyticsEventSubmission(event_name="session_started")


def test_internal_audit_token_requires_configured_constant() -> None:
    original = audit.get_settings
    audit.get_settings = lambda: SimpleNamespace(internal_audit_token="secret")
    try:
        audit.require_internal_audit_token(request_with_token("secret"))
        with pytest.raises(HTTPException) as error:
            audit.require_internal_audit_token(request_with_token("wrong"))
        assert error.value.status_code == 401
    finally:
        audit.get_settings = original


def test_stale_session_is_marked_without_deleting_records(monkeypatch) -> None:
    class FakeDb:
        def __init__(self) -> None:
            self.added = []

        def add(self, value) -> None:
            self.added.append(value)

    monkeypatch.setattr(service, "settings", SimpleNamespace(abandonment_timeout_minutes=30))
    session = SimpleNamespace(
        id=uuid4(),
        status="active",
        abandoned=False,
        last_activity_at=service.utc_now() - timedelta(minutes=31),
    )
    database = FakeDb()

    assert service.mark_abandoned_if_stale(database, session) is True
    assert session.status == "abandoned"
    assert session.abandoned is True
    assert len(database.added) == 1
    assert database.added[0].event_name == "session_abandoned"
