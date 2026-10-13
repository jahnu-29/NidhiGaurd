"""
NidhiGuard Intelligence — Relationship Intelligence Engine (Stage 5A, Part 1)

Answers a different question from Stage 4:

  Stage 4: "How anomalous is this project?"
  Stage 5: "What other entities and projects are connected to this project,
            and what evidence supports that connection?"

This module is INDEPENDENT of Stage 4. It does not import risk_engine, does
not read a project's risk_score/risk_level, and does not use
anomaly_signals.csv for anything. relationship_strength is a measure of how
strongly two entities are connected according to the dataset alone — it is
NOT a fraud, collusion, or corruption probability, and a high value must
never be described as such.

Two kinds of relationships are produced:

  1. DIRECT edges — deterministic foreign-key relationships that exist
     because the dataset says so (a project's contractor, its bills, a
     bill's payments, its location). relationship_strength = 100 for these;
     there's no gradient to compute, they either exist or they don't.

  2. ANALYTICAL edges — PROJECT_PROJECT relationships discovered by
     comparing attributes across all 200 current projects (no shared ID
     used to find them, the same way project_similarity.py works for
     Stage 4). A single shared attribute is NEVER enough on its own; the
     weighted formula below is what produces the strength.

RELATIONSHIP_STRENGTH FORMULA (documented, deterministic, bounded 0-100):

    same_contractor        -> 20 points if true
    same_work_type          -> 10 points if true
    same_district            -> 10 points if true
    geographic proximity   -> up to 15 points, linear decay to 0 at
                               GEO_PROXIMITY_DECAY_KM
    description similarity -> up to 25 points = 25 * TF-IDF cosine similarity
    cost similarity         -> up to 10 points = 10 * (1 - |a-b|/max(a,b))
    date proximity           -> up to 10 points, linear decay to 0 at
                               DATE_PROXIMITY_DECAY_DAYS (sanction_date gap)

    Weights sum to 100. Any missing input (no location on record, no
    sanction_date, zero cost) simply contributes 0 for that term rather
    than being estimated or skipped from the denominator.

Only pairs reaching RELATIONSHIP_REPORT_THRESHOLD are included in the
output — this keeps ~19,900 possible pairs down to the ones with enough
combined evidence to be worth an investigator's attention. The threshold
is a reporting cutoff, not a suspicion cutoff.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from math import radians, sin, cos, asin, sqrt
from typing import Any

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .data_loader import Dataset

# ---------------------------------------------------------------------------
# Formula constants (see module docstring)
# ---------------------------------------------------------------------------
SAME_CONTRACTOR_WEIGHT = 20.0
SAME_WORK_TYPE_WEIGHT = 10.0
SAME_DISTRICT_WEIGHT = 10.0
PROXIMITY_WEIGHT = 15.0
DESCRIPTION_SIMILARITY_WEIGHT = 25.0
COST_SIMILARITY_WEIGHT = 10.0
DATE_PROXIMITY_WEIGHT = 10.0

GEO_PROXIMITY_DECAY_KM = 10.0     # beyond this distance, proximity term = 0
DATE_PROXIMITY_DECAY_DAYS = 365   # beyond this sanction-date gap, term = 0

RELATIONSHIP_REPORT_THRESHOLD = 15.0  # minimum strength to appear in output

# Multi-hop paths are only built from analytical relationships at least this
# strong, so the traversal explains something beyond a bare contractor link.
MULTI_HOP_MIN_STRENGTH = 35.0
MAX_MULTI_HOP_PATHS_PER_PROJECT = 3
MAX_MULTI_HOP_PATHS_TOTAL = 500


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(a))


# ---------------------------------------------------------------------------
# Analytical PROJECT_PROJECT relationships
# ---------------------------------------------------------------------------

@dataclass
class RelationshipEvidence:
    same_contractor: bool
    same_work_type: bool
    same_district: bool
    same_state: bool
    distance_km: float | None
    description_similarity: float
    cost_similarity: float | None
    date_proximity: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RelationshipIndex:
    """Precomputes the TF-IDF description matrix once for all current
    projects, the same way project_similarity.SimilarityIndex does for
    Stage 4, so per-pair evidence lookups don't refit a vectorizer."""

    def __init__(self, projects: pd.DataFrame, locations: pd.DataFrame):
        self.projects = projects.reset_index(drop=True)
        self.locations_by_project = locations.set_index("project_id")

        descriptions = self.projects["project_description"].fillna("").tolist()
        vectorizer = TfidfVectorizer(stop_words="english", min_df=1)
        tfidf_matrix = vectorizer.fit_transform(descriptions)
        self.text_sim_matrix = cosine_similarity(tfidf_matrix)

        self.id_to_index = {pid: i for i, pid in enumerate(self.projects["project_id"])}

    def _distance_km(self, pid_a: str, pid_b: str) -> float | None:
        if pid_a not in self.locations_by_project.index or pid_b not in self.locations_by_project.index:
            return None
        la = self.locations_by_project.loc[pid_a]
        lb = self.locations_by_project.loc[pid_b]
        if pd.isna(la["latitude"]) or pd.isna(la["longitude"]) or pd.isna(lb["latitude"]) or pd.isna(lb["longitude"]):
            return None
        return _haversine_km(la["latitude"], la["longitude"], lb["latitude"], lb["longitude"])

    def pair_evidence(self, pid_a: str, pid_b: str) -> tuple[RelationshipEvidence, float]:
        """Returns (evidence, relationship_strength) for an unordered pair.
        Deterministic — same inputs always produce the same output."""
        ia = self.id_to_index[pid_a]
        ib = self.id_to_index[pid_b]
        row_a = self.projects.iloc[ia]
        row_b = self.projects.iloc[ib]

        same_contractor = bool(row_a["contractor_id"] == row_b["contractor_id"])
        same_work_type = bool(row_a["work_type"] == row_b["work_type"])
        same_district = bool(row_a["district_id"] == row_b["district_id"])
        same_state = bool(row_a["state"] == row_b["state"])

        description_similarity = float(self.text_sim_matrix[ia, ib])

        distance_km = self._distance_km(pid_a, pid_b)
        proximity_term = 0.0
        if distance_km is not None:
            proximity_term = max(0.0, 1.0 - distance_km / GEO_PROXIMITY_DECAY_KM)

        cost_similarity = None
        cost_term = 0.0
        amt_a, amt_b = row_a["sanctioned_amount"], row_b["sanctioned_amount"]
        if pd.notna(amt_a) and pd.notna(amt_b) and max(amt_a, amt_b) > 0:
            cost_similarity = max(0.0, 1.0 - abs(amt_a - amt_b) / max(amt_a, amt_b))
            cost_term = cost_similarity

        date_proximity = None
        date_term = 0.0
        date_a, date_b = row_a["sanction_date"], row_b["sanction_date"]
        if pd.notna(date_a) and pd.notna(date_b):
            gap_days = abs((date_a - date_b).days)
            date_proximity = max(0.0, 1.0 - gap_days / DATE_PROXIMITY_DECAY_DAYS)
            date_term = date_proximity

        strength = (
            (SAME_CONTRACTOR_WEIGHT if same_contractor else 0.0)
            + (SAME_WORK_TYPE_WEIGHT if same_work_type else 0.0)
            + (SAME_DISTRICT_WEIGHT if same_district else 0.0)
            + PROXIMITY_WEIGHT * proximity_term
            + DESCRIPTION_SIMILARITY_WEIGHT * description_similarity
            + COST_SIMILARITY_WEIGHT * cost_term
            + DATE_PROXIMITY_WEIGHT * date_term
        )
        strength = round(min(100.0, strength), 1)

        evidence = RelationshipEvidence(
            same_contractor=same_contractor,
            same_work_type=same_work_type,
            same_district=same_district,
            same_state=same_state,
            distance_km=round(distance_km, 2) if distance_km is not None else None,
            description_similarity=round(description_similarity, 3),
            cost_similarity=round(cost_similarity, 3) if cost_similarity is not None else None,
            date_proximity=round(date_proximity, 3) if date_proximity is not None else None,
        )
        return evidence, strength


def build_relationship_index(projects: pd.DataFrame, locations: pd.DataFrame) -> RelationshipIndex:
    return RelationshipIndex(projects, locations)


def _evidence_reasons(evidence: RelationshipEvidence) -> list[str]:
    reasons = []
    if evidence.same_contractor:
        reasons.append("same contractor")
    if evidence.same_work_type:
        reasons.append("same work type")
    if evidence.same_district:
        reasons.append("same district")
    if evidence.distance_km is not None and evidence.distance_km <= GEO_PROXIMITY_DECAY_KM:
        reasons.append(f"~{evidence.distance_km} km apart")
    if evidence.description_similarity >= 0.3:
        reasons.append(f"description similarity {evidence.description_similarity:.0%}")
    if evidence.cost_similarity is not None and evidence.cost_similarity >= 0.7:
        reasons.append("comparable sanctioned amount")
    if evidence.date_proximity is not None and evidence.date_proximity >= 0.7:
        reasons.append("sanctioned close together in time")
    return reasons


def generate_project_relationships(
    index: RelationshipIndex,
    threshold: float = RELATIONSHIP_REPORT_THRESHOLD,
) -> list[dict[str, Any]]:
    """All PROJECT_PROJECT analytical relationships reaching `threshold`,
    one record per unordered pair. Deterministic given the same dataset."""
    project_ids = list(index.projects["project_id"])
    results: list[dict[str, Any]] = []

    for i in range(len(project_ids)):
        for j in range(i + 1, len(project_ids)):
            pid_a, pid_b = project_ids[i], project_ids[j]
            evidence, strength = index.pair_evidence(pid_a, pid_b)
            if strength < threshold:
                continue
            reasons = _evidence_reasons(evidence)
            results.append({
                "source": pid_a,
                "target": pid_b,
                "relationship_type": "PROJECT_PROJECT",
                "relationship_strength": strength,
                "evidence": evidence.to_dict(),
                "explanation": (
                    f"Relationship detected between {pid_a} and {pid_b} "
                    f"({', '.join(reasons) if reasons else 'combined attribute overlap'})."
                ),
            })

    results.sort(key=lambda r: r["relationship_strength"], reverse=True)
    return results


def relationships_for_project(
    project_id: str,
    all_relationships: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        r for r in all_relationships
        if r["source"] == project_id or r["target"] == project_id
    ]


# ---------------------------------------------------------------------------
# Direct (foreign-key) edges
# ---------------------------------------------------------------------------

def build_direct_edges(dataset: Dataset) -> list[dict[str, Any]]:
    """Deterministic graph edges that exist purely because the relational
    dataset says so. relationship_strength is always 100 — these are not
    inferred, they're read straight off a foreign key."""
    edges: list[dict[str, Any]] = []

    for _, row in dataset.project_contractors.iterrows():
        edges.append({
            "source": row["project_id"],
            "target": row["contractor_id"],
            "relationship_type": "PROJECT_CONTRACTOR",
            "relationship_strength": 100.0,
            "evidence": {
                "relationship_id": row["relationship_id"],
                "role": row["role"],
                "contract_value": row["contract_value"] if pd.notna(row["contract_value"]) else None,
                "award_date": str(row["award_date"].date()) if pd.notna(row["award_date"]) else None,
            },
            "explanation": f"{row['project_id']} awarded to contractor {row['contractor_id']} ({row['role']}).",
        })

    for _, row in dataset.bills.iterrows():
        edges.append({
            "source": row["project_id"],
            "target": row["bill_id"],
            "relationship_type": "PROJECT_BILL",
            "relationship_strength": 100.0,
            "evidence": {
                "bill_number": row["bill_number"],
                "bill_status": row["bill_status"],
                "claimed_amount": row["claimed_amount"] if pd.notna(row["claimed_amount"]) else None,
            },
            "explanation": f"{row['project_id']} has bill {row['bill_id']} ({row['bill_number']}).",
        })

    for _, row in dataset.payments.iterrows():
        edges.append({
            "source": row["bill_id"],
            "target": row["payment_id"],
            "relationship_type": "BILL_PAYMENT",
            "relationship_strength": 100.0,
            "evidence": {
                "payment_amount": row["payment_amount"] if pd.notna(row["payment_amount"]) else None,
                "payment_status": row["payment_status"],
            },
            "explanation": f"Bill {row['bill_id']} has payment {row['payment_id']}.",
        })

    for _, row in dataset.locations.iterrows():
        edges.append({
            "source": row["project_id"],
            "target": row["location_id"],
            "relationship_type": "PROJECT_LOCATION",
            "relationship_strength": 100.0,
            "evidence": {
                "state": row["state"],
                "district": row["district"],
                "location_type": row["location_type"],
            },
            "explanation": f"{row['project_id']} is located at {row['location_id']} ({row['district']}, {row['state']}).",
        })

    return edges


# ---------------------------------------------------------------------------
# Contractor network analysis
# ---------------------------------------------------------------------------

def build_contractor_network(dataset: Dataset) -> list[dict[str, Any]]:
    """Per-contractor summary of their current-dataset footprint. A large
    portfolio is reported as a fact, never labelled suspicious by itself."""
    projects = dataset.projects
    results: list[dict[str, Any]] = []

    for _, contractor in dataset.contractors.iterrows():
        contractor_id = contractor["contractor_id"]
        portfolio = projects[projects["contractor_id"] == contractor_id]
        if portfolio.empty:
            continue  # contractor exists in contractors.csv but has no current project

        project_ids = sorted(portfolio["project_id"].tolist())
        project_pairs = [
            [project_ids[i], project_ids[j]]
            for i in range(len(project_ids))
            for j in range(i + 1, len(project_ids))
        ]

        results.append({
            "contractor_id": contractor_id,
            "contractor_name": contractor["contractor_name"],
            "total_projects": len(project_ids),
            "total_project_value": round(float(portfolio["sanctioned_amount"].sum()), 2),
            "work_types": sorted(portfolio["work_type"].dropna().unique().tolist()),
            "districts": sorted(portfolio["district_id"].dropna().unique().tolist()),
            "states": sorted(portfolio["state"].dropna().unique().tolist()),
            "connected_projects": project_ids,
            "project_pairs": project_pairs,
        })

    results.sort(key=lambda c: c["total_projects"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Multi-hop paths
# ---------------------------------------------------------------------------

def build_multi_hop_paths(
    dataset: Dataset,
    project_relationships: list[dict[str, Any]],
    min_strength: float = MULTI_HOP_MIN_STRENGTH,
) -> list[dict[str, Any]]:
    """Meaningful 2-4 hop traversals: PROJECT -> CONTRACTOR -> PROJECT, and
    PROJECT -> CONTRACTOR -> PROJECT -> LOCATION when the target's location
    is on record. Only built from analytical relationships that are already
    strong (`min_strength`) AND share a contractor, so every path traverses
    a real edge at every hop rather than jumping on attribute similarity
    alone. Capped per-project and in total to stay to "meaningful" paths,
    not an exhaustive graph dump."""
    locations_by_project = dataset.locations.set_index("project_id")
    paths: list[dict[str, Any]] = []
    per_project_count: dict[str, int] = {}

    candidates = [
        r for r in project_relationships
        if r["relationship_strength"] >= min_strength and r["evidence"]["same_contractor"]
    ]
    candidates.sort(key=lambda r: r["relationship_strength"], reverse=True)

    for rel in candidates:
        if len(paths) >= MAX_MULTI_HOP_PATHS_TOTAL:
            break
        source, target = rel["source"], rel["target"]
        if per_project_count.get(source, 0) >= MAX_MULTI_HOP_PATHS_PER_PROJECT:
            continue

        contractor_id = dataset.projects.loc[
            dataset.projects["project_id"] == source, "contractor_id"
        ].iloc[0]

        reasons = _evidence_reasons(
            RelationshipEvidence(**{k: v for k, v in rel["evidence"].items()})
        )
        extra_reasons = [r for r in reasons if r != "same contractor"]

        nodes = [
            {"type": "PROJECT", "id": source},
            {"type": "CONTRACTOR", "id": contractor_id},
            {"type": "PROJECT", "id": target},
        ]
        hops = [
            {"from": source, "to": contractor_id, "relationship_type": "PROJECT_CONTRACTOR"},
            {"from": contractor_id, "to": target, "relationship_type": "PROJECT_CONTRACTOR"},
        ]

        if target in locations_by_project.index:
            loc_id = locations_by_project.loc[target, "location_id"]
            nodes.append({"type": "LOCATION", "id": loc_id})
            hops.append({"from": target, "to": loc_id, "relationship_type": "PROJECT_LOCATION"})

        explanation = (
            f"{source} shares contractor {contractor_id} with {target}"
            + (f", also connected by {', '.join(extra_reasons)}" if extra_reasons else "")
            + f" (relationship_strength {rel['relationship_strength']})."
        )

        paths.append({
            "nodes": nodes,
            "hops": hops,
            "relationship_strength": rel["relationship_strength"],
            "explanation": explanation,
        })
        per_project_count[source] = per_project_count.get(source, 0) + 1

    return paths
