"""
V2.6 — investigator workflow endpoints.

    GET  /api/projects/{id}/investigation          status + audit history   (all roles)
    POST /api/projects/{id}/investigation/status   change status            (Investigator, Administrator)
    POST /api/projects/{id}/investigation/notes    add an investigator note (Investigator, Administrator)
    GET  /api/investigations                       status per project, for the queue (all roles)

Authorization is enforced here, on the server, with the existing V1 role
dependencies. There is deliberately no PUT / PATCH / DELETE: the audit trail
can only grow.

Nothing in this file reads or changes a risk score. Status is workflow state
chosen by a human; it never feeds back into the risk engine or the queue ranking.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_db, get_project_or_404
from backend.app.auth.dependencies import ALL_ROLES, INVESTIGATOR_UP, require_roles
from backend.app.auth.models import User
from backend.app.db.models import Project
from backend.app.investigation.models import (
    DEFAULT_STATUS,
    HistoryAction,
    Investigation,
    InvestigationHistory,
    _utcnow,
)
from backend.app.investigation.schemas import (
    InvestigationHistoryEntry,
    InvestigationResponse,
    InvestigationSummariesResponse,
    InvestigationSummary,
    NoteRequest,
    StatusChangeRequest,
    as_utc,
)

router = APIRouter(tags=["investigation"])


def _history_entry(row: InvestigationHistory) -> InvestigationHistoryEntry:
    return InvestigationHistoryEntry(
        id=row.id,
        project_id=row.project_id,
        action=row.action,
        previous_status=row.previous_status,
        new_status=row.new_status,
        note=row.note,
        username=row.username,
        user_role=row.user_role,
        created_at=as_utc(row.created_at),
    )


def _build_response(db: Session, project_id: str) -> InvestigationResponse:
    record = db.get(Investigation, project_id)
    rows = db.scalars(
        select(InvestigationHistory)
        .where(InvestigationHistory.project_id == project_id)
        .order_by(InvestigationHistory.created_at, InvestigationHistory.id)
    ).all()
    return InvestigationResponse(
        project_id=project_id,
        status=record.status if record else DEFAULT_STATUS,
        created_at=as_utc(record.created_at) if record else None,
        updated_at=as_utc(record.updated_at) if record else None,
        history=[_history_entry(r) for r in rows],
    )


def _get_or_create_record(db: Session, project_id: str) -> Investigation:
    """The project's workflow row; created (status NEW) on the first workflow action."""
    record = db.get(Investigation, project_id)
    if record is None:
        now = _utcnow()
        record = Investigation(project_id=project_id, status=DEFAULT_STATUS, created_at=now, updated_at=now)
        db.add(record)
    return record


def _commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        # Two first-time writes for the same project raced; nothing was saved for this one.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The investigation was updated by someone else at the same moment. Please retry.",
        )
    except Exception:
        db.rollback()
        raise


@router.get(
    "/api/projects/{project_id}/investigation",
    response_model=InvestigationResponse,
    dependencies=[Depends(require_roles(*ALL_ROLES))],
)
def get_investigation(project: Project = Depends(get_project_or_404), db: Session = Depends(get_db)):
    return _build_response(db, project.project_id)


@router.post("/api/projects/{project_id}/investigation/status", response_model=InvestigationResponse)
def change_status(
    body: StatusChangeRequest,
    user: User = Depends(require_roles(*INVESTIGATOR_UP)),  # authorize before anything else
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
):
    record = _get_or_create_record(db, project.project_id)
    previous = record.status
    if body.status == previous:
        db.rollback()  # discard a record that may have just been added
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The investigation status is already {previous.value}.",
        )
    now = _utcnow()
    record.status = body.status
    record.updated_at = now
    db.add(
        InvestigationHistory(
            project_id=project.project_id,
            user_id=user.id,
            username=user.username,
            user_role=user.role.value,
            action=HistoryAction.STATUS_CHANGE,
            previous_status=previous,
            new_status=body.status,
            note=None,
            created_at=now,
        )
    )
    _commit_or_conflict(db)
    return _build_response(db, project.project_id)


@router.post("/api/projects/{project_id}/investigation/notes", response_model=InvestigationResponse)
def add_note(
    body: NoteRequest,
    user: User = Depends(require_roles(*INVESTIGATOR_UP)),  # authorize before anything else
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
):
    record = _get_or_create_record(db, project.project_id)
    now = _utcnow()
    record.updated_at = now
    db.add(
        InvestigationHistory(
            project_id=project.project_id,
            user_id=user.id,
            username=user.username,
            user_role=user.role.value,
            action=HistoryAction.NOTE,
            previous_status=None,
            new_status=None,
            note=body.note,
            created_at=now,
        )
    )
    _commit_or_conflict(db)
    return _build_response(db, project.project_id)


@router.get(
    "/api/investigations",
    response_model=InvestigationSummariesResponse,
    dependencies=[Depends(require_roles(*ALL_ROLES))],
)
def list_investigations(db: Session = Depends(get_db)):
    last_action = dict(
        db.execute(
            select(InvestigationHistory.project_id, func.max(InvestigationHistory.created_at)).group_by(
                InvestigationHistory.project_id
            )
        ).all()
    )
    records = db.scalars(select(Investigation).order_by(Investigation.project_id)).all()
    return InvestigationSummariesResponse(
        items=[
            InvestigationSummary(
                project_id=r.project_id,
                status=r.status,
                last_action_at=as_utc(last_action[r.project_id]) if r.project_id in last_action else None,
            )
            for r in records
        ]
    )
