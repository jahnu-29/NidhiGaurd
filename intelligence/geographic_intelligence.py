"""
NidhiGuard Intelligence — Geospatial Intelligence Engine (Stage 5A, Part 2)

Haversine-based geographic context for investigators. This module is
INDEPENDENT of Stage 4: it does not read risk_score/risk_level and does not
use anomaly_signals.csv.

PROXIMITY ALONE IS NEVER TREATED AS AN ANOMALY. Every output here is framed
as "relationship detected" / "potential duplicate-like pattern", never as a
confirmed finding.

For per-pair evidence (same_contractor, same_work_type, description
similarity, cost similarity, date proximity) this module reuses
`relationship_analysis.RelationshipIndex.pair_evidence`, the same formula
Part 1 uses, rather than recomputing an independent similarity metric. This
is a deliberate design choice: it keeps "how similar are these two
projects" defined in exactly one place, so a project pair can't show a
different similarity number in the geographic output than in the
relationship output. See relationship_analysis.py for the formula.

Default investigation radius: 2 km (configurable via `radius_km`).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from math import radians, sin, cos, asin, sqrt
from typing import Any

import pandas as pd

from .data_loader import Dataset
from .relationship_analysis import RelationshipIndex, build_relationship_index, _evidence_reasons

DEFAULT_RADIUS_KM = 2.0

# "Potential duplicate-like pattern" thresholds — all four must hold.
DUPLICATE_DISTANCE_KM = 2.0
DUPLICATE_DESCRIPTION_SIMILARITY = 0.5
DUPLICATE_COST_SIMILARITY = 0.7
DUPLICATE_DATE_PROXIMITY = 0.3  # sanctioned within ~roughly a year of each other


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(a))


# ---------------------------------------------------------------------------
# Nearby project analysis
# ---------------------------------------------------------------------------

class GeospatialEngine:
    """Precomputes the pairwise Haversine distance matrix once for all
    current projects with a location on record, the same pattern
    geographic_analysis.GeographicIndex uses for Stage 4."""

    def __init__(self, dataset: Dataset, radius_km: float = DEFAULT_RADIUS_KM,
                 relationship_index: RelationshipIndex | None = None):
        self.dataset = dataset
        self.radius_km = radius_km
        self.relationship_index = relationship_index or build_relationship_index(
            dataset.projects, dataset.locations
        )

        merged = dataset.projects.merge(
            dataset.locations[["project_id", "location_id", "latitude", "longitude"]],
            on="project_id", how="left",
        ).reset_index(drop=True)
        self.merged = merged
        self.id_to_index = {pid: i for i, pid in enumerate(merged["project_id"])}

    def nearby(self, project_id: str) -> list[dict[str, Any]]:
        """Every other current project within `radius_km`, each with full
        pairwise evidence. Proximity alone never appears without the rest
        of the evidence dict alongside it."""
        idx = self.id_to_index[project_id]
        row = self.merged.iloc[idx]
        if pd.isna(row["latitude"]) or pd.isna(row["longitude"]):
            return []

        results: list[dict[str, Any]] = []
        for j, other_id in enumerate(self.merged["project_id"]):
            if other_id == project_id:
                continue
            other = self.merged.iloc[j]
            if pd.isna(other["latitude"]) or pd.isna(other["longitude"]):
                continue
            distance = _haversine_km(row["latitude"], row["longitude"], other["latitude"], other["longitude"])
            if distance > self.radius_km:
                continue

            evidence, strength = self.relationship_index.pair_evidence(project_id, other_id)
            reasons = _evidence_reasons(evidence)

            results.append({
                "project_id": other_id,
                "distance_km": round(distance, 3),
                "same_work_type": evidence.same_work_type,
                "same_contractor": evidence.same_contractor,
                "description_similarity": evidence.description_similarity,
                "cost_similarity": evidence.cost_similarity,
                "date_proximity": evidence.date_proximity,
                "relationship_strength": strength,
                "evidence": reasons,
                "explanation": (
                    f"Nearby project relationship detected ({distance:.2f} km) "
                    f"— {', '.join(reasons) if reasons else 'proximity only, no shared attributes'}."
                ),
            })

        results.sort(key=lambda r: r["distance_km"])
        return results

    def all_nearby_relationships(self) -> list[dict[str, Any]]:
        """Flat list of every (source, target) pair within radius_km,
        deduplicated to one record per unordered pair (source_id < target_id
        lexicographically) for the JSON/CSV output."""
        flat: list[dict[str, Any]] = []
        for pid in self.merged["project_id"]:
            for entry in self.nearby(pid):
                other = entry["project_id"]
                if pid < other:  # dedupe: report each unordered pair once
                    flat.append({"source": pid, "target": other, **{k: v for k, v in entry.items() if k != "project_id"}})
        flat.sort(key=lambda r: r["relationship_strength"], reverse=True)
        return flat


def build_geospatial_engine(dataset: Dataset, radius_km: float = DEFAULT_RADIUS_KM,
                             relationship_index: RelationshipIndex | None = None) -> GeospatialEngine:
    return GeospatialEngine(dataset, radius_km=radius_km, relationship_index=relationship_index)


# ---------------------------------------------------------------------------
# Potential duplicate-like projects
# ---------------------------------------------------------------------------

def find_duplicate_like_matches(nearby_relationships: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project pairs combining close distance, high description similarity,
    same work type, and comparable cost. Framed strictly as
    "potential duplicate-like pattern" — never "duplicate confirmed"."""
    matches = []
    for rel in nearby_relationships:
        if rel["distance_km"] > DUPLICATE_DISTANCE_KM:
            continue
        if rel["description_similarity"] < DUPLICATE_DESCRIPTION_SIMILARITY:
            continue
        if not rel["same_work_type"]:
            continue
        if rel["cost_similarity"] is None or rel["cost_similarity"] < DUPLICATE_COST_SIMILARITY:
            continue

        shared = ["work type", "location proximity", "description similarity", "comparable cost"]
        if rel["same_contractor"]:
            shared.append("same contractor")

        matches.append({
            "project_a": rel["source"],
            "project_b": rel["target"],
            "distance_km": rel["distance_km"],
            "description_similarity": rel["description_similarity"],
            "cost_similarity": rel["cost_similarity"],
            "shared_attributes": shared,
            "relationship_strength": rel["relationship_strength"],
            "explanation": (
                f"Potential duplicate-like pattern between {rel['source']} and {rel['target']}: "
                f"{rel['distance_km']} km apart, {rel['description_similarity']:.0%} description "
                f"similarity, same work type, comparable sanctioned amount "
                f"({rel['cost_similarity']:.0%} cost similarity). Requires review, not a confirmed duplicate."
            ),
        })

    matches.sort(key=lambda m: m["relationship_strength"], reverse=True)
    return matches


# ---------------------------------------------------------------------------
# Geographic clusters (connected components within radius_km)
# ---------------------------------------------------------------------------

class _UnionFind:
    def __init__(self, items: list[str]):
        self.parent = {item: item for item in items}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def build_geographic_clusters(engine: GeospatialEngine) -> list[dict[str, Any]]:
    """Connected components of projects transitively within radius_km of
    each other. A cluster is context for an investigator, never
    automatically suspicious."""
    project_ids = [
        pid for pid in engine.merged["project_id"]
        if pd.notna(engine.id_to_index.get(pid)) and not pd.isna(engine.merged.iloc[engine.id_to_index[pid]]["latitude"])
    ]
    uf = _UnionFind(project_ids)

    for pid in project_ids:
        for entry in engine.nearby(pid):
            if entry["project_id"] in uf.parent:
                uf.union(pid, entry["project_id"])

    groups: dict[str, list[str]] = {}
    for pid in project_ids:
        root = uf.find(pid)
        groups.setdefault(root, []).append(pid)

    clusters = []
    cluster_num = 0
    locations_by_project = engine.dataset.locations.set_index("project_id")
    for root, members in groups.items():
        if len(members) < 2:
            continue
        cluster_num += 1
        member_locs = locations_by_project.loc[members]
        center_lat = float(member_locs["latitude"].mean())
        center_lon = float(member_locs["longitude"].mean())
        max_radius = max(
            _haversine_km(center_lat, center_lon, r["latitude"], r["longitude"])
            for _, r in member_locs.iterrows()
        )

        member_projects = engine.dataset.projects[engine.dataset.projects["project_id"].isin(members)]
        work_type_counts = member_projects["work_type"].value_counts()
        common_work_types = sorted(work_type_counts[work_type_counts >= 2].index.tolist())
        contractor_counts = member_projects["contractor_id"].value_counts()
        shared_contractors = sorted(contractor_counts[contractor_counts >= 2].index.tolist())

        clusters.append({
            "cluster_id": f"GEO-CLUSTER-{cluster_num:03d}",
            "project_count": len(members),
            "project_ids": sorted(members),
            "approximate_center": {"latitude": round(center_lat, 5), "longitude": round(center_lon, 5)},
            "radius_km": round(max_radius, 2),
            "common_work_types": common_work_types,
            "shared_contractors": shared_contractors,
        })

    clusters.sort(key=lambda c: c["project_count"], reverse=True)
    return clusters
