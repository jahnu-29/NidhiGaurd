"""
Stage 6.4 — investigation queue.

Same filter the (frontend-only, synthetic-data) InvestigationQueuePage
already used: every project where riskLevel != LOW, ranked by risk score
descending. This is a presentation filter over Stage 4's own classification,
not a new formula — nothing here recomputes or re-weights a score.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import RISK_DISCLAIMER, get_risk_results
from backend.app.api.schemas import InvestigationQueueItem, InvestigationQueueResponse
from backend.app.db.database import get_db
from backend.app.db.models import Project

from intelligence.risk_engine import ProjectRiskResult

router = APIRouter(prefix="/api/investigation-queue", tags=["investigation-queue"])


@router.get("", response_model=InvestigationQueueResponse)
def get_investigation_queue(
    db=Depends(get_db),
    risk_results: dict[str, ProjectRiskResult] = Depends(get_risk_results),
) -> InvestigationQueueResponse:
    qualifying = [r for r in risk_results.values() if r.risk_level != "LOW"]
    qualifying.sort(key=lambda r: r.risk_score, reverse=True)

    projects_by_id = {p.project_id: p for p in db.query(Project).filter(Project.project_id.in_(r.project_id for r in qualifying))}

    items = [
        InvestigationQueueItem(
            rank=i + 1,
            project_id=r.project_id,
            project_description=projects_by_id[r.project_id].project_description,
            work_type=projects_by_id[r.project_id].work_type,
            contractor_id=projects_by_id[r.project_id].contractor_id,
            risk_score=r.risk_score,
            risk_level=r.risk_level,
            components_detected=sum(1 for c in r.components.values() if c["detected"]),
            recommendation=r.recommendation,
        )
        for i, r in enumerate(qualifying)
    ]

    return InvestigationQueueResponse(total=len(items), items=items, disclaimer=RISK_DISCLAIMER)
