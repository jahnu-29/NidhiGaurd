"""Deterministic CSV -> SQLite ingestion for the NidhiGuard seed dataset (Stage 6.2)."""

from backend.app.ingestion.csv_ingestion import (
    INGESTION_ORDER,
    IngestionError,
    TableResult,
    ingest_all,
)

__all__ = ["INGESTION_ORDER", "IngestionError", "TableResult", "ingest_all"]
