"""
Phase 2.1 tests — shared in-process intelligence cache.

Part 1 (fast, no database): the IntelligenceCache primitive — hit/miss,
single-flight under concurrency, invalidation, namespaces, failure handling.

Part 2 (real seed data, one temporary database, never backend/nidhiguard.db):
  * cached results are value-identical to the original uncached computation,
  * the expensive intelligence functions run once across many requests,
  * concurrent first requests trigger one computation,
  * ingestion invalidates the cache (and a failed ingestion does not),
  * a caller mutating what it received cannot corrupt later requests,
  * warm-up failing never raises.
"""

from __future__ import annotations

import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.orm import sessionmaker

from backend.app.db.database import create_db_engine, init_db
from backend.app.ingestion import IngestionError, ingest_all
from backend.app.intelligence import cache as cache_mod
from backend.app.intelligence import load_dataset_from_db
from backend.app.intelligence.cache import IntelligenceCache

from intelligence.geographic_intelligence import (
    DEFAULT_RADIUS_KM,
    build_geographic_clusters,
    build_geospatial_engine,
    find_duplicate_like_matches,
)
from intelligence.relationship_analysis import build_relationship_index, generate_project_relationships
from intelligence.risk_engine import build_engine


def canonical(obj) -> str:
    """Stable, byte-comparable rendering (handles numpy scalars, dataclasses via to_dict)."""

    def default(o):
        if hasattr(o, "to_dict"):
            return o.to_dict()
        if hasattr(o, "item"):
            return o.item()
        return repr(o)

    return json.dumps(obj, sort_keys=True, default=default)


# =========================================================================== #
# Part 1 — the cache primitive
# =========================================================================== #


class Counter:
    def __init__(self, delay: float = 0.0, value="v"):
        self.calls = 0
        self.delay = delay
        self.value = value
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            self.calls += 1
        time.sleep(self.delay)
        return self.value


def test_first_call_computes_and_second_call_reuses():
    c, compute = IntelligenceCache(), Counter()
    assert c.get_or_compute("db", "x", compute) == "v"
    assert c.get_or_compute("db", "x", compute) == "v"
    assert compute.calls == 1
    assert c.stats["x"] == {"hits": 1, "misses": 1}


def test_concurrent_first_requests_compute_exactly_once():
    c, compute = IntelligenceCache(), Counter(delay=0.3)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: c.get_or_compute("db", "x", compute), range(12)))
    assert results == ["v"] * 12
    assert compute.calls == 1


def test_different_entries_do_not_block_each_other():
    c = IntelligenceCache()
    slow, fast = Counter(delay=0.6, value="slow"), Counter(value="fast")
    t = threading.Thread(target=lambda: c.get_or_compute("db", "slow", slow))
    t.start()
    time.sleep(0.1)
    started = time.perf_counter()
    assert c.get_or_compute("db", "fast", fast) == "fast"
    assert time.perf_counter() - started < 0.4  # not queued behind the slow entry
    t.join()


def test_invalidation_forces_recompute():
    c, compute = IntelligenceCache(), Counter()
    c.get_or_compute("db", "x", compute)
    c.invalidate_all("test")
    assert not c.is_populated("db", "x")
    c.get_or_compute("db", "x", compute)
    assert compute.calls == 2


def test_value_computed_across_an_invalidation_is_not_stored():
    c = IntelligenceCache()
    started, release = threading.Event(), threading.Event()

    def slow_compute():
        started.set()
        release.wait(5)
        return "computed-from-old-data"

    t = threading.Thread(target=lambda: c.get_or_compute("db", "x", slow_compute))
    t.start()
    assert started.wait(5)
    c.invalidate_all("data changed mid-computation")
    release.set()
    t.join()
    assert not c.is_populated("db", "x")  # stale value was returned to its caller only
    fresh = Counter(value="fresh")
    assert c.get_or_compute("db", "x", fresh) == "fresh"


def test_namespaces_are_isolated():
    c = IntelligenceCache()
    a, b = Counter(value="A"), Counter(value="B")
    assert c.get_or_compute("db-a", "x", a) == "A"
    assert c.get_or_compute("db-b", "x", b) == "B"
    assert c.get_or_compute("db-a", "x", a) == "A"
    assert (a.calls, b.calls) == (1, 1)


def test_failed_computation_is_not_cached_and_is_retried():
    c = IntelligenceCache()
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("boom")
        return "ok"

    with pytest.raises(RuntimeError):
        c.get_or_compute("db", "x", flaky)
    assert c.get_or_compute("db", "x", flaky) == "ok"
    assert len(attempts) == 2


# =========================================================================== #
# Part 2 — real seed data
# =========================================================================== #
#
# The expensive real computation runs once per module (`warmed`); every other
# test reads the cache. Synchronization through the real accessors is tested with
# fast stand-ins for the engines so it does not need the multi-second pass again.


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    eng = create_db_engine(f"sqlite:///{tmp_path_factory.mktemp('cache') / 'cache_test.db'}")
    init_db(bind=eng)
    with sessionmaker(bind=eng)() as s:
        ingest_all(s)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture(scope="module")
def uncached(factory):
    """The ORIGINAL per-request computation, exactly as dependencies.py did it before Phase 2.1."""
    with factory() as s:
        dataset = load_dataset_from_db(s)
    risk = {r.project_id: r for r in build_engine(dataset).score_all()}
    rel_index = build_relationship_index(dataset.projects, dataset.locations)
    relationships = generate_project_relationships(rel_index)
    geo = build_geospatial_engine(dataset, radius_km=DEFAULT_RADIUS_KM)
    return {
        "dataset": dataset,
        "risk": risk,
        "relationships": relationships,
        "all_nearby": geo.all_nearby_relationships(),
        "clusters": build_geographic_clusters(geo),
        "duplicates": find_duplicate_like_matches(geo.all_nearby_relationships()),
        "nearby": {pid: geo.nearby(pid) for pid in dataset.projects["project_id"]},
    }


@pytest.fixture(scope="module")
def warmed(factory):
    """Cold cache -> one page-load worth of mixed requests, repeated, counting real computations."""
    cache_mod.cache.invalidate_all("module setup")
    cache_mod.cache.clear_stats()
    calls = {"load_dataset": 0, "risk_engine": 0, "relationships": 0, "clusters": 0, "duplicates": 0}
    timings: dict[str, float] = {}

    mp = pytest.MonkeyPatch()
    for key, attr in (
        ("load_dataset", "load_dataset_from_db"),
        ("risk_engine", "build_engine"),
        ("relationships", "generate_project_relationships"),
        ("clusters", "build_geographic_clusters"),
        ("duplicates", "find_duplicate_like_matches"),
    ):
        original = getattr(cache_mod, attr)

        def wrapper(*a, _o=original, _k=key, **k):
            calls[_k] += 1
            return _o(*a, **k)

        mp.setattr(cache_mod, attr, wrapper)

    def one_page_load():
        started = time.perf_counter()
        with factory() as s:
            cache_mod.get_cached_risk_results(s)
        with factory() as s:
            cache_mod.get_cached_relationships(s)
        with factory() as s:
            geo = cache_mod.get_cached_geospatial_engine(s)
        with factory() as s:
            cache_mod.get_cached_geographic_clusters(s)
        with factory() as s:
            cache_mod.get_cached_duplicate_like_matches(s)
        geo.nearby("P-1001")
        return time.perf_counter() - started

    timings["first_page_load_s"] = one_page_load()
    timings["second_page_load_s"] = one_page_load()
    timings["third_page_load_s"] = one_page_load()
    mp.undo()
    yield {"calls": calls, "timings": timings}
    cache_mod.cache.invalidate_all("module teardown")


def test_first_requests_compute_once_and_repeats_reuse(warmed):
    # three page loads (15 requests) -> each expensive computation ran exactly once
    assert warmed["calls"] == {"load_dataset": 1, "risk_engine": 1, "relationships": 1, "clusters": 1, "duplicates": 1}
    assert cache_mod.cache.stats["risk_results"] == {"hits": 2, "misses": 1}
    assert warmed["timings"]["second_page_load_s"] < warmed["timings"]["first_page_load_s"] / 10
    print("\n[local/sandbox timings] " + ", ".join(f"{k}={v:.3f}" for k, v in warmed["timings"].items()))


def test_cached_results_are_identical_to_uncached(factory, uncached, warmed):
    """Cached == uncached for every cached computation, compared byte-for-byte as canonical JSON."""
    with factory() as s:
        risk = cache_mod.get_cached_risk_results(s)
        relationships = cache_mod.get_cached_relationships(s)
        geo = cache_mod.get_cached_geospatial_engine(s)
        clusters = cache_mod.get_cached_geographic_clusters(s)
        duplicates = cache_mod.get_cached_duplicate_like_matches(s)
        ds = cache_mod.get_cached_dataset(s)

    assert risk == uncached["risk"]
    assert canonical(risk) == canonical(uncached["risk"])
    assert canonical(relationships) == canonical(uncached["relationships"])
    assert canonical(geo.all_nearby_relationships()) == canonical(uncached["all_nearby"])
    assert canonical(clusters) == canonical(uncached["clusters"])
    assert canonical(duplicates) == canonical(uncached["duplicates"])
    for pid, expected in uncached["nearby"].items():
        assert canonical(geo.nearby(pid)) == canonical(expected), pid
    for field in ("projects", "contractors", "bills", "payments", "locations", "historical_projects", "project_contractors"):
        assert getattr(ds, field).equals(getattr(uncached["dataset"], field)), field


def test_mutating_a_returned_result_cannot_corrupt_later_requests(factory, warmed):
    with factory() as s:
        first = cache_mod.get_cached_risk_results(s)
    pid = next(iter(first))
    pristine = canonical(first)
    first[pid].risk_score = -1.0
    first[pid].components["cost_anomaly"]["score"] = -999
    first.clear()
    with factory() as s:
        assert canonical(cache_mod.get_cached_risk_results(s)) == pristine

    with factory() as s:
        rels = cache_mod.get_cached_relationships(s)
    expected = canonical(rels)
    rels[0]["relationship_strength"] = -1
    rels.clear()
    with factory() as s:
        assert canonical(cache_mod.get_cached_relationships(s)) == expected

    with factory() as s:
        geo = cache_mod.get_cached_geospatial_engine(s)
        clusters = cache_mod.get_cached_geographic_clusters(s)
        duplicates = cache_mod.get_cached_duplicate_like_matches(s)
    nearby = geo.nearby("P-1001")
    nearby_expected = canonical(nearby)
    flat_expected = canonical(geo.all_nearby_relationships())
    clusters_expected, dups_expected = canonical(clusters), canonical(duplicates)
    nearby.clear()
    geo.all_nearby_relationships().clear()
    clusters.clear()
    duplicates.clear()
    assert canonical(geo.nearby("P-1001")) == nearby_expected
    assert canonical(geo.all_nearby_relationships()) == flat_expected
    with factory() as s:
        assert canonical(cache_mod.get_cached_geographic_clusters(s)) == clusters_expected
        assert canonical(cache_mod.get_cached_duplicate_like_matches(s)) == dups_expected


def test_concurrent_first_requests_through_the_real_accessors_compute_once(factory, uncached, monkeypatch):
    """Empty cache + several simultaneous requests -> one computation each (fast stand-in engines)."""
    cache_mod.cache.invalidate_all("concurrency test")
    calls = {"load": 0, "risk": 0, "relationships": 0, "index": 0}
    lock = threading.Lock()

    def tick(name):
        with lock:
            calls[name] += 1
        time.sleep(0.3)

    class FakeEngine:
        def score_all(self):
            return []

    def fake_load(_session):
        tick("load")
        return uncached["dataset"]

    def fake_engine(_dataset):
        tick("risk")
        return FakeEngine()

    def fake_index(*_a):
        tick("index")
        return object()

    def fake_relationships(_index):
        tick("relationships")
        return [{"source": "A", "target": "B", "relationship_strength": 1.0}]

    monkeypatch.setattr(cache_mod, "load_dataset_from_db", fake_load)
    monkeypatch.setattr(cache_mod, "build_engine", fake_engine)
    monkeypatch.setattr(cache_mod, "build_relationship_index", fake_index)
    monkeypatch.setattr(cache_mod, "generate_project_relationships", fake_relationships)

    def request(kind):
        with factory() as s:
            return (cache_mod.get_cached_risk_results if kind == "risk" else cache_mod.get_cached_relationships)(s)

    kinds = ["risk"] * 5 + ["rel"] * 5
    with ThreadPoolExecutor(max_workers=len(kinds)) as pool:
        results = list(pool.map(request, kinds))

    assert calls == {"load": 1, "risk": 1, "index": 1, "relationships": 1}
    assert all(r == {} for k, r in zip(kinds, results) if k == "risk")
    assert all(r == results[kinds.index("rel")] for k, r in zip(kinds, results) if k == "rel")
    cache_mod.cache.invalidate_all("concurrency test cleanup")


# ---- invalidation by ingestion (cheap: sentinel entries, separate throw-away DBs) ---- #


@pytest.fixture
def throwaway_db(tmp_path):
    eng = create_db_engine(f"sqlite:///{tmp_path / 'ingest.db'}")
    init_db(bind=eng)
    fac = sessionmaker(bind=eng)
    with fac() as s:
        ingest_all(s)
    yield fac
    eng.dispose()


def test_ingestion_invalidates_the_cache(throwaway_db):
    ns = cache_mod.namespace_for(throwaway_db())
    for name in (cache_mod.DATASET, cache_mod.RISK_RESULTS):
        cache_mod.cache.get_or_compute(ns, name, lambda: "sentinel")
        assert cache_mod.cache.is_populated(ns, name)

    with throwaway_db() as s:
        ingest_all(s)  # idempotent re-ingest; still a committed data-change event

    assert not cache_mod.cache.is_populated(ns, cache_mod.DATASET)
    assert not cache_mod.cache.is_populated(ns, cache_mod.RISK_RESULTS)


def test_failed_ingestion_leaves_the_cache_untouched(throwaway_db, tmp_path):
    ns = cache_mod.namespace_for(throwaway_db())
    cache_mod.cache.get_or_compute(ns, cache_mod.RISK_RESULTS, lambda: "sentinel")
    empty_dir = tmp_path / "no_csvs"
    empty_dir.mkdir()
    with throwaway_db() as s, pytest.raises(Exception):
        ingest_all(s, data_dir=empty_dir)  # nothing is committed, so nothing to invalidate
    assert cache_mod.cache.is_populated(ns, cache_mod.RISK_RESULTS)
    cache_mod.cache.invalidate_all("cleanup")


# ---- warm-up ---- #


def test_warm_up_on_an_empty_database_never_raises(tmp_path):
    eng = create_db_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    init_db(bind=eng)  # tables exist, no data ingested
    with sessionmaker(bind=eng)() as s:
        cache_mod.warm(s)
    eng.dispose()


def test_warm_up_swallows_unexpected_errors(throwaway_db, monkeypatch):
    def boom(_session):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(cache_mod, "load_dataset_from_db", boom)
    cache_mod.cache.invalidate_all("warm failure test")
    with throwaway_db() as s:
        cache_mod.warm(s)  # logged, not raised
    cache_mod.cache.invalidate_all("cleanup")
