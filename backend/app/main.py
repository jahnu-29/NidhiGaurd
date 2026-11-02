"""
NidhiGuard backend.

  - Stage 6.1: FastAPI app object, SQLite table creation on startup,
    GET / and GET /health.
  - Stage 6.2: full schema + CSV ingestion (backend/app/ingestion/).
  - Stage 6.3: database-backed intelligence adapter (backend/app/intelligence/).
  - Stage 6.6: authentication + role-based authorization (backend/app/auth/);
    every /api data route now requires a signed-in user with a permitted role.
    "/" and "/health" stay public.
  - Stage 6.4: the /api/* REST layer (backend/app/api/),
    exposing the database and the existing, unmodified Stage 4/5A
    intelligence engine over HTTP for React to consume in Stage 6.5.

The original Stage 6.1 / and /health routes are unchanged below — Stage 6.4
only adds the api_router, it does not replace this file's existing app.

Deliberately NOT here: a frontend connection (Stage 6.5), CRUD endpoints,
auth, or anything importing from src/ (the React frontend). Per the Stage 6
architecture:

    MPLADS/eSAKSHI data -> ingestion -> NidhiGuard database -> intelligence
    engine -> FastAPI -> React
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import api_router
from backend.app.auth.routes import auth_router, users_router
from backend.app.db.database import init_db

# Local-development CORS. The LAN IP of the machine serving the frontend
# changes between sessions, so instead of hardcoding it we accept any
# 192.168.<0-255>.<0-255> host on port 8443 via an anchored regex
# (Starlette uses fullmatch). No wildcard origin is used, so
# allow_credentials=True remains valid.
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://nidhi-gaurd-gamma.vercel.app",
]
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
CORS_ALLOWED_ORIGIN_REGEX = rf"http://(?:192\.168\.{_OCTET}\.{_OCTET}|10\.{_OCTET}\.{_OCTET}\.{_OCTET}):8443"

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Creates tables that don't exist yet; a no-op against an existing,
    # already-correct database. No data is seeded here.
    init_db()
    yield


app = FastAPI(title="NidhiGuard", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_origin_regex=CORS_ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(api_router)


@app.get("/")
def read_root():
    return {"name": "NidhiGuard", "status": "running"}


@app.get("/health")
def health():
    return {"status": "ok"}
