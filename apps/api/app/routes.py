from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from .database import DatabaseSession
from .audit import get_internal_session, require_internal_audit_token
from .schemas import (
    AnalyticsEventSubmission,
    AnswerSubmission,
    HealthOut,
    QuestionDeployedSubmission,
    SessionOut,
    InternalSessionOut,
)
from .service import (
    create_session,
    get_public_session,
    restart_session,
    retry_session,
    submit_answer,
    record_question_deployed,
    record_client_event,
)


router = APIRouter(prefix="/api/v1")


@router.get("/health", response_model=HealthOut)
def health(db: DatabaseSession) -> HealthOut:
    try:
        db.execute(text("SELECT 1"))
    except Exception as error:
        raise HTTPException(status_code=503, detail="Database is unavailable") from error
    return HealthOut(status="ok", database="connected")


@router.post("/questionnaire-sessions", response_model=SessionOut, status_code=201)
def start_questionnaire(db: DatabaseSession) -> SessionOut:
    return create_session(db)


@router.get("/questionnaire-sessions/{session_id}", response_model=SessionOut)
def read_questionnaire(session_id: UUID, db: DatabaseSession) -> SessionOut:
    return get_public_session(db, session_id)


@router.get("/internal/questionnaire-sessions/{session_id}", response_model=InternalSessionOut)
def read_internal_questionnaire(
    session_id: UUID,
    request: Request,
    db: DatabaseSession,
) -> InternalSessionOut:
    require_internal_audit_token(request)
    return get_internal_session(db, session_id)


@router.post("/questionnaire-sessions/{session_id}/answers", response_model=SessionOut)
def answer_questionnaire(
    session_id: UUID,
    submission: AnswerSubmission,
    db: DatabaseSession,
) -> SessionOut:
    return submit_answer(db, session_id, submission)


@router.post("/questionnaire-sessions/{session_id}/retry", response_model=SessionOut)
def retry_questionnaire(session_id: UUID, db: DatabaseSession) -> SessionOut:
    return retry_session(db, session_id)


@router.post("/questionnaire-sessions/{session_id}/question-deployed", status_code=204)
def deploy_question_event(
    session_id: UUID,
    submission: QuestionDeployedSubmission,
    db: DatabaseSession,
) -> None:
    record_question_deployed(db, session_id, submission.session_question_id)


@router.post("/questionnaire-sessions/{session_id}/events", status_code=204)
def record_event(
    session_id: UUID,
    submission: AnalyticsEventSubmission,
    db: DatabaseSession,
) -> None:
    record_client_event(db, session_id, submission.event_name, submission.properties)


@router.post("/questionnaire-sessions/{session_id}/restart", response_model=SessionOut)
def restart_questionnaire(session_id: UUID, db: DatabaseSession) -> SessionOut:
    return restart_session(db, session_id)
