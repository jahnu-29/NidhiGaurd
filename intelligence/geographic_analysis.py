"""
NidhiGuard Intelligence — Geographic Signal Detector (max score: 10)

Finds projects that sit inside a tight geographic cluster (via Haversine
distance on locations.csv) that ALSO shares other attributes — same
work_type, comparable sanctioned_amount, or the same contractor — with
enough of its neighbours. Proximity alone is never sufficient; the
combination is what raises the score.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import radians, sin, cos, asin, sqrt

import numpy as np
import pandas as pd

MAX_SCORE = 10
PROXIMITY_KM = 2.0
MIN_NEARBY_FOR_CLUSTER = 2       # need at least 2 other nearby projects to call it a cluster
AMOUNT_TOLERANCE = 0.3
MIN_ATTRIBUTE_SHARE_RATIO = 0.4  # at least 40% of nearby cluster members must share an attribute


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(a))


@dataclass
class GeographicSignalResult:
    score: float
    max_score: int = MAX_SCORE
    detected: bool = False
    nearby_project_count: int = 0
    attribute_sharing_count: int = 0
    nearby_project_ids: list[str] = field(default_factory=list)
    explanation: str = ""


class GeographicIndex:
    """Precomputes pairwise Haversine distances once for all current
    projects (joined to their locations) rather than recomputing per call."""

    def __init__(self, projects: pd.DataFrame, locations: pd.DataFrame):
        merged = projects.merge(
            locations[["project_id", "latitude", "longitude"]], on="project_id", how="left"
        ).reset_index(drop=True)
        self.merged = merged
        self.id_to_index = {pid: i for i, pid in enumerate(merged["project_id"])}

        n = len(merged)
        lat = merged["latitude"].to_numpy()
        lon = merged["longitude"].to_numpy()
        dist = np.zeros((n, n))
        for i in range(n):
            if np.isnan(lat[i]) or np.isnan(lon[i]):
                dist[i, :] = np.inf
                continue
            for j in range(i + 1, n):
                if np.isnan(lat[j]) or np.isnan(lon[j]):
                    d = np.inf
                else:
                    d = _haversine_km(lat[i], lon[i], lat[j], lon[j])
                dist[i, j] = d
                dist[j, i] = d
        self.dist_matrix = dist

    def score(self, project_id: str) -> GeographicSignalResult:
        idx = self.id_to_index[project_id]
        row = self.merged.iloc[idx]

        if pd.isna(row["latitude"]) or pd.isna(row["longitude"]):
            return GeographicSignalResult(score=0.0, detected=False, explanation="No location on record for this project.")

        distances = self.dist_matrix[idx]
        nearby_mask = (distances <= PROXIMITY_KM) & (distances > 0)
        nearby_indices = np.where(nearby_mask)[0]

        if len(nearby_indices) < MIN_NEARBY_FOR_CLUSTER:
            return GeographicSignalResult(
                score=0.0,
                detected=False,
                nearby_project_count=int(len(nearby_indices)),
                explanation=(
                    f"Fewer than {MIN_NEARBY_FOR_CLUSTER} other current projects lie within "
                    f"{PROXIMITY_KM} km — no geographic cluster to evaluate."
                ),
            )

        nearby = self.merged.iloc[nearby_indices]
        same_work_type = (nearby["work_type"] == row["work_type"]).sum()
        same_contractor = (nearby["contractor_id"] == row["contractor_id"]).sum()
        amount_ok = row["sanctioned_amount"] > 0
        comparable_amount = 0
        if amount_ok:
            ratio = nearby["sanctioned_amount"] / row["sanctioned_amount"]
            comparable_amount = ((ratio >= 1 - AMOUNT_TOLERANCE) & (ratio <= 1 + AMOUNT_TOLERANCE)).sum()

        # A neighbour "shares an attribute" if it matches on work type,
        # contractor, or comparable cost.
        shares_attr = (
            (nearby["work_type"] == row["work_type"])
            | (nearby["contractor_id"] == row["contractor_id"])
            | ((nearby["sanctioned_amount"] / row["sanctioned_amount"]).between(1 - AMOUNT_TOLERANCE, 1 + AMOUNT_TOLERANCE)
               if amount_ok else False)
        )
        attribute_sharing_count = int(shares_attr.sum())
        share_ratio = attribute_sharing_count / len(nearby_indices)

        detected = share_ratio >= MIN_ATTRIBUTE_SHARE_RATIO

        if not detected:
            return GeographicSignalResult(
                score=0.0,
                detected=False,
                nearby_project_count=int(len(nearby_indices)),
                attribute_sharing_count=attribute_sharing_count,
                nearby_project_ids=sorted(nearby["project_id"].tolist()),
                explanation=(
                    f"{len(nearby_indices)} other project(s) lie within {PROXIMITY_KM} km, but only "
                    f"{attribute_sharing_count} share work type, contractor, or comparable cost — "
                    f"proximity alone is not treated as a signal."
                ),
            )

        cluster_component = min(6.0, len(nearby_indices) * 1.5)
        attribute_component = min(4.0, share_ratio * 4)
        score = round(min(MAX_SCORE, cluster_component + attribute_component), 1)

        attr_bits = []
        if same_work_type:
            attr_bits.append(f"{int(same_work_type)} sharing work type")
        if same_contractor:
            attr_bits.append(f"{int(same_contractor)} sharing the same contractor")
        if comparable_amount:
            attr_bits.append(f"{int(comparable_amount)} with comparable sanctioned amount")

        explanation = (
            f"{len(nearby_indices)} nearby project(s) within {PROXIMITY_KM} km, of which "
            f"{attribute_sharing_count} also share an attribute with this project "
            f"({', '.join(attr_bits) if attr_bits else 'overlapping characteristics'}) — "
            f"a geographic relationship pattern requiring review."
        )

        return GeographicSignalResult(
            score=score,
            detected=True,
            nearby_project_count=int(len(nearby_indices)),
            attribute_sharing_count=attribute_sharing_count,
            nearby_project_ids=sorted(nearby["project_id"].tolist()),
            explanation=explanation,
        )


def build_geographic_index(projects: pd.DataFrame, locations: pd.DataFrame) -> GeographicIndex:
    return GeographicIndex(projects, locations)
