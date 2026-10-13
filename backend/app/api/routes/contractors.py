"""
Stage 6.4 — contractor-facing endpoints.

Portfolio size and value are shown as plain database facts. Neither this
file nor anything it calls computes or implies a contractor-level risk
score — that would contradict the project's explicit, repeated rule that
portfolio size is never itself a signal.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_contractor_or_404, get_db
from backend.app.api.schemas import ContractorDetail, ContractorSummary
from backend.app.api.services import contractor_to_summary, project_to_summary
from backend.app.db.models import Contractor

router = APIRouter(prefix="/api/contractors", tags=["contractors"])


@router.get("", response_model=list[ContractorSummary])
def list_contractors(db: Session = Depends(get_db)) -> list[ContractorSummary]:
    contractors = db.scalars(select(Contractor).order_by(Contractor.contractor_id)).all()
    return [contractor_to_summary(c) for c in contractors]


@router.get("/{contractor_id}", response_model=ContractorDetail)
def get_contractor(contractor: Contractor = Depends(get_contractor_or_404)) -> ContractorDetail:
    summary = contractor_to_summary(contractor)
    return ContractorDetail(
        **summary.model_dump(),
        projects=[project_to_summary(p) for p in contractor.projects],
    )
