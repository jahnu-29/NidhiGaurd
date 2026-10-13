"""
Stage 6.5 addition — see schemas.RiskResultSummary for why this exists.
Reuses the same get_risk_results dependency as /api/projects/{id}/risk,
/api/investigation-queue, and /api/dashboard/summary; computes nothing new.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import get_risk_results
from backend.app.api.schemas import RiskResultSummary

from intelligence.risk_engine import ProjectRiskResult

router = APIRouter(prefix="/api/risk-results", tags=["risk-results"])


@router.get("", response_model=list[RiskResultSummary])
def list_risk_results(
    risk_results: dict[str, ProjectRiskResult] = Depends(get_risk_results),
) -> list[RiskResultSummary]:
    return [
        RiskResultSummary(
            project_id=r.project_id,
            risk_score=r.risk_score,
            risk_level=r.risk_level,
            components_detected=sum(1 for c in r.components.values() if c["detected"]),
            recommendation=r.recommendation,
        )
        for r in risk_results.values()
    ]
