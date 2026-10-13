"""Stage 6.3 — database-backed data access for the existing intelligence engine."""

from backend.app.intelligence.db_data_loader import load_dataset_from_db

__all__ = ["load_dataset_from_db"]
