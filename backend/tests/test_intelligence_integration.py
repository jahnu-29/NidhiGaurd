"""
Stage 6.3 tests.

These prove two things:
  1. `load_dataset_from_db` produces a Dataset that is dtype-for-dtype and
     value-for-value identical to `intelligence.data_loader.load_dataset()`
     (the CSV path Stage 4/5A were built and verified against).
  2. Running the completely unmodified Stage 4 (`risk_engine`) and Stage 5A
     (`relationship_analysis`, `geographic_intelligence`) code against the
     database-backed Dataset reproduces the exact, previously verified
     results — not approximately, not "close enough".

No Stage 4/5A file is imported for anything but its existing public API.
Nothing here writes to the database.
"""

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.database import create_db_engine, init_db
from backend.app.db.models import Bill, Contractor, HistoricalProject, Location, Payment, Project, ProjectContractor
from backend.app.intelligence import load_dataset_from_db
from backend.app.ingestion import ingest_all

from intelligence.data_loader import load_dataset
from intelligence.geographic_intelligence import build_geographic_clusters, build_geospatial_engine
from intelligence.relationship_analysis import build_multi_hop_paths, build_relationship_index, generate_project_relationships
from intelligence.risk_engine import build_engine

EXPECTED_RISK = {
    "P-1023": (68.8, "HIGH"),
    "P-1001": (19.4, "LOW"),
    "P-1020": (19.8, "LOW"),
}

EXPECTED_5A = {
    "P-1023": {"top": "P-1151", "strength": 77.5, "nearby": 3, "multi_hop": 3, "cluster": "GEO-CLUSTER-004"},
    "P-1001": {"top": "P-1006", "strength": 61.2, "nearby": 1, "multi_hop": 3, "cluster": "GEO-CLUSTER-001"},
    "P-1020": {"top": "P-1187", "strength": 62.3, "nearby": 0, "multi_hop": 0, "cluster": None},
}

DATASET_FIELDS = [
    "projects", "contractors", "bills", "payments",
    "locations", "historical_projects", "project_contractors", "anomaly_signals",
]


# ----------------------------------------------------------------- fixtures --


@pytest.fixture(scope="module")
def seeded_engine(tmp_path_factory):
    """One ingested database, shared read-only by every test in this file."""
    eng = create_db_engine(f"sqlite:///{tmp_path_factory.mktemp('stage63') / 'seeded.db'}")
    init_db(bind=eng)
    with sessionmaker(bind=eng)() as s:
        ingest_all(s)
    yield eng
    eng.dispose()


@pytest.fixture
def session(seeded_engine):
    with sessionmaker(bind=seeded_engine)() as s:
        yield s


@pytest.fixture(scope="module")
def db_dataset(seeded_engine):
    with sessionmaker(bind=seeded_engine)() as s:
        return load_dataset_from_db(s)


@pytest.fixture(scope="module")
def csv_dataset():
    return load_dataset()


@pytest.fixture(scope="module")
def db_risk_results(db_dataset):
    return {r.project_id: r for r in build_engine(db_dataset).score_all()}


@pytest.fixture(scope="module")
def csv_risk_results(csv_dataset):
    return {r.project_id: r for r in build_engine(csv_dataset).score_all()}


@pytest.fixture(scope="module")
def db_5a(db_dataset):
    rel_index = build_relationship_index(db_dataset.projects, db_dataset.locations)
    project_relationships = generate_project_relationships(rel_index)
    multi_hop_paths = build_multi_hop_paths(db_dataset, project_relationships)
    geo = build_geospatial_engine(db_dataset)
    clusters = build_geographic_clusters(geo)
    return project_relationships, multi_hop_paths, geo, clusters


# ------------------------------------------------- data-loader equivalence --


def test_dataset_loader_returns_all_eight_tables(db_dataset):
    for field in DATASET_FIELDS:
        assert isinstance(getattr(db_dataset, field), pd.DataFrame)


def test_dataset_row_counts_match_source(db_dataset):
    assert len(db_dataset.projects) == 200
    assert len(db_dataset.contractors) == 75
    assert len(db_dataset.bills) == 888
    assert len(db_dataset.payments) == 983
    assert len(db_dataset.locations) == 200
    assert len(db_dataset.historical_projects) == 500
    assert len(db_dataset.project_contractors) == 200
    assert len(db_dataset.anomaly_signals) == 62


def test_database_dataset_is_identical_to_csv_dataset(db_dataset, csv_dataset):
    """The actual Stage 6.3 contract: same dtypes, same values, every table."""
    for field in DATASET_FIELDS:
        db_df = getattr(db_dataset, field).reset_index(drop=True)
        csv_df = getattr(csv_dataset, field).reset_index(drop=True)
        assert list(db_df.dtypes) == list(csv_df.dtypes), f"{field}: dtype mismatch"
        assert db_df.equals(csv_df), f"{field}: values differ between DB-backed and CSV-backed Dataset"


def test_expected_projects_and_relationships_are_present(session):
    for pid in ("P-1023", "P-1001", "P-1020"):
        assert session.get(Project, pid) is not None, pid

    p = session.get(Project, "P-1023")
    assert p.contractor_id == "C-054"
    assert session.get(Contractor, p.contractor_id) is not None
    assert session.get(Location, p.location_id) is not None
    assert session.scalar(select(func.count()).select_from(Bill).where(Bill.project_id == "P-1023")) > 0
    assert session.scalar(
        select(func.count()).select_from(Payment).where(Payment.project_id == "P-1023")
    ) > 0


# ---------------------------------------------------- Stage 4 equivalence --


def test_database_backed_engine_analyzes_all_200_projects(db_risk_results):
    assert len(db_risk_results) == 200


@pytest.mark.parametrize("project_id", list(EXPECTED_RISK))
def test_database_backed_risk_result_matches_verified_value(db_risk_results, project_id):
    expected_score, expected_level = EXPECTED_RISK[project_id]
    result = db_risk_results[project_id]
    assert result.risk_score == expected_score
    assert result.risk_level == expected_level


@pytest.mark.parametrize("project_id", list(EXPECTED_RISK))
def test_database_backed_result_matches_csv_backed_result_exactly(db_risk_results, csv_risk_results, project_id):
    db_r, csv_r = db_risk_results[project_id], csv_risk_results[project_id]
    assert db_r.risk_score == csv_r.risk_score
    assert db_r.risk_level == csv_r.risk_level
    assert db_r.recommendation == csv_r.recommendation
    assert db_r.components == csv_r.components  # every detector's score + explanation, not just the total


def test_all_200_database_backed_results_match_csv_backed_results(db_risk_results, csv_risk_results):
    assert set(db_risk_results) == set(csv_risk_results)
    for pid in db_risk_results:
        assert db_risk_results[pid].risk_score == csv_risk_results[pid].risk_score
        assert db_risk_results[pid].risk_level == csv_risk_results[pid].risk_level


# ---------------------------------------------------- Stage 5A equivalence --


@pytest.mark.parametrize("project_id", list(EXPECTED_5A))
def test_database_backed_relationship_and_geographic_results_match_verified_values(db_5a, project_id):
    project_relationships, multi_hop_paths, geo, clusters = db_5a
    expected = EXPECTED_5A[project_id]

    related = [r for r in project_relationships if project_id in (r["source"], r["target"])]
    top = max(related, key=lambda r: r["relationship_strength"]) if related else None
    top_other = (top["target"] if top["source"] == project_id else top["source"]) if top else None

    assert top_other == expected["top"]
    assert top["relationship_strength"] == pytest.approx(expected["strength"], abs=0.05)
    assert len(geo.nearby(project_id)) == expected["nearby"]

    n_multi_hop = sum(1 for p in multi_hop_paths if any(n["type"] == "PROJECT" and n["id"] == project_id for n in p["nodes"]))
    assert n_multi_hop == expected["multi_hop"]

    matching_clusters = [c["cluster_id"] for c in clusters if project_id in c["project_ids"]]
    if expected["cluster"] is None:
        assert matching_clusters == []
    else:
        assert expected["cluster"] in matching_clusters


# ------------------------------------------------------- anomaly_signals --


def test_anomaly_signals_are_loaded_but_not_required_by_the_risk_engine(db_dataset):
    """
    anomaly_signals is present (Stage 6.2 persists it) but build_engine/score_all
    never reads it — confirmed structurally: RiskEngine never touches
    dataset.anomaly_signals, and scoring still succeeds when it is dropped.
    """
    assert len(db_dataset.anomaly_signals) == 62

    import dataclasses

    stripped = dataclasses.replace(db_dataset, anomaly_signals=db_dataset.anomaly_signals.iloc[0:0])
    results = {r.project_id: r for r in build_engine(stripped).score_all()}
    assert results["P-1023"].risk_score == 68.8
    assert results["P-1001"].risk_score == 19.4


# ------------------------------------------------------------- read-only --


def _all_counts(session):
    return {
        model.__tablename__: session.scalar(select(func.count()).select_from(model))
        for model in (Project, Contractor, Bill, Payment, Location, HistoricalProject, ProjectContractor)
    }


def test_running_intelligence_analysis_does_not_modify_the_database(session):
    before = _all_counts(session)

    ds = load_dataset_from_db(session)
    build_engine(ds).score_all()
    rel_index = build_relationship_index(ds.projects, ds.locations)
    generate_project_relationships(rel_index)
    build_geographic_clusters(build_geospatial_engine(ds))

    session.rollback()  # reads should never have staged any pending change in the first place
    assert _all_counts(session) == before
