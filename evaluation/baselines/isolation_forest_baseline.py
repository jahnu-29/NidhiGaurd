"""
V2.3 Baseline 2 - Isolation Forest (generic unsupervised anomaly detection).

Fitted on the 150 evaluation projects themselves (transductive; there is no separate training pool for
an unsupervised detector) with NO labels, NO engine outputs and NO planted signals anywhere in the pipeline.

Features (8, committed before any result was seen; generic project-level numbers, not tailored to scenario rules):
    log_cost_ratio           ln(sanctioned_amount / historical median of the same work type)
                             - removes the scale difference between work types so the forest does not flag
                               "a classroom block costs more than a hand pump" as anomalous.
    sanction_over_estimate   sanctioned_amount / estimated_cost
                             - a standard procurement red flag: sanction far above the engineer's estimate.
    bill_count               number of bills submitted for the project.
    billed_over_sanctioned   total claimed amount / sanctioned_amount (how much of the sanction has been billed).
    payment_count            number of payments made for the project.
    contractor_project_count number of projects in the pool held by the same contractor (workload concentration).
    neighbors_within_5km     other projects within 5 km (haversine) - local project density.
    nearest_neighbor_km_log1p  log1p(distance in km to the nearest other project) - spatial isolation.

Deliberately NOT used: work_type/state/category (no categorical encoding; work type only enters through the
benchmark), planned duration (no hypothesised link to the red flags), approved/actual amounts (downstream of the
sanction), dates, contractor attributes, text descriptions.

Preprocessing: none beyond the log transforms above. Isolation Forest splits on per-feature thresholds, so it is
invariant to monotone rescaling and needs no standardisation. Missing values: none exist in the frozen inputs;
any NaN/inf raises instead of being imputed.

Parameters: n_estimators=200, max_samples='auto' (min(256, n) = 150), contamination='auto' (so no anomaly
prevalence is assumed or leaked; contamination only moves a decision offset, never the ranking), max_features=1.0,
bootstrap=False, n_jobs=1, random_state=2303.
Score = -score_samples(X): higher = more anomalous.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from evaluation.baselines.cost_baseline import historical_benchmark

SCORE_COLUMN = "isolation_forest_score"
RANDOM_STATE = 2303
IF_PARAMS = {"n_estimators": 200, "max_samples": "auto", "contamination": "auto", "max_features": 1.0,
             "bootstrap": False, "n_jobs": 1, "random_state": RANDOM_STATE}
NEIGHBOR_RADIUS_KM = 5.0
FEATURES = ["log_cost_ratio", "sanction_over_estimate", "bill_count", "billed_over_sanctioned", "payment_count",
            "contractor_project_count", "neighbors_within_5km", "nearest_neighbor_km_log1p"]
FEATURE_PURPOSE = {
    "log_cost_ratio": "cost level relative to the work type's historical median, on a log scale",
    "sanction_over_estimate": "sanction versus the estimate: a standard procurement red flag",
    "bill_count": "billing activity volume",
    "billed_over_sanctioned": "share of the sanction already billed",
    "payment_count": "payment activity volume",
    "contractor_project_count": "contractor workload concentration within the pool",
    "neighbors_within_5km": "local project density",
    "nearest_neighbor_km_log1p": "spatial isolation from other projects",
}
PREPROCESSING = ("log transforms for log_cost_ratio and nearest_neighbor_km_log1p only; no scaling (tree splits are "
                 "scale-invariant); no categorical encoding; no imputation (NaN/inf raises); rows sorted by project_id.")


def _haversine_matrix_km(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    la, lo = np.radians(lat), np.radians(lon)
    dphi = la[:, None] - la[None, :]
    dl = lo[:, None] - lo[None, :]
    h = np.sin(dphi / 2) ** 2 + np.cos(la)[:, None] * np.cos(la)[None, :] * np.sin(dl / 2) ** 2
    return 2 * 6371.0088 * np.arcsin(np.sqrt(np.clip(h, 0.0, 1.0)))


def build_features(projects: pd.DataFrame, historical: pd.DataFrame, bills: pd.DataFrame,
                   payments: pd.DataFrame, locations: pd.DataFrame) -> pd.DataFrame:
    """One row per project, indexed by project_id (sorted), columns = FEATURES."""
    p = projects.copy()
    p["project_id"] = p["project_id"].astype(str)
    p = p.sort_values("project_id").reset_index(drop=True)
    amount = pd.to_numeric(p["sanctioned_amount"], errors="raise").astype(float)
    estimate = pd.to_numeric(p["estimated_cost"], errors="raise").astype(float)
    bench = p["work_type"].map(historical_benchmark(historical))
    if bench.isna().any():
        raise ValueError("work type without a historical benchmark")

    feats = pd.DataFrame(index=p["project_id"])
    feats["log_cost_ratio"] = np.log(amount.to_numpy() / bench.to_numpy())
    feats["sanction_over_estimate"] = (amount / estimate).to_numpy()

    b = bills.copy()
    b["project_id"] = b["project_id"].astype(str)
    b["claimed_amount"] = pd.to_numeric(b["claimed_amount"], errors="raise").astype(float)
    feats["bill_count"] = b.groupby("project_id").size().reindex(feats.index).fillna(0).to_numpy()
    claimed = b.groupby("project_id")["claimed_amount"].sum().reindex(feats.index).fillna(0.0)
    feats["billed_over_sanctioned"] = (claimed.to_numpy() / amount.to_numpy())

    pay = payments.copy()
    pay["project_id"] = pay["project_id"].astype(str)
    feats["payment_count"] = pay.groupby("project_id").size().reindex(feats.index).fillna(0).to_numpy()

    feats["contractor_project_count"] = p.groupby("contractor_id")["project_id"].transform("size").to_numpy()

    loc = locations.copy()
    loc["project_id"] = loc["project_id"].astype(str)
    loc = loc.set_index("project_id").reindex(feats.index)
    if loc[["latitude", "longitude"]].isna().any().any():
        raise ValueError("project without a location")
    d = _haversine_matrix_km(loc["latitude"].astype(float).to_numpy(), loc["longitude"].astype(float).to_numpy())
    np.fill_diagonal(d, np.inf)
    feats["neighbors_within_5km"] = (d <= NEIGHBOR_RADIUS_KM).sum(axis=1)
    feats["nearest_neighbor_km_log1p"] = np.log1p(d.min(axis=1))

    feats = feats[FEATURES].astype(float)
    if not np.isfinite(feats.to_numpy()).all():
        raise ValueError("non-finite feature value (no imputation is performed)")
    return feats


def score(features: pd.DataFrame) -> pd.DataFrame:
    """Fit the forest on the feature matrix only (no target) and return project_id + isolation_forest_score."""
    if list(features.columns) != FEATURES:
        raise ValueError(f"unexpected feature columns: {list(features.columns)}")
    X = features.to_numpy(dtype=float)
    model = IsolationForest(**IF_PARAMS)
    model.fit(X)
    s = -model.score_samples(X)
    if not np.isfinite(s).all():
        raise ValueError("non-finite isolation-forest score")
    out = pd.DataFrame({"project_id": features.index.astype(str), SCORE_COLUMN: s})
    return out.sort_values("project_id").reset_index(drop=True)
