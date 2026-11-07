"""Shared test configuration."""

import os

# Phase 2.1: the app's startup hook would otherwise warm the intelligence cache on a
# background thread against the default (non-test) database every time a TestClient starts.
os.environ.setdefault("NIDHIGUARD_WARM_INTELLIGENCE_CACHE", "0")
