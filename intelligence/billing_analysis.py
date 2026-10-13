"""
NidhiGuard Intelligence — Billing Anomaly Detector (max score: 20)

Looks at the TIMING pattern of a project's own bills — not whether the
arithmetic reconciles (the generator guarantees approved <= claimed and
payments <= approved for every bill in this dataset) — for two independent
signals:

  1. Compression: bills raised much closer together than an even spread
     across the project's own timeline would predict.
  2. End-loading: a disproportionate share of the total claimed amount
     concentrated in a bill raised close to (expected/actual) completion.

Both must clear a threshold relative to the PROJECT'S OWN timeline (not a
fixed number of days), so short projects with naturally close bills aren't
penalised just for being short.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

MAX_SCORE = 20
MIN_BILLS = 2
COMPRESSION_RATIO_THRESHOLD = 0.45   # avg gap below 45% of the "even spread" gap counts as compressed
CONCENTRATION_SHARE_THRESHOLD = 0.35  # bill nearest completion carrying >=35% of total claimed
COMPLETION_PROXIMITY_DAYS = 25        # "close to completion" window


@dataclass
class BillingAnomalyResult:
    score: float
    max_score: int = MAX_SCORE
    detected: bool = False
    evidence: list[str] = field(default_factory=list)
    explanation: str = ""


def score_billing_anomaly(project_row: pd.Series, project_bills: pd.DataFrame) -> BillingAnomalyResult:
    bills = project_bills.dropna(subset=["bill_date"]).sort_values("bill_date")
    n = len(bills)

    if n < MIN_BILLS:
        return BillingAnomalyResult(
            score=0.0,
            detected=False,
            explanation=f"Only {n} bill(s) recorded — too few to evaluate a billing timing pattern.",
        )

    evidence: list[str] = []
    compression_component = 0.0
    concentration_component = 0.0

    # --- 1. Compression: rather than averaging ALL gaps (which a single
    # early or late outlier bill can mask), look for the tightest cluster
    # of at least half the bills — "several bills within days of each
    # other" as described in the anomaly scenario docs — and compare that
    # cluster's span to what an even spread across the project's own
    # start -> last-bill timeline would predict for a window that size. ---
    span_start = project_row["start_date"] if pd.notna(project_row["start_date"]) else bills["bill_date"].iloc[0]
    span_end = bills["bill_date"].iloc[-1]
    total_span_days = max((span_end - span_start).days, 1)

    if n >= 3:
        dates = bills["bill_date"].tolist()
        window_size = max(3, -(-n // 2))  # ceil(n/2), at least 3
        window_size = min(window_size, n)

        best_ratio = None
        best_window_span = None
        for i in range(0, n - window_size + 1):
            window = dates[i:i + window_size]
            window_span = (window[-1] - window[0]).days
            expected_window_span = total_span_days * (window_size - 1) / (n - 1) if n > 1 else total_span_days
            ratio = window_span / expected_window_span if expected_window_span > 0 else 1.0
            if best_ratio is None or ratio < best_ratio:
                best_ratio = ratio
                best_window_span = window_span

        if best_ratio is not None and best_ratio < COMPRESSION_RATIO_THRESHOLD:
            compression_component = min(10.0, (1 - best_ratio / COMPRESSION_RATIO_THRESHOLD) * 10 + 4)
            evidence.append(
                f"{window_size} of the {n} bills fall within a {best_window_span}-day window, far tighter than "
                f"an even spread across the project's {total_span_days}-day timeline would predict "
                f"(compression ratio {best_ratio:.2f})."
            )

    # --- 2. End-loading: share of total claimed amount in a bill raised
    # close to completion. ---
    completion_date = project_row["actual_completion_date"]
    if pd.isna(completion_date):
        completion_date = project_row["expected_completion_date"]

    total_claimed = bills["claimed_amount"].sum()
    if pd.notna(completion_date) and total_claimed > 0:
        bills = bills.assign(days_to_completion=(completion_date - bills["bill_date"]).dt.days.abs())
        near_completion = bills[bills["days_to_completion"] <= COMPLETION_PROXIMITY_DAYS]
        if not near_completion.empty:
            near_share = near_completion["claimed_amount"].sum() / total_claimed
            if near_share >= CONCENTRATION_SHARE_THRESHOLD:
                concentration_component = min(10.0, near_share * 20)
                evidence.append(
                    f"{near_share:.0%} of total claimed amount (₹{near_completion['claimed_amount'].sum():,.0f} "
                    f"of ₹{total_claimed:,.0f}) is concentrated in bill(s) raised within "
                    f"{COMPLETION_PROXIMITY_DAYS} days of project completion."
                )

    score = round(min(MAX_SCORE, compression_component + concentration_component), 1)
    detected = score > 0

    if not detected:
        explanation = (
            f"Bill timing across the {n} bills follows a broadly expected cadence "
            f"relative to the project's own timeline — no compression or end-loading pattern detected."
        )
    else:
        explanation = " ".join(evidence) + " This is a timing pattern requiring review, not proof of any wrongdoing."

    return BillingAnomalyResult(
        score=score,
        detected=detected,
        evidence=evidence,
        explanation=explanation,
    )
