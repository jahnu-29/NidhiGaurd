"""
NidhiGuard Intelligence — Cost Anomaly Detector (max score: 25)

Compares a project's sanctioned_amount against a comparable-group benchmark
built from:
  - other CURRENT projects sharing the same work_type + state, and
  - HISTORICAL_PROJECTS sharing the same work_type + state.

Per docs/RELATIONSHIPS.md, `district_id` on projects.csv and the free-text
`district` on historical_projects.csv are not a reliable shared key (they
come from independently-sampled pools), so work_type + state is the
reliable, documented join for this comparison.

Uses the MEDIAN as the primary benchmark (robust to a handful of other
outliers already present in the comparable pool) and reports the mean as
supporting context. Requires a minimum number of comparables before
claiming a signal, and never asserts fraud.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median, mean

import pandas as pd

MAX_SCORE = 25
MIN_COMPARABLES = 5          # below this, we don't have a statistically meaningful group
LOW_PCT = 15.0                # below this deviation, no signal at all
SATURATE_PCT = 100.0          # at/above this deviation, score saturates at MAX_SCORE
DETECTION_PCT = 30.0          # minimum deviation to call `detected = True`


@dataclass
class CostAnomalyResult:
    score: float
    max_score: int = MAX_SCORE
    detected: bool = False
    benchmark_mean: float | None = None
    benchmark_median: float | None = None
    current_value: float | None = None
    percentage_difference: float | None = None
    comparable_count: int = 0
    explanation: str = ""


def _comparable_group(project_row: pd.Series, projects: pd.DataFrame,
                       historical: pd.DataFrame) -> list[float]:
    work_type = project_row["work_type"]
    state = project_row["state"]

    sibling_mask = (
        (projects["work_type"] == work_type)
        & (projects["state"] == state)
        & (projects["project_id"] != project_row["project_id"])
    )
    sibling_amounts = projects.loc[sibling_mask, "sanctioned_amount"].dropna().tolist()

    hist_mask = (historical["work_type"] == work_type) & (historical["state"] == state)
    hist_amounts = historical.loc[hist_mask, "sanctioned_amount"].dropna().tolist()

    return sibling_amounts + hist_amounts


def _score_from_percentage(pct_diff: float) -> float:
    """Linear ramp from 0 at LOW_PCT to MAX_SCORE at SATURATE_PCT. Deviations
    below (i.e. cheaper than benchmark, or within normal range) score 0."""
    if pct_diff <= LOW_PCT:
        return 0.0
    if pct_diff >= SATURATE_PCT:
        return float(MAX_SCORE)
    fraction = (pct_diff - LOW_PCT) / (SATURATE_PCT - LOW_PCT)
    return round(fraction * MAX_SCORE, 1)


def score_cost_anomaly(project_row: pd.Series, projects: pd.DataFrame,
                        historical: pd.DataFrame) -> CostAnomalyResult:
    comparables = _comparable_group(project_row, projects, historical)
    current_value = float(project_row["sanctioned_amount"])

    if len(comparables) < MIN_COMPARABLES:
        return CostAnomalyResult(
            score=0.0,
            detected=False,
            current_value=current_value,
            comparable_count=len(comparables),
            explanation=(
                f"Only {len(comparables)} comparable project(s) found for work type "
                f"'{project_row['work_type']}' in {project_row['state']} — too few to "
                f"establish a statistically meaningful cost benchmark, so no cost "
                f"signal is raised."
            ),
        )

    benchmark_median = median(comparables)
    benchmark_mean = mean(comparables)

    # Use whichever benchmark is closer to current value (i.e. the more
    # conservative/harder-to-trigger one) so a handful of low outliers in
    # the comparable pool can't manufacture a false signal.
    conservative_benchmark = max(benchmark_median, benchmark_mean)
    pct_diff = ((current_value - conservative_benchmark) / conservative_benchmark) * 100.0

    score = _score_from_percentage(pct_diff)
    detected = pct_diff >= DETECTION_PCT

    if pct_diff <= LOW_PCT:
        explanation = (
            f"Sanctioned amount is within the normal range of {len(comparables)} "
            f"comparable '{project_row['work_type']}' projects in {project_row['state']} "
            f"(benchmark median ₹{benchmark_median:,.0f})."
        )
    else:
        explanation = (
            f"Sanctioned amount is approximately {pct_diff:.0f}% above the median "
            f"expenditure of {len(comparables)} comparable '{project_row['work_type']}' "
            f"projects in {project_row['state']} (benchmark median ₹{benchmark_median:,.0f}, "
            f"current ₹{current_value:,.0f})."
        )

    return CostAnomalyResult(
        score=score,
        detected=detected,
        benchmark_mean=round(benchmark_mean, 2),
        benchmark_median=round(benchmark_median, 2),
        current_value=current_value,
        percentage_difference=round(pct_diff, 2),
        comparable_count=len(comparables),
        explanation=explanation,
    )
