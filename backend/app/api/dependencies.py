"""
Stage 6.4 dependency providers (Phase 2.1: shared in-process cache).

The expensive intelligence results (Dataset, Stage 4 risk results, Stage 5A
relationships, Stage 5A geographic engine/clusters/duplicate-like matches) are
no longer rebuilt on every request. Each is computed once per process and
shared across requests by backend/app/intelligence/cache.py (single-flight under
concurrency, invalidated by ingestion, handed out as copies). The intelligence
functions themselves are called exactly as before.

Everything user-specific stays request-scoped and database-backed: this module
only provides intelligence results and 404-checked ORM lookups; authentication,
RBAC, investigations and audit history live elsewhere and are never cached.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.db.models import Contractor, Project
from backend.app.intelligence.cache import (
    get_cached_dataset,
    get_cached_duplicate_like_matches,
    get_cached_geographic_clusters,
    get_cached_geospatial_engine,
    get_cached_relationships,
    get_cached_risk_results,
)

from intelligence.data_loader import Dataset
from intelligence.geographic_intelligence import GeospatialEngine
from intelligence.risk_engine import DISCLAIMER as RISK_DISCLAIMER, ProjectRiskResult

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
    The database-backed Dataset (Stage 6.3), loaded once per process and shared.

    Still obtained via Depends(get_db) (not a separate SessionLocal()), so this
    keeps respecting FastAPI's dependency_overrides — tests point get_db at a
    temporary database this way, and the cache keys its entries by that database.

    The request's session is closed as soon as the cache accessor returns (as it
    was before caching), so no pooled connection is held during the multi-second
    in-memory computation, which is what once exhausted QueuePool's slots.
    Treat the returned Dataset as read-only.
    """
    return get_cached_dataset(db)


def get_risk_results(db: Session = Depends(get_db)) -> dict[str, ProjectRiskResult]:
    """Stage 4, run unmodified, keyed by project_id. Computed once per process; callers get a copy."""
    return get_cached_risk_results(db)


def get_project_relationships(db: Session = Depends(get_db)) -> list[dict]:
    """Stage 5A analytical PROJECT_PROJECT relationships, run unmodified. Computed once; callers get a copy."""
    return get_cached_relationships(db)


def get_geospatial_engine(db: Session = Depends(get_db)) -> GeospatialEngine:
    """
    Stage 5A geographic engine, run unmodified. Built once; its nearby() and
    all_nearby_relationships() are computed once and returned as copies.
    """
    return get_cached_geospatial_engine(db)


def get_geographic_clusters(db: Session = Depends(get_db)) -> list[dict]:
    """Stage 5A connected-component clusters, run unmodified. Computed once; callers get a copy."""
    return get_cached_geographic_clusters(db)


def get_duplicate_like_matches(db: Session = Depends(get_db)) -> list[dict]:
    """Stage 5A potential-duplicate-like matches (dataset-wide; filtered per project in the route). Computed once; callers get a copy."""
    return get_cached_duplicate_like_matches(db)


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