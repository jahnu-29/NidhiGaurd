"""
Phase 2.1 — reproducible benchmark: repeated uncached computation vs the shared cache.

    python scripts/phase_2_1_benchmark.py [--repeats 3]

Uses a temporary SQLite database built from the seed CSVs (never backend/nidhiguard.db
and never a production database). All numbers are LOCAL/SANDBOX timings on whatever
machine runs this; they are NOT production measurements.

WITHOUT CACHE  = what dependencies.py did before Phase 2.1 on every request:
                 load dataset, then build_engine().score_all() / relationship analysis /
                 geographic engine + clusters + duplicate-like matches, from scratch.
WITH CACHE     = backend.app.intelligence.cache accessors (first call = miss, then hits).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.app.db.database import create_db_engine, init_db  # noqa: E402
from backend.app.ingestion import ingest_all  # noqa: E402
from backend.app.intelligence import cache as C  # noqa: E402
from backend.app.intelligence import load_dataset_from_db  # noqa: E402

from intelligence.geographic_intelligence import (  # noqa: E402
    DEFAULT_RADIUS_KM,
    build_geographic_clusters,
    build_geospatial_engine,
    find_duplicate_like_matches,
)
from intelligence.relationship_analysis import build_relationship_index, generate_project_relationships  # noqa: E402
from intelligence.risk_engine import build_engine  # noqa: E402


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - t


# ---- the ORIGINAL per-request work, as backend/app/api/dependencies.py did it ---- #


def original_risk(factory):
    with factory() as s:
        ds = load_dataset_from_db(s)
    return {r.project_id: r for r in build_engine(ds).score_all()}


def original_relationships(factory):
    with factory() as s:
        ds = load_dataset_from_db(s)
    return generate_project_relationships(build_relationship_index(ds.projects, ds.locations))


def original_geography_overview(factory):
    """GET /api/geography: engine + all_nearby (route) + clusters + duplicates, each rebuilding passes."""
    with factory() as s:
        ds = load_dataset_from_db(s)
    geo = build_geospatial_engine(ds, radius_km=DEFAULT_RADIUS_KM)
    clusters = build_geographic_clusters(geo)
    dups = find_duplicate_like_matches(geo.all_nearby_relationships())
    nearby = geo.all_nearby_relationships()
    return nearby, clusters, dups


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    n = ap.parse_args().repeats

    tmp = tempfile.mkdtemp(prefix="phase21_bench_")
    eng = create_db_engine(f"sqlite:///{Path(tmp) / 'bench.db'}")
    init_db(bind=eng)
    factory = sessionmaker(bind=eng)
    with factory() as s:
        ingest_all(s)

    print(f"LOCAL/SANDBOX timings (not production). repeats={n}\n")

    cases = [
        ("Risk results (e.g. /api/dashboard/summary, /api/risk-results, /api/projects/{id}/risk)",
         lambda: original_risk(factory), lambda: C.get_cached_risk_results(factory())),
        ("Relationships (/api/projects/{id}/relationships)",
         lambda: original_relationships(factory), lambda: C.get_cached_relationships(factory())),
        ("Geography overview (/api/geography)",
         lambda: original_geography_overview(factory),
         lambda: (C.get_cached_geospatial_engine(factory()).all_nearby_relationships(),
                  C.get_cached_geographic_clusters(factory()), C.get_cached_duplicate_like_matches(factory()))),
    ]

    for name, uncached_fn, cached_fn in cases:
        print(name)
        C.cache.invalidate_all("benchmark: cold start for this case")  # no sharing between cases
        before = [timed(uncached_fn)[1] for _ in range(n)]
        print("  WITHOUT cache, each call: " + ", ".join(f"{t:.2f}s" for t in before) + f"   (total {sum(before):.2f}s for {n} calls)")
        first = timed(cached_fn)[1]
        later = [timed(cached_fn)[1] for _ in range(n)]
        print(f"  WITH cache, first call (miss): {first:.2f}s")
        print("  WITH cache, later calls (hits): " + ", ".join(f"{t * 1000:.1f} ms" for t in later))
        print()

    eng.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
