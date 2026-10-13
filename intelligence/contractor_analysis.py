"""
NidhiGuard Intelligence — Contractor Pattern Detector (max score: 20)

Looks for a CONCENTRATION pattern within a single contractor's own project
portfolio: a subset of their projects that were awarded close together in
time, repeat the same work_type, and sit at the higher-cost end of that
contractor's own project distribution.

Explicitly NOT scored:
  - Simply having many projects (a large, legitimate contractor is not
    inherently suspicious).
  - anomaly_signals.csv is never read here — the cluster must be found
    from projects.csv / project_contractors.csv / contractors.csv alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

import pandas as pd

MAX_SCORE = 20
MIN_PORTFOLIO_SIZE = 3       # below this, no meaningful pattern is possible
MIN_CLUSTER_SIZE = 3         # smallest "closely-awarded, same-work-type" group worth flagging
CLOSE_AWARD_WINDOW_DAYS = 60
COST_PREMIUM_THRESHOLD = 1.15  # cluster median >= 15% above contractor's own median


@dataclass
class ContractorPatternResult:
    score: float
    max_score: int = MAX_SCORE
    detected: bool = False
    contractor_id: str | None = None
    portfolio_size: int = 0
    cluster_size: int = 0
    cost_premium_pct: float | None = None
    cluster_project_ids: list[str] = field(default_factory=list)
    explanation: str = ""


def score_contractor_pattern(project_row: pd.Series, projects: pd.DataFrame) -> ContractorPatternResult:
    contractor_id = project_row["contractor_id"]
    portfolio = projects[projects["contractor_id"] == contractor_id]
    portfolio_size = len(portfolio)

    if portfolio_size < MIN_PORTFOLIO_SIZE:
        return ContractorPatternResult(
            score=0.0,
            detected=False,
            contractor_id=contractor_id,
            portfolio_size=portfolio_size,
            explanation=(
                f"Contractor {contractor_id} has only {portfolio_size} project(s) in the "
                f"current dataset — too few to establish a concentration pattern."
            ),
        )

    work_order_date = project_row["work_order_date"]
    if pd.isna(work_order_date):
        return ContractorPatternResult(
            score=0.0,
            detected=False,
            contractor_id=contractor_id,
            portfolio_size=portfolio_size,
            explanation="Project has no work_order_date on record, so award-timing clustering cannot be evaluated.",
        )

    same_type = portfolio[portfolio["work_type"] == project_row["work_type"]]
    close_award_mask = (same_type["work_order_date"] - work_order_date).abs().dt.days <= CLOSE_AWARD_WINDOW_DAYS
    cluster = same_type[close_award_mask]
    cluster_size = len(cluster)

    if cluster_size < MIN_CLUSTER_SIZE:
        return ContractorPatternResult(
            score=0.0,
            detected=False,
            contractor_id=contractor_id,
            portfolio_size=portfolio_size,
            cluster_size=cluster_size,
            explanation=(
                f"Contractor {contractor_id} has {portfolio_size} total project(s), but no group of "
                f"{MIN_CLUSTER_SIZE}+ same-work-type projects awarded within "
                f"{CLOSE_AWARD_WINDOW_DAYS} days of each other."
            ),
        )

    portfolio_median_cost = median(portfolio["sanctioned_amount"].dropna().tolist())
    cluster_median_cost = median(cluster["sanctioned_amount"].dropna().tolist())
    premium_ratio = cluster_median_cost / portfolio_median_cost if portfolio_median_cost else 1.0
    premium_pct = (premium_ratio - 1.0) * 100.0

    detected = premium_ratio >= COST_PREMIUM_THRESHOLD

    if not detected:
        score = round(min(MAX_SCORE, (cluster_size - MIN_CLUSTER_SIZE + 1) * 2), 1)
        explanation = (
            f"Contractor {contractor_id} has a group of {cluster_size} '{project_row['work_type']}' "
            f"projects awarded within {CLOSE_AWARD_WINDOW_DAYS} days of each other, but their cost "
            f"sits close to the contractor's own typical project cost (no premium detected)."
        )
    else:
        size_component = min(12, (cluster_size - MIN_CLUSTER_SIZE + 1) * 4)
        premium_component = min(8, premium_pct / 5)
        score = round(min(MAX_SCORE, size_component + premium_component), 1)
        explanation = (
            f"This project is part of a cluster of {cluster_size} closely-awarded "
            f"'{project_row['work_type']}' projects connected to contractor {contractor_id}, "
            f"priced approximately {premium_pct:.0f}% above that contractor's own median project "
            f"cost — an unusual concentration pattern worth review."
        )

    return ContractorPatternResult(
        score=score,
        detected=detected,
        contractor_id=contractor_id,
        portfolio_size=portfolio_size,
        cluster_size=cluster_size,
        cost_premium_pct=round(premium_pct, 2),
        cluster_project_ids=sorted(cluster["project_id"].tolist()),
        explanation=explanation,
    )
