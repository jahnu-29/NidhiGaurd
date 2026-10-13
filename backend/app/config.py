"""
NidhiGuard backend configuration.

Stage 6.1 scope: just enough to give the database layer a single,
unambiguous source for its connection URL. Nothing here talks to the
intelligence engine or the frontend.
"""

import os
import secrets
from pathlib import Path

# backend/app/config.py -> backend/app/ -> backend/
# Resolved from this file's own location (not the process's current working
# directory), so `uvicorn backend.app.main:app` behaves identically whether
# it's launched from the project root, from backend/, or anywhere else.
BACKEND_DIR = Path(__file__).resolve().parent.parent

# Default DB file lives at backend/nidhiguard.db, as specified for Stage 6.1.
# Override with the NIDHIGUARD_DATABASE_URL env var if ever needed (e.g. a
# later stage swapping in PostgreSQL) without touching this file.
DEFAULT_DATABASE_PATH = BACKEND_DIR / "nidhiguard.db"
DATABASE_URL = os.environ.get(
    "NIDHIGUARD_DATABASE_URL",
    f"sqlite:///{DEFAULT_DATABASE_PATH}",
)

# Stage 6.2: the reproducible seed dataset. The CSVs are never modified by the
# backend; ingestion only reads them. Overridable for tests / alternate seeds.
SEED_DATA_DIR = Path(
    os.environ.get("NIDHIGUARD_SEED_DATA_DIR", BACKEND_DIR.parent / "data-source" / "data")
)


# --------------------------------------------------------------------------
# Stage 6.6 — authentication settings.
#
# Secrets come from the environment only; nothing real is committed. For
# convenience a local, git-ignored `backend/.env` file (KEY=VALUE lines) is
# read first — real environment variables always win over it. See
# backend/.env.example for the variables.
# --------------------------------------------------------------------------


def _load_dotenv(path: Path) -> None:
    """Tiny .env reader (no dependency). Never overrides existing env vars."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BACKEND_DIR / ".env")

# HMAC key used to sign access tokens. If it is not configured, a random
# per-process key is generated at startup: the app stays safe (no default or
# guessable secret exists) but issued tokens stop working when the server
# restarts. Set NIDHIGUARD_AUTH_SECRET to a long random value for stable
# sessions, e.g.:  python -c "import secrets; print(secrets.token_urlsafe(48))"
AUTH_SECRET_CONFIGURED: bool = bool(os.environ.get("NIDHIGUARD_AUTH_SECRET"))
AUTH_SECRET: str = os.environ.get("NIDHIGUARD_AUTH_SECRET") or secrets.token_urlsafe(48)

# Access-token lifetime in minutes (no refresh tokens in Stage 6.6).
AUTH_TOKEN_MINUTES: int = int(os.environ.get("NIDHIGUARD_AUTH_TOKEN_MINUTES", "480"))