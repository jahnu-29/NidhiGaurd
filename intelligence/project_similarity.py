"""
NidhiGuard Intelligence — Project Similarity Detector (max score: 25)

Finds other CURRENT projects that look like a potential duplicate or
overlapping-scope project to the one being scored, by combining:

  1. Text similarity of `project_description` (TF-IDF + cosine similarity —
     deterministic, no downloaded model).
  2. Structured similarity: same work_type, same district, overlapping
     sanction/start-date windows, comparable sanctioned_amount, and
     geographic proximity (haversine distance via locations.csv).

No shared ID is used to find these matches — the whole point is that the
engine discovers the relationship the way a human investigator would.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import radians, sin, cos, asin, sqrt

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

MAX_SCORE = 25
DATE_WINDOW_DAYS = 120           # sanction/start windows considered "overlapping"
AMOUNT_TOLERANCE = 0.25          # sanctioned_amount within +/-25% counts as comparable
PROXIMITY_KM = 3.0               # locations within this distance count as "nearby"
COMBINED_MATCH_THRESHOLD = 0.45  # minimum combined score to report a match at all
DETECTION_THRESHOLD = 0.6        # minimum combined score to call `detected = True`

TEXT_WEIGHT = 0.55
STRUCTURED_WEIGHT = 0.45
STRUCTURED_SIGNAL_COUNT = 4      # work_type, district, date window, amount/geo


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(a))


@dataclass
class SimilarityMatch:
    project_id: str
    combined_score: float
    text_similarity: float
    reasons: list[str] = field(default_factory=list)


@dataclass
class ProjectSimilarityResult:
    score: float
    max_score: int = MAX_SCORE
    detected: bool = False
    matches: list[SimilarityMatch] = field(default_factory=list)
    explanation: str = ""


class SimilarityIndex:
    """Precomputes the TF-IDF matrix once for all current projects so the
    per-project detector call doesn't refit a vectorizer 200 times."""

    def __init__(self, projects: pd.DataFrame, locations: pd.DataFrame):
        self.projects = projects.reset_index(drop=True)
        self.locations_by_project = locations.set_index("project_id")

        descriptions = self.projects["project_description"].fillna("").tolist()
        self.vectorizer = TfidfVectorizer(stop_words="english", min_df=1)
        self.tfidf_matrix = self.vectorizer.fit_transform(descriptions)
        self.text_sim_matrix = cosine_similarity(self.tfidf_matrix)

        self.id_to_index = {
            pid: i for i, pid in enumerate(self.projects["project_id"])
        }

    def score(self, project_id: str) -> ProjectSimilarityResult:
        idx = self.id_to_index[project_id]
        row = self.projects.iloc[idx]
        loc = self.locations_by_project.loc[project_id] if project_id in self.locations_by_project.index else None

        text_sims = self.text_sim_matrix[idx]

        matches: list[SimilarityMatch] = []
        for j, other_id in enumerate(self.projects["project_id"]):
            if other_id == project_id:
                continue
            text_sim = float(text_sims[j])
            other = self.projects.iloc[j]

            reasons = []
            structured_hits = 0

            if other["work_type"] == row["work_type"]:
                structured_hits += 1
                reasons.append("same work type")

            if other["district_id"] == row["district_id"]:
                structured_hits += 1
                reasons.append("same district")

            date_overlap = False
            if pd.notna(row["sanction_date"]) and pd.notna(other["sanction_date"]):
                if abs((row["sanction_date"] - other["sanction_date"]).days) <= DATE_WINDOW_DAYS:
                    date_overlap = True
            if date_overlap:
                structured_hits += 1
                reasons.append("overlapping sanction-date window")

            amount_close = False
            if pd.notna(row["sanctioned_amount"]) and pd.notna(other["sanctioned_amount"]) and other["sanctioned_amount"] > 0:
                ratio = row["sanctioned_amount"] / other["sanctioned_amount"]
                if (1 - AMOUNT_TOLERANCE) <= ratio <= (1 + AMOUNT_TOLERANCE):
                    amount_close = True
            if amount_close:
                structured_hits += 1
                reasons.append("comparable sanctioned amount")

            nearby = False
            if loc is not None and other_id in self.locations_by_project.index:
                other_loc = self.locations_by_project.loc[other_id]
                dist = _haversine_km(loc["latitude"], loc["longitude"], other_loc["latitude"], other_loc["longitude"])
                if dist <= PROXIMITY_KM:
                    nearby = True
                    reasons.append(f"location ~{dist:.1f} km away")

            # Structured fraction combines the 4 categorical hits plus a
            # geographic boost, capped at 1.0.
            structured_fraction = min(1.0, structured_hits / STRUCTURED_SIGNAL_COUNT + (0.15 if nearby else 0))

            combined = TEXT_WEIGHT * text_sim + STRUCTURED_WEIGHT * structured_fraction

            if combined >= COMBINED_MATCH_THRESHOLD and (text_sim > 0.15 or structured_hits >= 2):
                matches.append(SimilarityMatch(
                    project_id=other_id,
                    combined_score=round(combined, 3),
                    text_similarity=round(text_sim, 3),
                    reasons=reasons,
                ))

        matches.sort(key=lambda m: m.combined_score, reverse=True)
        top_matches = matches[:5]

        if not top_matches:
            return ProjectSimilarityResult(
                score=0.0,
                detected=False,
                matches=[],
                explanation="No other current project shows meaningful description, timing, or location overlap with this project.",
            )

        best = top_matches[0]
        score = round(min(1.0, best.combined_score) * MAX_SCORE, 1)
        detected = best.combined_score >= DETECTION_THRESHOLD

        reason_str = ", ".join(best.reasons) if best.reasons else "description text overlap"
        explanation = (
            f"Potentially similar project {best.project_id} identified "
            f"(description similarity {best.text_similarity:.0%}; {reason_str})."
        )
        if len(top_matches) > 1:
            explanation += f" {len(top_matches) - 1} additional potentially similar project(s) also found."

        return ProjectSimilarityResult(
            score=score,
            detected=detected,
            matches=top_matches,
            explanation=explanation,
        )


def build_similarity_index(projects: pd.DataFrame, locations: pd.DataFrame) -> SimilarityIndex:
    return SimilarityIndex(projects, locations)
