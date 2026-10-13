"""
Stage 6.4 — dashboard summary.

Every number here is computed from the database-backed Stage 4 results at
request time (via get_risk_results), not copied from any old frontend
hardcoded KPI value.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import RISK_DISCLAIMER, get_risk_results
from backend.app.api.schemas import DashboardSummaryResponse, RiskLevelDistribution

from intelligence.risk_engine import ProjectRiskResult

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    risk_results: dict[str, ProjectRiskResult] = Depends(get_risk_results),
) -> DashboardSummaryResponse:
    levels = [r.risk_level for r in risk_results.values()]
    distribution = RiskLevelDistribution(
        critical=levels.count("CRITICAL"),
        high=levels.count("HIGH"),
        medium=levels.count("MEDIUM"),
        low=levels.count("LOW"),
    )
    queue_size = sum(1 for level in levels if level != "LOW")

    return DashboardSummaryResponse(
        total_projects=len(risk_results),
        risk_level_distribution=distribution,
        investigation_queue_size=queue_size,
        disclaimer=RISK_DISCLAIMER,
    )
