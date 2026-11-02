"""
V2.6 — investigation workflow tables.

These tables hold the *human investigator's* workflow state. They are separate
from the risk engine: nothing here is read by, or written back into, any risk
score, detector or threshold. Risk level and investigation status are
different concepts and are stored in different places.

  investigations         one row per project that has had a workflow action
                         (status only). A project with no row is implicitly NEW.
  investigation_history  the audit trail. Append-only from the application's
                         point of view: the ORM refuses UPDATE and DELETE on it
                         (see the mapper events below), and the API exposes no
                         route that could edit or delete a row.

Both tables are additive. `init_db()` -> `create_all` creates them if missing
and never touches existing tables or data.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.database import Base


class InvestigationStatus(str, enum.Enum):
    """The controlled set of workflow states. Deliberately small."""

    NEW = "NEW"
    UNDER_REVIEW = "UNDER_REVIEW"
    REQUIRES_FURTHER_INVESTIGATION = "REQUIRES_FURTHER_INVESTIGATION"
    REVIEWED_NO_CONCERN = "REVIEWED_NO_CONCERN"
    ESCALATED = "ESCALATED"


class HistoryAction(str, enum.Enum):
    STATUS_CHANGE = "STATUS_CHANGE"
    NOTE = "NOTE"


DEFAULT_STATUS = InvestigationStatus.NEW


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _status_column(nullable: bool):
    return mapped_column(
        Enum(
            InvestigationStatus,
            native_enum=False,
            validate_strings=True,
            length=40,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=nullable,
    )


class Investigation(Base):
    __tablename__ = "investigations"

    # One workflow record per project, so the project id is the key.
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.project_id"), primary_key=True)
    status: Mapped[InvestigationStatus] = _status_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class InvestigationHistory(Base):
    __tablename__ = "investigation_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.project_id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    # Snapshots of who acted and in what role at that moment, so the trail stays
    # readable and accurate even if the account is later renamed or re-roled.
    username: Mapped[str] = mapped_column(String, nullable=False)
    user_role: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[HistoryAction] = mapped_column(
        Enum(HistoryAction, native_enum=False, validate_strings=True, length=20,
             values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    # Set for STATUS_CHANGE rows; NULL for NOTE rows (a note never changes status).
    previous_status: Mapped[InvestigationStatus | None] = _status_column(nullable=True)
    new_status: Mapped[InvestigationStatus | None] = _status_column(nullable=True)
    # Set for NOTE rows: the investigator's own words, stored verbatim.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)


class AuditTrailImmutableError(RuntimeError):
    """Raised if application code tries to modify or delete an audit-history row."""


@event.listens_for(InvestigationHistory, "before_update")
def _forbid_history_update(_mapper, _connection, _target):
    raise AuditTrailImmutableError("investigation_history is append-only: rows cannot be updated.")


@event.listens_for(InvestigationHistory, "before_delete")
def _forbid_history_delete(_mapper, _connection, _target):
    raise AuditTrailImmutableError("investigation_history is append-only: rows cannot be deleted.")
