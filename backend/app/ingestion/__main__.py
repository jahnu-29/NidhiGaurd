"""Allows:  python -m backend.app.ingestion"""

import sys

from backend.app.ingestion.csv_ingestion import main

if __name__ == "__main__":
    sys.exit(main())
