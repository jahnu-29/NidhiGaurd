"""
V2.3 Baseline 1 - simple cost-deviation.

Question it answers: how much of the multi-detector engine's ranking can cost deviation alone explain?

Method (the whole baseline):
    benchmark(work_type) = median sanctioned_amount of the HISTORICAL projects of that work type
    score(project)       = sanctioned_amount / benchmark(project.work_type)       (higher = more anomalous)

Deliberate simplicity (this is NOT a rename of the V1 cost detector):
    * benchmark pools all states (no state adjustment),
    * benchmark uses only the historical table (never the project pool being scored),
    * no minimum-group logic beyond a sanity floor, no capping, no score scaling,
    * one-sided: only costs ABOVE the benchmark score high (cost inflation is the red flag).
It does not look at estimates, bills, contractors, locations, or any other detector's output.

Inputs: projects.csv and historical_projects.csv from engine_input/ only. No ground truth is read.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SCORE_COLUMN = "cost_deviation_score"
MIN_HISTORICAL_PER_WORK_TYPE = 5     # sanity floor only: refuse to benchmark on a handful of rows

METHOD_DESCRIPTION = (
    "score = sanctioned_amount / median(historical sanctioned_amount of the same work_type); "
    "pooled across states; historical table only; one-sided (higher = more anomalous); no tuning."
)


def historical_benchmark(historical: pd.DataFrame) -> pd.Series:
    """Median historical sanctioned amount per work type."""
    grouped = historical.groupby("work_type")["sanctioned_amount"]
    counts = grouped.size()
    if (counts < MIN_HISTORICAL_PER_WORK_TYPE).any():
        thin = counts[counts < MIN_HISTORICAL_PER_WORK_TYPE].to_dict()
        raise ValueError(f"too few historical projects to benchmark work types: {thin}")
    bench = grouped.median().astype(float)
    if not np.isfinite(bench).all() or (bench <= 0).any():
        raise ValueError("non-positive or non-finite historical benchmark")
    return bench


def score(projects: pd.DataFrame, historical: pd.DataFrame) -> pd.DataFrame:
    """Return project_id + cost_deviation_score, sorted by project_id."""
    bench = historical_benchmark(historical)
    b = projects["work_type"].map(bench)
    if b.isna().any():
        raise ValueError(f"no historical benchmark for work types: {sorted(projects.loc[b.isna(), 'work_type'].unique())}")
    amount = pd.to_numeric(projects["sanctioned_amount"], errors="raise").astype(float)
    ratio = amount / b
    if not np.isfinite(ratio).all():
        raise ValueError("non-finite cost-deviation score")
    out = pd.DataFrame({"project_id": projects["project_id"].astype(str).to_numpy(), SCORE_COLUMN: ratio.to_numpy()})
    return out.sort_values("project_id").reset_index(drop=True)
