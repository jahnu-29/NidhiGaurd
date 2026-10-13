"""
Stage 6.4 dependency providers.

FastAPI caches a dependency's result for the lifetime of one request (by
default), so chaining get_dataset -> get_risk_engine -> get_risk_results means
a route that needs more than one of these only pays for loading/scoring once
per request, with no extra caching infrastructure. Per-request rebuilding
(no cross-request cache) is the same tradeoff the Stage 6.3 adapter already
accepted — intentionally not "over-engineered" per the Stage 6.4 brief.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.db.models import Contractor, Project
from backend.app.intelligence import load_dataset_from_db

from intelligence.data_loader import Dataset
from intelligence.geographic_intelligence import (
    DEFAULT_RADIUS_KM,
    GeospatialEngine,
    build_geographic_clusters,
    build_geospatial_engine,
    find_duplicate_like_matches,
)
from intelligence.relationship_analysis import build_relationship_index, generate_project_relationships
from intelligence.risk_engine import DISCLAIMER as RISK_DISCLAIMER, ProjectRiskResult, build_engine

GEOGRAPHIC_DISCLAIMER = (
    "Geographic proximity is contextual information for investigators. "
    "Proximity alone is never treated as an anomaly."
)
RELATIONSHIP_DISCLAIMER = (
    "Relationship strength indicates how strongly two entities are connected "
    "according to available data. It does not represent fraud, collusion, or "
    "corruption probability."
)

__all__ = [
    "get_db",
    "get_dataset",
    "get_risk_results",
    "get_project_relationships",
    "get_geospatial_engine",
    "get_geographic_clusters",
    "get_duplicate_like_matches",
    "get_project_or_404",
    "get_contractor_or_404",
    "RISK_DISCLAIMER",
    "GEOGRAPHIC_DISCLAIMER",
    "RELATIONSHIP_DISCLAIMER",
]


def get_dataset(db: Session = Depends(get_db)) -> Dataset:
    """
    The database-backed Dataset (Stage 6.3), rebuilt once per request.

    Still obtained via Depends(get_db) (not a separate SessionLocal()), so
    this keeps respecting FastAPI's dependency_overrides — tests point
    get_db at a temporary database this way, and that must keep working.

    But the session is explicitly closed here, immediately after
    load_dataset_from_db() finishes reading rows into pandas DataFrames.
    Without this, the session — and its checked-out pool connection — stays
    open for the rest of the request (FastAPI's own db.close() in get_db's
    finally: only runs after the endpoint returns), even though nothing
    downstream (Stage 4 scoring, Stage 5A relationship/geographic analysis —
    several seconds of pure in-memory pandas/sklearn work) ever touches the
    database again. Holding a pooled connection for that whole computation,
    multiplied across several requests overlapping (exactly what a React
    page firing a few concurrent fetches does), was what exhausted
    QueuePool's 5 + 10 overflow slots.

    Session.close() is idempotent, so get_db's own later close() call is a
    harmless no-op — this doesn't change get_db's contract or lifecycle for
    any other dependency, only returns this one connection to the pool early.
    """
    try:
        return load_dataset_from_db(db)
    finally:
        db.close()


def get_risk_results(dataset: Dataset = Depends(get_dataset)) -> dict[str, ProjectRiskResult]:
    """Stage 4, run unmodified, keyed by project_id. Computed once per request."""
    engine = build_engine(dataset)
    return {r.project_id: r for r in engine.score_all()}


def get_project_relationships(dataset: Dataset = Depends(get_dataset)) -> list[dict]:
    """Stage 5A analytical PROJECT_PROJECT relationships, run unmodified."""
    rel_index = build_relationship_index(dataset.projects, dataset.locations)
    return generate_project_relationships(rel_index)


def get_geospatial_engine(dataset: Dataset = Depends(get_dataset)) -> GeospatialEngine:
    """Stage 5A geographic engine, run unmodified."""
    return build_geospatial_engine(dataset, radius_km=DEFAULT_RADIUS_KM)


def get_geographic_clusters(geo: GeospatialEngine = Depends(get_geospatial_engine)) -> list[dict]:
    """Stage 5A connected-component clusters, run unmodified."""
    return build_geographic_clusters(geo)


def get_duplicate_like_matches(geo: GeospatialEngine = Depends(get_geospatial_engine)) -> list[dict]:
    """Stage 5A potential-duplicate-like matches, run unmodified (dataset-wide, filtered per project in the route)."""
    return find_duplicate_like_matches(geo.all_nearby_relationships())


def get_project_or_404(project_id: str, db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' was not found.")
    return project


def get_contractor_or_404(contractor_id: str, db: Session = Depends(get_db)) -> Contractor:
    contractor = db.get(Contractor, contractor_id)
    if contractor is None:
        raise HTTPException(status_code=404, detail=f"Contractor '{contractor_id}' was not found.")
    return contractor