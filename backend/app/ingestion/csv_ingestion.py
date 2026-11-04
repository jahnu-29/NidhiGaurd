"""
CSV -> SQLite ingestion (Stage 6.2).

Loads the existing synthetic seed dataset (data-source/data/*.csv) into
NidhiGuard's internal database. The CSVs are only ever READ.

Guarantees:
  * Deterministic   - files are processed in a fixed order, rows in file order.
  * Idempotent      - rows are upserted by their source primary key, so running
                      ingestion again never duplicates rows. Rows already in
                      the database but absent from the CSV are NOT deleted.
  * Exact IDs       - source identifiers are stored verbatim (no trimming or
                      case changes to string values).
  * Loud failures   - a malformed row, wrong header, duplicate primary key, or
                      dangling foreign key raises IngestionError with the file,
                      line, column and value. Nothing is silently skipped.
  * All-or-nothing  - the whole run is one transaction; on any error it is
                      rolled back, so the database is never left half-loaded.

Column types and nullability come from the SQLAlchemy models, and CSV headers
must match the model's columns exactly, so schema and loader cannot drift apart.

No scoring, relationship or anomaly logic lives here, and anomaly_signals.csv
is stored as plain data only.

Run:   python -m backend.app.ingestion [--data-dir PATH]
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import Boolean, Date, Float, Integer, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import SEED_DATA_DIR
from backend.app.db.database import Base, SessionLocal, init_db
from backend.app.intelligence.cache import cache as intelligence_cache
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

# Dependency order. locations comes before projects (as documented); the
# locations.project_id -> projects link is the one forward reference and is
# verified after everything is loaded (see _verify_cross_references).
INGESTION_ORDER: list[tuple[str, type[Base]]] = [
    ("contractors.csv", Contractor),
    ("locations.csv", Location),
    ("projects.csv", Project),
    ("project_contractors.csv", ProjectContractor),
    ("bills.csv", Bill),
    ("payments.csv", Payment),
    ("historical_projects.csv", HistoricalProject),
    ("anomaly_signals.csv", AnomalySignal),
]


class IngestionError(Exception):
    """Raised for any malformed / inconsistent source data. Nothing is committed."""


@dataclass
class TableResult:
    table: str
    inserted: int
    updated: int
    unchanged: int
    total_in_db: int


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def _parse_value(column, raw: str):
    """Convert one CSV cell to the column's Python type. Raises ValueError."""
    if raw == "":
        if column.nullable:
            return None
        raise ValueError("value is required but blank")

    col_type = column.type
    if isinstance(col_type, Boolean):
        lowered = raw.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        raise ValueError("expected True/False")
    if isinstance(col_type, Integer):
        return int(raw)
    if isinstance(col_type, Float):
        value = float(raw)
        if math.isnan(value) or math.isinf(value):
            raise ValueError("NaN/infinite numbers are not allowed")
        return value
    if isinstance(col_type, Date):
        return date.fromisoformat(raw)
    return raw  # strings (IDs included) are stored exactly as supplied


def _read_table(path: Path, model: type[Base]) -> list[tuple[int, dict]]:
    """Read + validate one CSV. Returns [(csv_line_number, parsed_row), ...]."""
    if not path.is_file():
        raise IngestionError(f"{path.name}: required source file not found at {path}")

    columns = {c.name: c for c in model.__table__.columns}
    pk_name = next(c.name for c in model.__table__.primary_key.columns)

    rows: list[tuple[int, dict]] = []
    seen_pks: dict[str, int] = {}

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = set(reader.fieldnames or [])
        missing, unexpected = set(columns) - header, header - set(columns)
        if missing or unexpected:
            raise IngestionError(
                f"{path.name}: header does not match table '{model.__tablename__}'"
                f" (missing columns: {sorted(missing) or 'none'};"
                f" unexpected columns: {sorted(unexpected) or 'none'})"
            )

        for raw_row in reader:
            line = reader.line_num
            if None in raw_row or any(v is None for v in raw_row.values()):
                raise IngestionError(f"{path.name}:{line}: malformed row (wrong number of fields)")

            parsed = {}
            for name, column in columns.items():
                try:
                    parsed[name] = _parse_value(column, raw_row[name])
                except ValueError as exc:
                    raise IngestionError(
                        f"{path.name}:{line}: column '{name}' has invalid value {raw_row[name]!r} ({exc})"
                    ) from exc

            pk = parsed[pk_name]
            if pk in seen_pks:
                raise IngestionError(
                    f"{path.name}:{line}: duplicate primary key {pk_name}={pk!r}"
                    f" (first seen on line {seen_pks[pk]})"
                )
            seen_pks[pk] = line
            rows.append((line, parsed))

    return rows


# --------------------------------------------------------------------------- #
# Foreign-key validation
# --------------------------------------------------------------------------- #


def _foreign_keys(model: type[Base]):
    """Yield (column_name, target_table_name, target_column_name) for each FK."""
    for fk_col in model.__table__.columns:
        for fk in fk_col.foreign_keys:
            yield fk_col.name, fk.column.table.name, fk.column.name


def _existing_ids(session: Session, model: type[Base], column: str) -> set:
    return set(session.scalars(select(getattr(model, column))))


def _table_to_model() -> dict[str, type[Base]]:
    return {m.__tablename__: m for _, m in INGESTION_ORDER}


def _check_rows_against_loaded_parents(
    session: Session, csv_name: str, model: type[Base], rows: list[tuple[int, dict]], loaded: set[str]
) -> None:
    """
    Row-level FK check (gives file + line) for every FK whose parent table has
    already been loaded in this run. Forward references are covered later by
    _verify_cross_references.
    """
    tables = _table_to_model()
    for column, target_table, target_column in _foreign_keys(model):
        if target_table not in loaded:
            continue
        valid = _existing_ids(session, tables[target_table], target_column)
        for line, row in rows:
            if row[column] not in valid:
                raise IngestionError(
                    f"{csv_name}:{line}: {column}={row[column]!r} does not exist in"
                    f" {target_table}.{target_column} (missing foreign-key reference)"
                )


def _verify_cross_references(session: Session) -> None:
    """
    Whole-database checks run after all tables are loaded:
      1. Every foreign key in every table resolves (catches forward references,
         e.g. locations.project_id -> projects).
      2. The documented projects<->locations 1:1 is consistent: a project's
         location_id points at a location whose project_id is that project.
    """
    tables = _table_to_model()
    for _, model in INGESTION_ORDER:
        for column, target_table, target_column in _foreign_keys(model):
            valid = _existing_ids(session, tables[target_table], target_column)
            pk_name = next(c.name for c in model.__table__.primary_key.columns)
            for pk, value in session.execute(select(getattr(model, pk_name), getattr(model, column))):
                if value not in valid:
                    raise IngestionError(
                        f"{model.__tablename__}: row {pk_name}={pk!r} has {column}={value!r},"
                        f" which does not exist in {target_table}.{target_column}"
                        f" (missing foreign-key reference)"
                    )

    owner_by_location = {loc: proj for loc, proj in session.execute(select(Location.location_id, Location.project_id))}
    for project_id, location_id in session.execute(select(Project.project_id, Project.location_id)):
        if owner_by_location.get(location_id) != project_id:
            raise IngestionError(
                f"projects/locations: project {project_id!r} points at location {location_id!r},"
                f" but that location belongs to project {owner_by_location.get(location_id)!r}"
                f" (documented 1:1 relationship violated)"
            )


# --------------------------------------------------------------------------- #
# Upsert
# --------------------------------------------------------------------------- #


def _upsert(session: Session, model: type[Base], rows: list[tuple[int, dict]]) -> TableResult:
    pk_name = next(c.name for c in model.__table__.primary_key.columns)
    existing = {getattr(obj, pk_name): obj for obj in session.scalars(select(model))}

    inserted = updated = unchanged = 0
    for _, row in rows:
        obj = existing.get(row[pk_name])
        if obj is None:
            session.add(model(**row))
            inserted += 1
            continue
        for name, value in row.items():
            setattr(obj, name, value)
        if session.is_modified(obj):
            updated += 1
        else:
            unchanged += 1

    session.flush()
    total = session.scalar(select(func.count()).select_from(model))
    return TableResult(model.__tablename__, inserted, updated, unchanged, total)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def ingest_all(session: Session, data_dir: Path | str | None = None) -> list[TableResult]:
    """
    Load every seed CSV into the database bound to `session`, in one
    transaction. Commits on success; rolls back and raises IngestionError on
    any problem. Safe to run repeatedly.
    """
    directory = Path(data_dir) if data_dir is not None else SEED_DATA_DIR
    results: list[TableResult] = []
    loaded: set[str] = set()

    try:
        # Read and validate everything before touching the database, so a bad
        # file fails fast without doing any work.
        parsed = [(name, model, _read_table(directory / name, model)) for name, model in INGESTION_ORDER]

        for csv_name, model, rows in parsed:
            _check_rows_against_loaded_parents(session, csv_name, model, rows, loaded)
            results.append(_upsert(session, model, rows))
            loaded.add(model.__tablename__)

        _verify_cross_references(session)
        session.commit()
    except IngestionError:
        session.rollback()
        raise
    except IntegrityError as exc:  # database-level constraint (incl. deferred FKs at commit)
        session.rollback()
        raise IngestionError(f"database integrity check failed: {exc.orig}") from exc
    except Exception:
        session.rollback()
        raise

    # Phase 2.1: the project/bill/payment/location/contractor data just changed, so any
    # in-process intelligence results computed from the old data are stale. This is the one
    # place those tables are written; a failed run rolls back and never reaches this line.
    intelligence_cache.invalidate_all("ingestion committed")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.app.ingestion",
        description="Load the NidhiGuard seed CSVs into the configured SQLite database (idempotent).",
    )
    parser.add_argument("--data-dir", default=None, help=f"CSV directory (default: {SEED_DATA_DIR})")
    args = parser.parse_args(argv)

    init_db()  # create tables if missing (no-op if they exist)
    with SessionLocal() as session:
        try:
            results = ingest_all(session, args.data_dir)
        except IngestionError as exc:
            print(f"INGESTION FAILED (nothing was committed): {exc}", file=sys.stderr)
            return 1

    print(f"{'table':<22}{'inserted':>9}{'updated':>9}{'unchanged':>10}{'total':>8}")
    for r in results:
        print(f"{r.table:<22}{r.inserted:>9}{r.updated:>9}{r.unchanged:>10}{r.total_in_db:>8}")
    return 0
