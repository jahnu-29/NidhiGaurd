"""
NidhiGuard Intelligence — Data Loader

Reads the Stage 1 synthetic CSV dataset (read-only) into pandas DataFrames
with parsed dates and numeric columns, and exposes a single `Dataset`
container the detectors build on.

IMPORTANT: `anomaly_signals.csv` is loaded here for CONVENIENCE (tests and
the validation report need it), but no detector in this package may use it
as an input to compute a score. See risk_engine.py / main.py for where the
line between "scoring" and "validation-only" is drawn.

Nothing in this file writes to the CSVs. They are treated as read-only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import pandas as pd

DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data-source", "data",
)

_DATE_COLUMNS = {
    "projects.csv": [
        "sanction_date", "work_order_date", "start_date",
        "expected_completion_date", "actual_completion_date", "created_date",
    ],
    "bills.csv": [
        "bill_date", "work_period_start", "work_period_end",
        "submission_date", "approval_date",
    ],
    "payments.csv": ["payment_date"],
    "contractors.csv": ["registration_date"],
    "historical_projects.csv": ["completion_date"],
    "project_contractors.csv": ["award_date"],
}

_NUMERIC_COLUMNS = {
    "projects.csv": [
        "sanctioned_amount", "estimated_cost", "approved_amount",
        "actual_expenditure", "completion_percentage",
    ],
    "contractors.csv": ["total_projects", "total_project_value"],
    "bills.csv": ["claimed_amount", "approved_amount"],
    "payments.csv": ["payment_amount"],
    "locations.csv": ["latitude", "longitude"],
    "historical_projects.csv": [
        "sanctioned_amount", "actual_expenditure", "latitude", "longitude",
    ],
    "project_contractors.csv": ["contract_value"],
}


def _read_csv(data_dir: str, filename: str) -> pd.DataFrame:
    path = os.path.join(data_dir, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Expected dataset file not found: {path}. "
            f"Stage 4 reads the Stage 1 CSV package and does not invent data."
        )
    df = pd.read_csv(path, dtype=str, keep_default_na=False)

    for col in _NUMERIC_COLUMNS.get(filename, []):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in _DATE_COLUMNS.get(filename, []):
        if col in df.columns:
            # blank strings -> NaT, real dates -> Timestamp
            df[col] = pd.to_datetime(df[col].replace("", pd.NA), errors="coerce")

    return df


@dataclass
class Dataset:
    projects: pd.DataFrame
    contractors: pd.DataFrame
    bills: pd.DataFrame
    payments: pd.DataFrame
    locations: pd.DataFrame
    historical_projects: pd.DataFrame
    project_contractors: pd.DataFrame
    anomaly_signals: pd.DataFrame  # validation-only, see module docstring

    def project_ids(self) -> list[str]:
        return list(self.projects["project_id"])


def load_dataset(data_dir: str = DEFAULT_DATA_DIR) -> Dataset:
    """Load every CSV in the Stage 1 package into a Dataset. Read-only."""
    return Dataset(
        projects=_read_csv(data_dir, "projects.csv"),
        contractors=_read_csv(data_dir, "contractors.csv"),
        bills=_read_csv(data_dir, "bills.csv"),
        payments=_read_csv(data_dir, "payments.csv"),
        locations=_read_csv(data_dir, "locations.csv"),
        historical_projects=_read_csv(data_dir, "historical_projects.csv"),
        project_contractors=_read_csv(data_dir, "project_contractors.csv"),
        anomaly_signals=_read_csv(data_dir, "anomaly_signals.csv"),
    )
