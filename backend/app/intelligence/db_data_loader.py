"""
Stage 6.3 — database-backed data access for the intelligence engine.

This module's only job is to produce an `intelligence.data_loader.Dataset` —
the exact same dataclass of 8 pandas DataFrames that `load_dataset()` builds
from the CSVs — except sourced from NidhiGuard's SQLite database instead.

Nothing from Stage 4/5A is reimplemented, rewritten, or adapted here:
`intelligence.risk_engine`, `intelligence.relationship_analysis`, and
`intelligence.geographic_intelligence` are handed this Dataset and run
completely unmodified, exactly as they do against the CSV-backed one.

Read-only: every function here only SELECTs. Nothing is inserted, updated,
or deleted. anomaly_signals is loaded (Stage 6.2 already persists it) only
because Dataset has a slot for it — same "validation-only, never a scoring
input" rule that already applies to the CSV path.

Type/dtype parity with the CSV path (this is the part Stage 6.3's "result
equivalence" requirement actually hinges on):

  * Float/Integer/String columns: SQLAlchemy already returns native Python
    float/int/str from these typed columns, which pandas infers into the
    same float64/int64/object dtypes `pd.to_numeric` produces from CSV text.
    Both paths parse the exact same decimal literals (e.g. "2837651.71"),
    so the resulting float64 values are bit-identical.
  * Date columns: `intelligence.data_loader` parses every date column with
    `pd.to_datetime`, turning blanks into NaT. SQLAlchemy Date columns give
    Python `date`/`None` objects; running the same `pd.to_datetime` over
    them yields identical Timestamp/NaT values.
  * Boolean columns (only anomaly_signals.planted_for_testing): the CSV
    loader does NOT convert this to bool — it stays the literal string
    "True"/"False", since the column isn't in data_loader's numeric/date
    lists. The database stores a real bool for this column (Stage 6.2), so
    it is converted back to "True"/"False" here to match.
  * Nullable string columns (only anomaly_signals.related_entity_id): CSV's
    `keep_default_na=False` makes a blank an empty string, never NaN/None.
    The database stores NULL for the same blank, so None -> "" here.

Column type detection uses each SQLAlchemy model's own column metadata
(Date/Boolean/etc.), not a hand-maintained duplicate list, so this module
can't silently drift from the schema in backend/app/db/models.py.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import Boolean, Date, String, select
from sqlalchemy.orm import Session

from intelligence.data_loader import Dataset

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

# (model, Dataset field name) — order matches intelligence.data_loader.load_dataset.
_TABLES: list[tuple[type, str]] = [
    (Project, "projects"),
    (Contractor, "contractors"),
    (Bill, "bills"),
    (Payment, "payments"),
    (Location, "locations"),
    (HistoricalProject, "historical_projects"),
    (ProjectContractor, "project_contractors"),
    (AnomalySignal, "anomaly_signals"),
]


def _load_table(session: Session, model: type) -> pd.DataFrame:
    """One table -> one DataFrame, typed exactly like intelligence.data_loader's CSV path."""
    columns = list(model.__table__.columns)
    pk = model.__table__.primary_key.columns.values()[0]

    rows = session.execute(select(model).order_by(pk)).scalars().all()
    records = [{c.name: getattr(row, c.name) for c in columns} for row in rows]

    # Build with an explicit, stable column order even for an empty table.
    df = pd.DataFrame.from_records(records, columns=[c.name for c in columns])

    for column in columns:
        if isinstance(column.type, Date):
            # None -> NaT, date -> Timestamp — same as pd.to_datetime on CSV text.
            # astype("datetime64[us]") matches the resolution pandas picks
            # when parsing CSV date *strings* (pd.to_datetime on a column of
            # Python `date` objects alone yields second resolution instead).
            df[column.name] = pd.to_datetime(df[column.name]).astype("datetime64[us]")
        elif isinstance(column.type, Boolean):
            # data_loader.py never casts this column to bool; it stays the
            # literal CSV string. Match that representation exactly.
            df[column.name] = df[column.name].map({True: "True", False: "False"})
        elif isinstance(column.type, String) and column.nullable:
            # Nullable string column: CSV's keep_default_na=False means a
            # blank cell is "" , never NaN — mirror that for a NULL here.
            df[column.name] = df[column.name].fillna("")

    return df


def load_dataset_from_db(session: Session) -> Dataset:
    """
    Build a Dataset identical in shape/dtype to `intelligence.data_loader.load_dataset()`,
    sourced from the NidhiGuard database instead of the CSVs. Read-only — see module docstring.
    """
    tables = {field_name: _load_table(session, model) for model, field_name in _TABLES}
    return Dataset(**tables)
