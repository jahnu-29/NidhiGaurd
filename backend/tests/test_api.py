"""
Stage 6.4 API tests.

Each test module-scoped TestClient points the app at one shared, freshly
ingested temporary database (never backend/nidhiguard.db), via dependency
overrides on get_db — the same pattern FastAPI recommends for testing.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.app.auth.seed import get_demo_password, seed_demo_users
from backend.app.db.database import create_db_engine, get_db, init_db
from backend.app.db.models import Bill, Contractor, HistoricalProject, Location, Payment, Project, ProjectContractor
from backend.app.ingestion import ingest_all
from backend.app.main import app

RISK_DISCLAIMER = "Risk score indicates anomaly signals and does not constitute a finding of fraud."


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    eng = create_db_engine(f"sqlite:///{tmp_path_factory.mktemp('api') / 'api_test.db'}")
    init_db(bind=eng)
    with sessionmaker(bind=eng)() as s:
        ingest_all(s)
        seed_demo_users(s)  # Stage 6.6: the data routes now require a signed-in user
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def client(engine):
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        # Stage 6.6: sign in as the demo Administrator (all routes permitted), so
        # these Stage 6.4/6.5 tests keep exercising the data endpoints unchanged.
        # Authentication/authorization itself is tested in test_auth.py.
        token = c.post(
            "/api/auth/login", json={"username": "admin", "password": get_demo_password("admin")}
        ).json()["access_token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c
    app.dependency_overrides.clear()


def _all_counts(engine):
    with sessionmaker(bind=engine)() as s:
        return {
            model.__tablename__: s.scalar(select(func.count()).select_from(model))
            for model in (Project, Contractor, Bill, Payment, Location, HistoricalProject, ProjectContractor)
        }


# --------------------------------------------------------------- health --


def test_health_still_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_root_still_identifies_app(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {"name": "NidhiGuard", "status": "running"}


# -------------------------------------------------------------- projects --


def test_list_projects_returns_200_projects(client):
    r = client.get("/api/projects")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 200
    assert {p["project_id"] for p in body} >= {"P-1023", "P-1001", "P-1020"}


def test_get_project_p1023_returns_expected_fields(client):
    r = client.get("/api/projects/P-1023")
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == "P-1023"
    assert body["contractor"]["contractor_id"] == "C-054"
    assert body["location"]["location_id"] == body["location_id"]
    assert len(body["bills"]) > 0
    assert len(body["payments"]) > 0


def test_get_unknown_project_returns_404(client):
    r = client.get("/api/projects/DOES-NOT-EXIST")
    assert r.status_code == 404


# ------------------------------------------------------------------ risk --


@pytest.mark.parametrize(
    "project_id,expected_score,expected_level",
    [("P-1023", 68.8, "HIGH"), ("P-1001", 19.4, "LOW"), ("P-1020", 19.8, "LOW")],
)
def test_project_risk_matches_verified_stage4_result(client, project_id, expected_score, expected_level):
    r = client.get(f"/api/projects/{project_id}/risk")
    assert r.status_code == 200
    body = r.json()
    assert body["risk_score"] == expected_score
    assert body["risk_level"] == expected_level


def test_risk_response_contains_component_breakdown(client):
    body = client.get("/api/projects/P-1023/risk").json()
    components = body["components"]
    for key in ("cost_anomaly", "project_similarity", "contractor_pattern", "billing_anomaly", "geographic_signal"):
        assert key in components
        assert "score" in components[key] and "explanation" in components[key]


def test_risk_response_contains_fraud_disclaimer(client):
    body = client.get("/api/projects/P-1023/risk").json()
    assert body["disclaimer"] == RISK_DISCLAIMER


def test_risk_for_unknown_project_returns_404(client):
    assert client.get("/api/projects/DOES-NOT-EXIST/risk").status_code == 404


# --------------------------------------------------------- relationships --


def test_project_relationships_top_match_for_p1023(client):
    r = client.get("/api/projects/P-1023/relationships")
    assert r.status_code == 200
    body = r.json()
    top = max(body["relationships"], key=lambda item: item["relationship_strength"])
    assert top["related_project_id"] == "P-1151"
    assert top["relationship_strength"] == pytest.approx(77.5, abs=0.05)
    # The disclaimer may reference "fraud" only to disclaim it (same pattern as
    # RISK_DISCLAIMER itself) — what must never appear is an assertion that
    # fraud/collusion/corruption IS present.
    assert "fraud detected" not in body["disclaimer"].lower()
    assert "collusion detected" not in body["disclaimer"].lower()


# ------------------------------------------------------------- geography --


def test_project_geography_for_p1023(client):
    r = client.get("/api/projects/P-1023/geography")
    assert r.status_code == 200
    body = r.json()
    assert len(body["nearby_projects"]) == 3
    assert body["cluster_id"] == "GEO-CLUSTER-004"


def test_project_geography_for_p1001(client):
    body = client.get("/api/projects/P-1001/geography").json()
    assert len(body["nearby_projects"]) == 1
    assert body["cluster_id"] == "GEO-CLUSTER-001"


def test_project_geography_for_p1020_has_no_context(client):
    body = client.get("/api/projects/P-1020/geography").json()
    assert body["nearby_projects"] == []
    assert body["cluster_id"] is None


# ------------------------------------------------------------ contractors --


def test_list_contractors_returns_75(client):
    r = client.get("/api/contractors")
    assert r.status_code == 200
    assert len(r.json()) == 75


def test_contractor_detail_for_c054(client):
    r = client.get("/api/contractors/C-054")
    assert r.status_code == 200
    body = r.json()
    assert body["contractor_name"] == "Balaji Infrastructure Associates"
    assert body["total_projects"] == 14
    assert any(p["project_id"] == "P-1023" for p in body["projects"])


def test_unknown_contractor_returns_404(client):
    assert client.get("/api/contractors/DOES-NOT-EXIST").status_code == 404


# ------------------------------------------------------- investigation queue --


def test_investigation_queue_has_80_items(client):
    r = client.get("/api/investigation-queue")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 80
    assert len(body["items"]) == 80


def test_investigation_queue_ranks_p1023_first(client):
    body = client.get("/api/investigation-queue").json()
    first = body["items"][0]
    assert first["project_id"] == "P-1023"
    assert first["rank"] == 1
    assert first["risk_level"] == "HIGH"
    assert first["recommendation"] == "Investigation recommended"


def test_investigation_queue_excludes_low_risk_projects(client):
    body = client.get("/api/investigation-queue").json()
    assert all(item["risk_level"] != "LOW" for item in body["items"])


# --------------------------------------------------------------- dashboard --


def test_dashboard_summary_matches_verified_distribution(client):
    r = client.get("/api/dashboard/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["total_projects"] == 200
    assert body["risk_level_distribution"] == {"critical": 0, "high": 1, "medium": 79, "low": 120}
    assert body["investigation_queue_size"] == 80


# -------------------------------------------------- independence / safety --


def test_api_does_not_require_frontend_generated_typescript_data(client):
    """Sanity: nothing in the backend process touches src/. Proven by these
    endpoints working at all inside a backend-only test process with no
    Node/TS toolchain involved."""
    r = client.get("/api/projects/P-1023")
    assert r.status_code == 200


def test_api_requests_do_not_modify_the_database(client, engine):
    before = _all_counts(engine)
    client.get("/api/projects")
    client.get("/api/projects/P-1023")
    client.get("/api/projects/P-1023/risk")
    client.get("/api/projects/P-1023/relationships")
    client.get("/api/projects/P-1023/geography")
    client.get("/api/investigation-queue")
    client.get("/api/dashboard/summary")
    client.get("/api/contractors")
    client.get("/api/contractors/C-054")
    assert _all_counts(engine) == before


def test_openapi_lists_the_new_endpoints(client):
    schema = client.get("/openapi.json").json()
    paths = set(schema["paths"])
    for expected in (
        "/api/projects",
        "/api/projects/{project_id}",
        "/api/projects/{project_id}/risk",
        "/api/projects/{project_id}/relationships",
        "/api/projects/{project_id}/geography",
        "/api/contractors",
        "/api/contractors/{contractor_id}",
        "/api/investigation-queue",
        "/api/dashboard/summary",
    ):
        assert expected in paths
