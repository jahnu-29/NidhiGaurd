"""
Phase 2.1 — shared in-process cache for the expensive intelligence results.

Why this exists
---------------
Before this module, backend/app/api/dependencies.py rebuilt the Dataset and
re-ran the Stage 4 risk engine, the Stage 5A relationship analysis and the
Stage 5A geographic engine on EVERY request (FastAPI only de-duplicates inside
one request). A React page firing several requests therefore paid for the same
multi-second computation several times, concurrently.

What is cached (per database, see "Namespaces")
-----------------------------------------------
  dataset             Dataset read from the database
  risk_results        {project_id: ProjectRiskResult}        (Stage 4, unmodified)
  relationship_index  Stage 5A RelationshipIndex (TF-IDF matrix)   [internal]
  relationships       PROJECT_PROJECT relationships              (Stage 5A, unmodified)
  geography           geospatial engine + clusters + duplicate-like matches (Stage 5A, unmodified)

The intelligence code itself (intelligence/*) is called exactly as before; only
how often it is called changes. NOT cached here (stay request-scoped and
database-backed): authentication, authorization, investigations, investigation
history, audit rows, and the plain project/contractor reads.

Synchronization (single-flight)
-------------------------------
Each cache entry has its own lock. If N requests arrive while an entry is empty,
one computes it and the others wait on that lock, then reuse the result. Locks
are never held while doing unrelated work: the short `_state` lock only guards
dictionary bookkeeping, and the expensive computation runs under the entry's own
lock only. An entry may depend on another entry (risk -> dataset), always in the
same direction, so locks cannot deadlock.

Invalidation
------------
`invalidate_all()` bumps a generation counter and empties the cache. A value
whose computation started before an invalidation is returned to the caller that
computed it but is NOT stored, so stale data can never be cached after
invalidation. It is called from backend.app.ingestion.csv_ingestion.ingest_all()
right after a successful commit — the only code path that changes the
project/bill/payment/location/contractor tables. Note ingestion is also a
separate CLI process (`python -m backend.app.ingestion`): that process cannot
reach the cache inside a running API process, so after ingesting into a live
database the API process must be restarted (the cache is rebuilt on start).

Mutation safety
---------------
Values handed to callers are deep copies (plain data) or, for the geographic
engine, an engine whose query methods return copies. A request that edits what it
received cannot change what the next request receives. The shared Dataset is
only ever passed to the (read-only) intelligence code.

Namespaces
----------
Entries are keyed by the database they were computed from (credential-free URL),
so test suites or tools that point the app at different databases never see each
other's results.
"""

from __future__ import annotations

import copy
import logging
import os
import threading
import time
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import Project
from backend.app.intelligence import load_dataset_from_db

from intelligence.data_loader import Dataset
from intelligence.geographic_intelligence import (
    DEFAULT_RADIUS_KM,
    GeospatialEngine,
    build_geographic_clusters,
    build_geospatial_engine,
    find_duplicate_like_matches,
)
from intelligence.relationship_analysis import (
    RelationshipIndex,
    build_relationship_index,
    generate_project_relationships,
)
from intelligence.risk_engine import ProjectRiskResult, build_engine

logger = logging.getLogger("nidhiguard.intelligence_cache")
if not logger.handlers and not logging.getLogger().handlers:
    # uvicorn only configures its own loggers; without this the INFO lines below
    # would be invisible in the server log.
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

DATASET = "dataset"
RISK_RESULTS = "risk_results"
RELATIONSHIP_INDEX = "relationship_index"
RELATIONSHIPS = "relationships"
GEOGRAPHY = "geography"


class IntelligenceCache:
    """Thread-safe, single-flight, invalidatable in-process cache."""

    def __init__(self) -> None:
        self._state = threading.Lock()  # guards the three dicts below, held only briefly
        self._values: dict[tuple[str, str], Any] = {}
        self._entry_locks: dict[tuple[str, str], threading.Lock] = {}
        self._generation = 0
        self.stats: dict[str, dict[str, int]] = {}  # name -> {"hits": n, "misses": n}

    # ---- core ---------------------------------------------------------- #

    def get_or_compute(self, namespace: str, name: str, compute: Callable[[], Any]) -> Any:
        key = (namespace, name)
        with self._state:
            if key in self._values:
                self._count(name, "hits")
                value = self._values[key]
                hit = True
            else:
                hit = False
                entry_lock = self._entry_locks.setdefault(key, threading.Lock())
        if hit:
            logger.info("intelligence_cache computation=%s result=HIT", name)
            return value

        with entry_lock:
            with self._state:
                if key in self._values:  # another request computed it while we waited
                    self._count(name, "hits")
                    value = self._values[key]
                    waited = True
                else:
                    waited = False
                    generation = self._generation
            if waited:
                logger.info("intelligence_cache computation=%s result=HIT (waited for in-flight computation)", name)
                return value

            started = time.perf_counter()
            value = compute()  # expensive; no shared lock is held here
            elapsed = time.perf_counter() - started

            with self._state:
                self._count(name, "misses")
                stored = generation == self._generation
                if stored:
                    self._values[key] = value
            logger.info(
                "intelligence_cache computation=%s result=MISS elapsed=%.3fs%s",
                name, elapsed, "" if stored else " (invalidated during computation; not stored)",
            )
            return value

    def invalidate_all(self, reason: str = "unspecified") -> None:
        with self._state:
            self._generation += 1
            self._values.clear()
        logger.info("intelligence_cache invalidated reason=%s", reason)

    def clear_stats(self) -> None:
        with self._state:
            self.stats.clear()

    def is_populated(self, namespace: str, name: str) -> bool:
        with self._state:
            return (namespace, name) in self._values

    def _count(self, name: str, kind: str) -> None:
        self.stats.setdefault(name, {"hits": 0, "misses": 0})[kind] += 1


cache = IntelligenceCache()


# --------------------------------------------------------------------------- #
# Geographic engine whose query methods are computed once and return copies
# --------------------------------------------------------------------------- #


class MemoizedGeospatialEngine(GeospatialEngine):
    """
    The unmodified GeospatialEngine, with `nearby()` and `all_nearby_relationships()`
    computed once per engine and returned as copies. build_geographic_clusters(),
    find_duplicate_like_matches() and the routes all call these repeatedly, each
    call previously redoing the full pairwise pass; results are identical.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._memo_lock = threading.Lock()
        self._nearby_memo: dict[str, list[dict[str, Any]]] = {}
        self._all_nearby_memo: list[dict[str, Any]] | None = None

    def nearby(self, project_id: str) -> list[dict[str, Any]]:
        with self._memo_lock:
            cached = self._nearby_memo.get(project_id)
        if cached is None:
            cached = super().nearby(project_id)  # KeyError for unknown ids, exactly as before
            with self._memo_lock:
                self._nearby_memo.setdefault(project_id, cached)
        return copy.deepcopy(cached)

    def all_nearby_relationships(self) -> list[dict[str, Any]]:
        with self._memo_lock:
            cached = self._all_nearby_memo
        if cached is None:
            cached = super().all_nearby_relationships()  # calls self.nearby -> memoized
            with self._memo_lock:
                if self._all_nearby_memo is None:
                    self._all_nearby_memo = cached
        return copy.deepcopy(cached)


class GeographyBundle:
    """Engine + the two dataset-wide derived lists, computed together once."""

    def __init__(self, engine: MemoizedGeospatialEngine, clusters: list[dict], duplicates: list[dict]) -> None:
        self.engine = engine
        self._clusters = clusters
        self._duplicates = duplicates

    @property
    def clusters(self) -> list[dict]:
        return copy.deepcopy(self._clusters)

    @property
    def duplicates(self) -> list[dict]:
        return copy.deepcopy(self._duplicates)


# --------------------------------------------------------------------------- #
# Public accessors (used by backend/app/api/dependencies.py)
# --------------------------------------------------------------------------- #


def namespace_for(session: Session) -> str:
    """Credential-free identity of the database a session reads from."""
    return session.get_bind().url.render_as_string(hide_password=True)


def _dataset(db: Session, ns: str) -> Dataset:
    def compute() -> Dataset:
        try:
            return load_dataset_from_db(db)
        finally:
            db.close()  # return the pooled connection before any in-memory work

    return cache.get_or_compute(ns, DATASET, compute)


def _relationship_index(db: Session, ns: str) -> RelationshipIndex:
    def compute() -> RelationshipIndex:
        dataset = _dataset(db, ns)
        return build_relationship_index(dataset.projects, dataset.locations)

    return cache.get_or_compute(ns, RELATIONSHIP_INDEX, compute)


def get_cached_dataset(db: Session) -> Dataset:
    """Shared Dataset. Treat as read-only (the intelligence code only reads it)."""
    ns = namespace_for(db)
    try:
        return _dataset(db, ns)
    finally:
        db.close()


def get_cached_risk_results(db: Session) -> dict[str, ProjectRiskResult]:
    ns = namespace_for(db)

    def compute() -> dict[str, ProjectRiskResult]:
        dataset = _dataset(db, ns)
        engine = build_engine(dataset)
        return {r.project_id: r for r in engine.score_all()}

    try:
        return copy.deepcopy(cache.get_or_compute(ns, RISK_RESULTS, compute))
    finally:
        db.close()


def get_cached_relationships(db: Session) -> list[dict]:
    ns = namespace_for(db)

    def compute() -> list[dict]:
        return generate_project_relationships(_relationship_index(db, ns))

    try:
        return copy.deepcopy(cache.get_or_compute(ns, RELATIONSHIPS, compute))
    finally:
        db.close()


def _geography(db: Session, ns: str) -> GeographyBundle:
    def compute() -> GeographyBundle:
        dataset = _dataset(db, ns)
        index = _relationship_index(db, ns)
        engine = MemoizedGeospatialEngine(dataset, radius_km=DEFAULT_RADIUS_KM, relationship_index=index)
        clusters = build_geographic_clusters(engine)
        duplicates = find_duplicate_like_matches(engine.all_nearby_relationships())
        return GeographyBundle(engine, clusters, duplicates)

    return cache.get_or_compute(ns, GEOGRAPHY, compute)


def get_cached_geospatial_engine(db: Session) -> GeospatialEngine:
    ns = namespace_for(db)
    try:
        return _geography(db, ns).engine
    finally:
        db.close()


def get_cached_geographic_clusters(db: Session) -> list[dict]:
    ns = namespace_for(db)
    try:
        return _geography(db, ns).clusters
    finally:
        db.close()


def get_cached_duplicate_like_matches(db: Session) -> list[dict]:
    ns = namespace_for(db)
    try:
        return _geography(db, ns).duplicates
    finally:
        db.close()


def warm(db: Session) -> None:
    """Populate every entry. Safe to call repeatedly; never raises into the caller."""
    started = time.perf_counter()
    try:
        if not db.scalar(select(func.count()).select_from(Project)):
            logger.info("intelligence_cache warm-up skipped: no projects in the database")
            return
        ns = namespace_for(db)
        _dataset(db, ns)
        get_cached_risk_results(db)
        get_cached_relationships(db)
        _geography(db, ns)
        logger.info("intelligence_cache warm-up complete elapsed=%.3fs", time.perf_counter() - started)
    except Exception:  # optional optimisation: never affect API availability
        logger.exception("intelligence_cache warm-up failed; requests will compute on demand")
    finally:
        db.close()


WARM_ENV_VAR = "NIDHIGUARD_WARM_INTELLIGENCE_CACHE"


def start_background_warmup() -> threading.Thread | None:
    """
    Warm the cache on a daemon thread after the database is initialised, so the
    API starts (and answers /health) immediately; requests that arrive while the
    warm-up is running simply wait for that same single computation.
    Set NIDHIGUARD_WARM_INTELLIGENCE_CACHE=0 to disable.
    """
    if os.environ.get(WARM_ENV_VAR, "1").strip().lower() in {"0", "false", "no", "off"}:
        return None

    def run() -> None:
        from backend.app.db.database import SessionLocal  # late: avoid import-time coupling

        try:
            with SessionLocal() as session:
                warm(session)
        except Exception:
            logger.exception("intelligence_cache warm-up thread failed")

    thread = threading.Thread(target=run, name="intelligence-cache-warmup", daemon=True)
    thread.start()
    return thread
