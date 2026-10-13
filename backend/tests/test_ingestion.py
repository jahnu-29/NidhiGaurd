"""
Stage 6.2 tests: full schema + deterministic CSV ingestion.

Every test uses its own temporary SQLite file, so the real
backend/nidhiguard.db is never touched. The expected row counts below are
expectations for the CURRENT synthetic seed dataset only — application code
does not hardcode them.
"""

import csv
import shutil
from pathlib import Path

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import SEED_DATA_DIR
from backend.app.db.database import Base, create_db_engine, init_db
from backend.app.db.models import (
    AnomalySignal,
    Bill,
    Contractor,
    HistoricalProject,
    Location,
    Payment,
    Project,
    ProjectContractor,
)
from backend.app.ingestion import INGESTION_ORDER, IngestionError, ingest_all

EXPECTED_COUNTS = {
    "projects": 200,
    "contractors": 75,
    "bills": 888,
    "payments": 983,
    "locations": 200,
    "historical_projects": 500,
    "project_contractors": 200,
    "anomaly_signals": 62,
}


# ----------------------------------------------------------------- fixtures --


def _make_db(path: Path):
    engine = create_db_engine(f"sqlite:///{path}")
    init_db(bind=engine)
    return engine


@pytest.fixture
def engine(tmp_path):
    eng = _make_db(tmp_path / "test.db")
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with sessionmaker(bind=engine)() as s:
        yield s


@pytest.fixture(scope="module")
def loaded_engine(tmp_path_factory):
    """One fully-ingested database shared by the read-only tests."""
    eng = _make_db(tmp_path_factory.mktemp("seeded") / "seeded.db")
    with sessionmaker(bind=eng)() as s:
        ingest_all(s)
    yield eng
    eng.dispose()


@pytest.fixture
def loaded(loaded_engine):
    with sessionmaker(bind=loaded_engine)() as s:
        yield s


@pytest.fixture
def csv_copy(tmp_path) -> Path:
    """A private copy of the seed CSVs that tests may corrupt safely."""
    target = tmp_path / "data"
    shutil.copytree(SEED_DATA_DIR, target)
    return target


def _edit_csv(path: Path, edit) -> int:
    """Apply edit(rows, fieldnames) to a CSV in place; returns the csv line number of rows[0]... (header=1)."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    edit(rows)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return 2  # first data row is on line 2


def _counts(session: Session) -> dict[str, int]:
    return {m.__tablename__: session.scalar(select(func.count()).select_from(m)) for _, m in INGESTION_ORDER}


# -------------------------------------------------------- schema / database --


def test_database_initializes_with_all_expected_tables(engine):
    assert set(EXPECTED_COUNTS) <= set(inspect(engine).get_table_names())


def test_foreign_keys_are_declared_in_the_schema(engine):
    insp = inspect(engine)

    def fks(table):
        return {(fk["constrained_columns"][0], fk["referred_table"]) for fk in insp.get_foreign_keys(table)}

    assert fks("projects") == {("contractor_id", "contractors"), ("location_id", "locations")}
    assert fks("locations") == {("project_id", "projects")}
    assert fks("project_contractors") == {("project_id", "projects"), ("contractor_id", "contractors")}
    assert fks("bills") == {("project_id", "projects"), ("contractor_id", "contractors")}
    assert fks("payments") == {
        ("bill_id", "bills"),
        ("project_id", "projects"),
        ("contractor_id", "contractors"),
    }
    assert fks("historical_projects") == {("contractor_id", "contractors")}
    assert fks("anomaly_signals") == {("project_id", "projects")}


def test_database_itself_enforces_foreign_keys(session):
    """Proves PRAGMA foreign_keys is on: an orphan bill is rejected by SQLite, not just by our loader."""
    from datetime import date

    session.add(
        Bill(
            bill_id="B-X", project_id="P-NOPE", contractor_id="C-NOPE", bill_number="n",
            bill_date=date(2023, 1, 1), bill_type="Final", claimed_amount=1.0, approved_amount=1.0,
            bill_status="Approved", work_period_start=date(2023, 1, 1), work_period_end=date(2023, 1, 1),
            submission_date=date(2023, 1, 1), approval_date=None,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


# ---------------------------------------------------------------- ingestion --


def test_ingestion_completes_and_row_counts_match_source(loaded):
    assert _counts(loaded) == EXPECTED_COUNTS


def test_row_counts_match_the_csv_files_independently(loaded):
    for csv_name, model in INGESTION_ORDER:
        with (SEED_DATA_DIR / csv_name).open(newline="", encoding="utf-8") as f:
            csv_rows = sum(1 for _ in csv.DictReader(f))
        assert loaded.scalar(select(func.count()).select_from(model)) == csv_rows, csv_name


def test_primary_ids_are_unique(loaded):
    for _, model in INGESTION_ORDER:
        pk = next(iter(model.__table__.primary_key.columns))
        total = loaded.scalar(select(func.count()).select_from(model))
        distinct = loaded.scalar(select(func.count(func.distinct(pk))))
        assert total == distinct, model.__tablename__


def test_all_foreign_key_references_are_valid(loaded_engine):
    with loaded_engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []


def test_source_values_are_stored_exactly(loaded):
    """IDs verbatim, blank dates -> NULL, pincode stays a string, bool parsed."""
    p = loaded.get(Project, "P-1001")
    assert (p.project_code, p.contractor_id, p.location_id) == ("MPLADS/UP/2023/0001", "C-040", "L-0001")
    assert p.actual_completion_date is None and p.completion_percentage == 90
    assert p.sanctioned_amount == 2837651.71

    with (SEED_DATA_DIR / "projects.csv").open(newline="", encoding="utf-8") as f:
        blank_completion = sum(1 for r in csv.DictReader(f) if r["actual_completion_date"] == "")
    assert loaded.scalar(select(func.count()).where(Project.actual_completion_date.is_(None))) == blank_completion

    assert loaded.get(Location, "L-0001").pincode == "601440"
    assert all(s.planted_for_testing is True for s in loaded.scalars(select(AnomalySignal)))


# ------------------------------------------------------------ relationships --


def test_project_to_contractor_and_location_are_traversable(loaded):
    p = loaded.get(Project, "P-1023")
    assert p.contractor.contractor_id == p.contractor_id
    assert p.contractor.contractor_name  # resolved through the FK, not by name
    assert p in p.contractor.projects
    assert p.location.location_id == p.location_id
    # documented 1:1: the location points back at this same project
    assert p.location.project_id == p.project_id
    assert [loc.location_id for loc in p.location_of_record] == [p.location_id]
    assert p.location_of_record[0].project is p


def test_project_to_bills_to_payments_are_traversable(loaded):
    with_payments = [
        p for p in loaded.scalars(select(Project)) if p.bills and any(b.payments for b in p.bills)
    ]
    assert with_payments, "expected projects with bills that have payments"
    p = with_payments[0]
    for bill in p.bills:
        assert bill.project_id == p.project_id and bill.project is p
        for pay in bill.payments:
            assert pay.bill_id == bill.bill_id
            # documented: payment.project_id / contractor_id match the parent bill's
            assert pay.project_id == bill.project_id and pay.contractor_id == bill.contractor_id


def test_other_documented_relationships_are_traversable(loaded):
    pc = loaded.scalars(select(ProjectContractor)).first()
    assert pc.project.project_id == pc.project_id and pc.contractor.contractor_id == pc.contractor_id
    assert loaded.scalars(select(HistoricalProject)).first().contractor is not None

    sig = loaded.scalars(select(AnomalySignal)).first()
    assert sig.project.project_id == sig.project_id and sig in sig.project.anomaly_signals

    # every bill's total payments never exceed its approved amount (documented rule holds in the data)
    for bill in loaded.scalars(select(Bill)):
        assert sum(p.payment_amount for p in bill.payments) <= bill.approved_amount + 1e-6


# --------------------------------------------------------------- idempotency --


def test_running_ingestion_twice_does_not_increase_row_counts(session):
    first = ingest_all(session)
    counts_after_first = _counts(session)
    second = ingest_all(session)

    assert counts_after_first == EXPECTED_COUNTS
    assert _counts(session) == EXPECTED_COUNTS
    assert sum(r.inserted for r in first) == sum(EXPECTED_COUNTS.values())
    assert all(r.inserted == 0 and r.updated == 0 for r in second)


def test_rerun_updates_changed_rows_in_place_without_duplicating(session, csv_copy):
    ingest_all(session, csv_copy)

    def bump(rows):
        rows[0]["project_status"] = "Delayed" if rows[0]["project_status"] != "Delayed" else "Completed"

    _edit_csv(csv_copy / "projects.csv", bump)
    results = {r.table: r for r in ingest_all(session, csv_copy)}

    assert results["projects"].updated == 1 and results["projects"].inserted == 0
    assert _counts(session) == EXPECTED_COUNTS


def test_rerun_never_deletes_existing_rows(session, csv_copy):
    ingest_all(session, csv_copy)
    _edit_csv(csv_copy / "anomaly_signals.csv", lambda rows: rows.pop())  # source now has 61 rows
    ingest_all(session, csv_copy)
    assert _counts(session)["anomaly_signals"] == 62


# ------------------------------------------------------ failure / validation --


def _assert_nothing_committed(session):
    session.rollback()
    assert all(v == 0 for v in _counts(session).values())


def test_missing_foreign_key_reference_fails_clearly(session, csv_copy):
    def orphan(rows):
        rows[0]["project_id"] = "P-9999"

    _edit_csv(csv_copy / "bills.csv", orphan)
    with pytest.raises(IngestionError) as exc:
        ingest_all(session, csv_copy)

    message = str(exc.value)
    assert "bills.csv:2" in message and "project_id" in message and "P-9999" in message
    assert "missing foreign-key reference" in message
    _assert_nothing_committed(session)  # rolled back: no partial load


def test_missing_contractor_reference_on_projects_fails_clearly(session, csv_copy):
    _edit_csv(csv_copy / "projects.csv", lambda rows: rows[0].update(contractor_id="C-999"))
    with pytest.raises(IngestionError, match=r"projects\.csv:2.*contractor_id.*C-999"):
        ingest_all(session, csv_copy)
    _assert_nothing_committed(session)


def test_forward_reference_locations_to_missing_project_fails_clearly(session, csv_copy):
    _edit_csv(csv_copy / "locations.csv", lambda rows: rows[0].update(project_id="P-9999"))
    with pytest.raises(IngestionError, match=r"locations.*P-9999"):
        ingest_all(session, csv_copy)
    _assert_nothing_committed(session)


def test_inconsistent_project_location_pair_fails_clearly(session, csv_copy):
    def swap(rows):  # both ids exist, but the documented 1:1 is broken
        rows[0]["location_id"], rows[1]["location_id"] = rows[1]["location_id"], rows[0]["location_id"]

    _edit_csv(csv_copy / "projects.csv", swap)
    with pytest.raises(IngestionError, match="1:1"):
        ingest_all(session, csv_copy)
    _assert_nothing_committed(session)


def test_malformed_value_is_rejected_not_skipped(session, csv_copy):
    _edit_csv(csv_copy / "payments.csv", lambda rows: rows[0].update(payment_amount="not-a-number"))
    with pytest.raises(IngestionError, match=r"payments\.csv:2.*payment_amount.*not-a-number"):
        ingest_all(session, csv_copy)
    _assert_nothing_committed(session)


def test_blank_required_value_is_rejected(session, csv_copy):
    _edit_csv(csv_copy / "contractors.csv", lambda rows: rows[0].update(contractor_name=""))
    with pytest.raises(IngestionError, match=r"contractors\.csv:2.*contractor_name.*required"):
        ingest_all(session, csv_copy)


def test_duplicate_primary_key_in_source_is_rejected(session, csv_copy):
    _edit_csv(csv_copy / "contractors.csv", lambda rows: rows[1].update(contractor_id=rows[0]["contractor_id"]))
    with pytest.raises(IngestionError, match="duplicate primary key"):
        ingest_all(session, csv_copy)


def test_header_mismatch_is_rejected(session, csv_copy):
    path = csv_copy / "locations.csv"
    path.write_text(path.read_text(encoding="utf-8").replace("village_or_ward", "village", 1), encoding="utf-8")
    with pytest.raises(IngestionError, match="header does not match"):
        ingest_all(session, csv_copy)


def test_missing_source_file_is_reported(session, csv_copy):
    (csv_copy / "bills.csv").unlink()
    with pytest.raises(IngestionError, match=r"bills\.csv.*not found"):
        ingest_all(session, csv_copy)


def test_source_csvs_are_not_modified_by_ingestion(session):
    before = {p.name: p.read_bytes() for p in SEED_DATA_DIR.glob("*.csv")}
    ingest_all(session)
    assert {p.name: p.read_bytes() for p in SEED_DATA_DIR.glob("*.csv")} == before
