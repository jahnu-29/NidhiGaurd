"""
NidhiGuard Intelligence — Explainable Risk Engine

Combines the five independent detectors into a single explainable result
per project. No detector here reads anomaly_signals.csv — that file is
reserved for validation/reporting only (see main.py).

risk_score = cost + similarity + contractor + billing + geographic (0-100)

Risk levels:
  0-29   LOW
  30-59  MEDIUM
  60-79  HIGH
  80-100 CRITICAL
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import pandas as pd

from .cost_anomaly import score_cost_anomaly
from .project_similarity import SimilarityIndex
from .contractor_analysis import score_contractor_pattern
from .billing_analysis import score_billing_anomaly
from .geographic_analysis import GeographicIndex
from .data_loader import Dataset

DISCLAIMER = "Risk score indicates anomaly signals and does not constitute a finding of fraud."


def classify_risk_level(score: float) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


def _recommendation(level: str) -> str:
    return {
        "CRITICAL": "Priority investigation recommended",
        "HIGH": "Investigation recommended",
        "MEDIUM": "Review recommended",
        "LOW": "No immediate action indicated",
    }[level]


@dataclass
class ProjectRiskResult:
    project_id: str
    risk_score: float
    risk_level: str
    components: dict[str, dict[str, Any]]
    recommendation: str
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RiskEngine:
    """Holds the two detectors that benefit from precomputing an index
    across all projects (similarity, geographic) and exposes a single
    `score_project` / `score_all` entry point."""

    def __init__(self, dataset: Dataset):
        self.dataset = dataset
        self.projects = dataset.projects
        self.similarity_index = SimilarityIndex(dataset.projects, dataset.locations)
        self.geographic_index = GeographicIndex(dataset.projects, dataset.locations)

    def score_project(self, project_id: str) -> ProjectRiskResult:
        project_row = self.projects[self.projects["project_id"] == project_id].iloc[0]
        project_bills = self.dataset.bills[self.dataset.bills["project_id"] == project_id]

        cost = score_cost_anomaly(project_row, self.projects, self.dataset.historical_projects)
        similarity = self.similarity_index.score(project_id)
        contractor = score_contractor_pattern(project_row, self.projects)
        billing = score_billing_anomaly(project_row, project_bills)
        geographic = self.geographic_index.score(project_id)

        components = {
            "cost_anomaly": {
                "score": cost.score, "max_score": cost.max_score, "detected": cost.detected,
                "benchmark_mean": cost.benchmark_mean, "benchmark_median": cost.benchmark_median,
                "current_value": cost.current_value, "percentage_difference": cost.percentage_difference,
                "comparable_count": cost.comparable_count, "explanation": cost.explanation,
            },
            "project_similarity": {
                "score": similarity.score, "max_score": similarity.max_score, "detected": similarity.detected,
                "matches": [
                    {"project_id": m.project_id, "combined_score": m.combined_score,
                     "text_similarity": m.text_similarity, "reasons": m.reasons}
                    for m in similarity.matches
                ],
                "explanation": similarity.explanation,
            },
            "contractor_pattern": {
                "score": contractor.score, "max_score": contractor.max_score, "detected": contractor.detected,
                "contractor_id": contractor.contractor_id, "portfolio_size": contractor.portfolio_size,
                "cluster_size": contractor.cluster_size, "cost_premium_pct": contractor.cost_premium_pct,
                "cluster_project_ids": contractor.cluster_project_ids, "explanation": contractor.explanation,
            },
            "billing_anomaly": {
                "score": billing.score, "max_score": billing.max_score, "detected": billing.detected,
                "evidence": billing.evidence, "explanation": billing.explanation,
            },
            "geographic_signal": {
                "score": geographic.score, "max_score": geographic.max_score, "detected": geographic.detected,
                "nearby_project_count": geographic.nearby_project_count,
                "attribute_sharing_count": geographic.attribute_sharing_count,
                "nearby_project_ids": geographic.nearby_project_ids, "explanation": geographic.explanation,
            },
        }

        raw_total = cost.score + similarity.score + contractor.score + billing.score + geographic.score
        risk_score = round(min(100.0, raw_total), 1)
        risk_level = classify_risk_level(risk_score)

        return ProjectRiskResult(
            project_id=project_id,
            risk_score=risk_score,
            risk_level=risk_level,
            components=components,
            recommendation=_recommendation(risk_level),
        )

    def score_all(self) -> list[ProjectRiskResult]:
        return [self.score_project(pid) for pid in self.projects["project_id"]]


def build_engine(dataset: Dataset) -> RiskEngine:
    return RiskEngine(dataset)
