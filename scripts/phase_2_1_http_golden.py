"""
Phase 2.1 — HTTP-level golden capture / comparison.

Builds a fresh temporary SQLite database from the seed CSVs (never touches
backend/nidhiguard.db or any production database), drives the real FastAPI app
through TestClient, and records a SHA-256 of every response body for the
intelligence-backed endpoints.

    python scripts/phase_2_1_http_golden.py capture OUT.json   # record
    python scripts/phase_2_1_http_golden.py compare OUT.json   # re-run + diff

Run `capture` on the code BEFORE the cache change and `compare` AFTER it.
Timings are local/sandbox only and are NOT production measurements.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.app.auth.seed import get_demo_password, seed_demo_users  # noqa: E402
from backend.app.db.database import create_db_engine, get_db, init_db  # noqa: E402
from backend.app.ingestion import ingest_all  # noqa: E402
from backend.app.main import app  # noqa: E402

OVERVIEW_PATHS = [
    "/api/dashboard/summary",
    "/api/risk-results",
    "/api/investigation-queue",
    "/api/geography",
    "/api/projects",
    "/api/contractors",
]
PER_PROJECT_SUFFIXES = ["", "/risk", "/relationships", "/geography"]


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _sample_projects(client: TestClient) -> list[str]:
    """Deterministic sample: 3 highest-risk, 3 lowest-risk, 2 from the middle."""
    rows = client.get("/api/risk-results").json()
    rows = sorted(rows, key=lambda r: (-r["risk_score"], r["project_id"]))
    mid = len(rows) // 2
    picks = rows[:3] + rows[mid : mid + 2] + rows[-3:]
    return [r["project_id"] for r in picks]


def run() -> dict:
    tmp = tempfile.mkdtemp(prefix="phase21_")
    eng = create_db_engine(f"sqlite:///{Path(tmp) / 'golden.db'}")
    init_db(bind=eng)
    factory = sessionmaker(bind=eng)
    with factory() as s:
        ingest_all(s)
        seed_demo_users(s)

    def override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    out: dict = {"responses": {}, "timings_s": {}}
    with TestClient(app) as c:
        token = c.post(
            "/api/auth/login", json={"username": "admin", "password": get_demo_password("admin")}
        ).json()["access_token"]
        c.headers["Authorization"] = f"Bearer {token}"

        paths = list(OVERVIEW_PATHS)
        sample = _sample_projects(c)
        out["sample_projects"] = sample
        for pid in sample:
            paths += [f"/api/projects/{pid}{suffix}" for suffix in PER_PROJECT_SUFFIXES]

        for path in paths:
            t0 = time.perf_counter()
            r = c.get(path)
            out["timings_s"][path] = round(time.perf_counter() - t0, 3)
            out["responses"][path] = {"status": r.status_code, "sha256": _sha(r.content), "bytes": len(r.content)}
            print(f"{r.status_code} {out['timings_s'][path]:>8.3f}s  {path}", flush=True)
    app.dependency_overrides.clear()
    eng.dispose()
    return out


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"capture", "compare"}:
        print(__doc__)
        return 2
    mode, path = sys.argv[1], Path(sys.argv[2])
    result = run()
    if mode == "capture":
        path.write_text(json.dumps(result, indent=2, sort_keys=True))
        print(f"captured {len(result['responses'])} responses -> {path}")
        return 0

    golden = json.loads(path.read_text())
    bad = []
    for p, g in golden["responses"].items():
        now = result["responses"].get(p)
        if now is None or now["sha256"] != g["sha256"] or now["status"] != g["status"]:
            bad.append(p)
    print(f"compared {len(golden['responses'])} responses: {len(bad)} differ")
    for p in bad:
        print("  DIFF", p)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
