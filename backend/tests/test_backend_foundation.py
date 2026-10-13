"""
Stage 6.1 acceptance tests: prove the FastAPI + SQLAlchemy + SQLite
foundation works, without touching the intelligence engine or frontend.
"""

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from backend.app.db.database import engine
from backend.app.db.models import Project
from backend.app.main import app


def test_app_imports():
    assert app is not None
    assert app.title == "NidhiGuard"


def test_health_endpoint_returns_ok():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_endpoint_identifies_app():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "NidhiGuard"
    assert body["status"] == "running"


def test_startup_creates_project_table():
    # Entering the TestClient context runs the app's lifespan startup,
    # which calls init_db() -> Base.metadata.create_all(engine).
    with TestClient(app):
        pass
    table_names = inspect(engine).get_table_names()
    assert "projects" in table_names
    assert Project.__tablename__ == "projects"
