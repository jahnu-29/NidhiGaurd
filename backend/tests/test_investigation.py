"""
V2.6 — investigator workflow + audit trail tests.

Same pattern as test_api.py / test_auth.py: one freshly ingested temporary
database (never backend/nidhiguard.db), injected via a get_db override. Tests
that write state each use their own project id, so they cannot affect each other.
"""

import itertools

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.app.auth.models import Role
from backend.app.auth.seed import get_demo_password, seed_demo_users
from backend.app.db.database import create_db_engine, get_db, init_db
from backend.app.db.models import Project
from backend.app.ingestion import ingest_all
from backend.app.investigation.models import (
    AuditTrailImmutableError,
    Investigation,
    InvestigationHistory,
    InvestigationStatus,
)
from backend.app.investigation.schemas import MAX_NOTE_LENGTH
from backend.app.main import app

ROLE_USERNAME = {Role.ADMINISTRATOR: "admin", Role.INVESTIGATOR: "investigator", Role.VIEWER: "viewer"}
STATUSES = ["NEW", "UNDER_REVIEW", "REQUIRES_FURTHER_INVESTIGATION", "REVIEWED_NO_CONCERN", "ESCALATED"]
FRAUD_PHRASES = ("fraud detected", "fraud confirmed", "fraud probability", "fraud case")


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    eng = create_db_engine(f"sqlite:///{tmp_path_factory.mktemp('inv') / 'investigation_test.db'}")
    init_db(bind=eng)
    with sessionmaker(bind=eng)() as s:
        ingest_all(s)
        seed_demo_users(s)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def client(engine):
    factory = sessionmaker(bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:  # no default Authorization header
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def auth(client):
    out = {}
    for role, username in ROLE_USERNAME.items():
        resp = client.post("/api/auth/login", json={"username": username, "password": get_demo_password(username)})
        assert resp.status_code == 200, resp.text
        out[role] = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    return out


_ids = itertools.count(1100)


@pytest.fixture
def pid():
    """A project id no other test in this module writes to."""
    return f"P-{next(_ids)}"


def _status_url(p):
    return f"/api/projects/{p}/investigation/status"


def _notes_url(p):
    return f"/api/projects/{p}/investigation/notes"


def _get(client, headers, p):
    r = client.get(f"/api/projects/{p}/investigation", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _set_status(client, headers, p, status):
    return client.post(_status_url(p), json={"status": status}, headers=headers)


def _row_counts(engine):
    with sessionmaker(bind=engine)() as s:
        return (
            s.scalar(select(func.count()).select_from(Investigation)),
            s.scalar(select(func.count()).select_from(InvestigationHistory)),
        )


# ------------------------------------------- 1, 2. default state / creation --


def test_default_status_is_new_and_viewing_creates_nothing(client, auth, engine, pid):
    before = _row_counts(engine)
    body = _get(client, auth[Role.INVESTIGATOR], pid)
    assert body["project_id"] == pid
    assert body["status"] == "NEW"
    assert body["history"] == []
    assert body["created_at"] is None
    assert _row_counts(engine) == before  # a GET never writes


def test_investigation_is_created_for_valid_project_on_first_action(client, auth, engine, pid):
    r = _set_status(client, auth[Role.INVESTIGATOR], pid, "UNDER_REVIEW")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_id"] == pid
    assert body["created_at"] is not None
    with sessionmaker(bind=engine)() as s:
        record = s.get(Investigation, pid)
        assert record is not None and record.status is InvestigationStatus.UNDER_REVIEW


# --------------------------------------------------- 3, 4. who can change --


@pytest.mark.parametrize("role", [Role.INVESTIGATOR, Role.ADMINISTRATOR])
def test_investigator_and_administrator_can_change_status(client, auth, pid, role):
    r = _set_status(client, auth[role], pid, "REQUIRES_FURTHER_INVESTIGATION")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "REQUIRES_FURTHER_INVESTIGATION"
    assert _get(client, auth[Role.VIEWER], pid)["status"] == "REQUIRES_FURTHER_INVESTIGATION"


@pytest.mark.parametrize("status", STATUSES)
def test_every_controlled_status_is_accepted(client, auth, status):
    p = f"P-{next(_ids)}"
    if status == "NEW":  # NEW is the starting state, so move away and back
        assert _set_status(client, auth[Role.INVESTIGATOR], p, "ESCALATED").status_code == 200
    r = _set_status(client, auth[Role.INVESTIGATOR], p, status)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == status


# ------------------------------------------------------- 5, 7. viewer reads --


def test_viewer_cannot_change_status_and_nothing_is_written(client, auth, engine, pid):
    before = _row_counts(engine)
    r = _set_status(client, auth[Role.VIEWER], pid, "UNDER_REVIEW")
    assert r.status_code == 403
    assert _row_counts(engine) == before
    assert _get(client, auth[Role.VIEWER], pid)["status"] == "NEW"


def test_viewer_cannot_add_note_and_nothing_is_written(client, auth, engine, pid):
    before = _row_counts(engine)
    r = client.post(_notes_url(pid), json={"note": "viewer attempt"}, headers=auth[Role.VIEWER])
    assert r.status_code == 403
    assert _row_counts(engine) == before


def test_viewer_can_view_status_and_history(client, auth, pid):
    assert _set_status(client, auth[Role.INVESTIGATOR], pid, "UNDER_REVIEW").status_code == 200
    body = _get(client, auth[Role.VIEWER], pid)
    assert body["status"] == "UNDER_REVIEW"
    assert [h["action"] for h in body["history"]] == ["STATUS_CHANGE"]
    summaries = client.get("/api/investigations", headers=auth[Role.VIEWER])
    assert summaries.status_code == 200
    assert pid in {i["project_id"] for i in summaries.json()["items"]}


# ---------------------------------------------------------------- 6. notes --


@pytest.mark.parametrize("role", [Role.INVESTIGATOR, Role.ADMINISTRATOR])
def test_investigator_and_administrator_can_add_note(client, auth, pid, role):
    r = client.post(_notes_url(pid), json={"note": "  Cost is above comparable projects.  "}, headers=auth[role])
    assert r.status_code == 200, r.text
    entry = r.json()["history"][-1]
    assert entry["action"] == "NOTE"
    assert entry["note"] == "Cost is above comparable projects."  # trimmed, otherwise verbatim
    assert entry["username"] == ROLE_USERNAME[role]


def test_note_does_not_change_status(client, auth, pid):
    assert _set_status(client, auth[Role.INVESTIGATOR], pid, "ESCALATED").status_code == 200
    body = client.post(_notes_url(pid), json={"note": "Escalating for desk review."}, headers=auth[Role.INVESTIGATOR]).json()
    assert body["status"] == "ESCALATED"
    note_entry = body["history"][-1]
    assert note_entry["previous_status"] is None and note_entry["new_status"] is None


@pytest.mark.parametrize("bad", ["", "   ", "\n\t "])
def test_blank_note_is_rejected(client, auth, pid, bad):
    r = client.post(_notes_url(pid), json={"note": bad}, headers=auth[Role.INVESTIGATOR])
    assert r.status_code == 422


def test_note_length_limit(client, auth, pid):
    ok = client.post(_notes_url(pid), json={"note": "x" * MAX_NOTE_LENGTH}, headers=auth[Role.INVESTIGATOR])
    assert ok.status_code == 200
    too_long = client.post(_notes_url(pid), json={"note": "x" * (MAX_NOTE_LENGTH + 1)}, headers=auth[Role.INVESTIGATOR])
    assert too_long.status_code == 422


def test_note_missing_or_extra_fields_rejected(client, auth, pid):
    assert client.post(_notes_url(pid), json={}, headers=auth[Role.INVESTIGATOR]).status_code == 422
    r = client.post(_notes_url(pid), json={"note": "ok", "user_id": 1}, headers=auth[Role.INVESTIGATOR])
    assert r.status_code == 422  # the acting user always comes from the token, never the body


# ------------------------------------------------------- 8, 9, 10. history --


def test_status_change_creates_audit_entry(client, auth, pid):
    body = _set_status(client, auth[Role.INVESTIGATOR], pid, "UNDER_REVIEW").json()
    assert len(body["history"]) == 1
    e = body["history"][0]
    assert e["action"] == "STATUS_CHANGE"
    assert (e["previous_status"], e["new_status"]) == ("NEW", "UNDER_REVIEW")
    assert e["project_id"] == pid
    assert e["username"] == "investigator" and e["user_role"] == "Investigator"
    assert e["created_at"].endswith("Z")  # explicit UTC, safe for the browser to localise
    assert e["note"] is None


def test_note_creates_audit_entry(client, auth, pid):
    body = client.post(_notes_url(pid), json={"note": "Needs site verification."}, headers=auth[Role.ADMINISTRATOR]).json()
    assert len(body["history"]) == 1
    e = body["history"][0]
    assert e["action"] == "NOTE" and e["note"] == "Needs site verification."
    assert e["username"] == "admin" and e["user_role"] == "Administrator"


def test_audit_history_preserves_previous_entries_in_order(client, auth, pid):
    h = auth[Role.INVESTIGATOR]
    _set_status(client, h, pid, "UNDER_REVIEW")
    first_snapshot = _get(client, h, pid)["history"]
    client.post(_notes_url(pid), json={"note": "Cost significantly above comparable projects."}, headers=h)
    _set_status(client, h, pid, "REQUIRES_FURTHER_INVESTIGATION")
    history = _get(client, h, pid)["history"]

    assert len(history) == 3
    assert history[0] == first_snapshot[0]  # the first entry is untouched by later actions
    assert [e["action"] for e in history] == ["STATUS_CHANGE", "NOTE", "STATUS_CHANGE"]
    assert [(e["previous_status"], e["new_status"]) for e in (history[0], history[2])] == [
        ("NEW", "UNDER_REVIEW"),
        ("UNDER_REVIEW", "REQUIRES_FURTHER_INVESTIGATION"),
    ]
    assert [e["created_at"] for e in history] == sorted(e["created_at"] for e in history)  # chronological
    assert len({e["id"] for e in history}) == 3


def test_same_status_is_rejected_and_adds_no_history(client, auth, engine, pid):
    h = auth[Role.INVESTIGATOR]
    _set_status(client, h, pid, "UNDER_REVIEW")
    before = _row_counts(engine)
    assert _set_status(client, h, pid, "UNDER_REVIEW").status_code == 409
    assert _row_counts(engine) == before
    # NEW -> NEW on a project with no record is also a no-op, and must not leave a stray record
    fresh = f"P-{next(_ids)}"
    assert _set_status(client, h, fresh, "NEW").status_code == 409
    assert _get(client, h, fresh)["created_at"] is None


# ----------------------------------------------------- 11, 12. validation --


@pytest.mark.parametrize("path", ["status", "notes"])
def test_invalid_project_is_rejected(client, auth, path):
    h = auth[Role.INVESTIGATOR]
    body = {"status": "UNDER_REVIEW"} if path == "status" else {"note": "hello"}
    assert client.post(f"/api/projects/DOES-NOT-EXIST/investigation/{path}", json=body, headers=h).status_code == 404
    assert client.get("/api/projects/DOES-NOT-EXIST/investigation", headers=h).status_code == 404


@pytest.mark.parametrize("bad", ["FRAUD_CONFIRMED", "under_review", "CLOSED", "", None, 3])
def test_invalid_status_is_rejected(client, auth, engine, pid, bad):
    before = _row_counts(engine)
    r = client.post(_status_url(pid), json={"status": bad}, headers=auth[Role.INVESTIGATOR])
    assert r.status_code == 422
    assert _row_counts(engine) == before


# ------------------------------------------------ 13. unauthenticated / bad --


@pytest.mark.parametrize("method,suffix,body", [
    ("post", "/status", {"status": "UNDER_REVIEW"}),
    ("post", "/notes", {"note": "anonymous"}),
    ("get", "", None),
])
def test_unauthenticated_requests_are_rejected(client, engine, pid, method, suffix, body):
    before = _row_counts(engine)
    url = f"/api/projects/{pid}/investigation{suffix}"
    r = client.get(url) if method == "get" else client.post(url, json=body)
    assert r.status_code == 401
    assert _row_counts(engine) == before


def test_garbage_token_is_rejected(client, pid):
    r = client.post(_status_url(pid), json={"status": "ESCALATED"}, headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401


def test_authorization_is_checked_before_project_lookup(client, auth):
    # A Viewer probing a nonexistent project learns nothing about it: 403, not 404.
    assert _set_status(client, auth[Role.VIEWER], "DOES-NOT-EXIST", "ESCALATED").status_code == 403


def test_acting_user_cannot_be_spoofed_through_the_body(client, auth, pid):
    r = client.post(_status_url(pid), json={"status": "ESCALATED", "username": "admin"}, headers=auth[Role.INVESTIGATOR])
    assert r.status_code == 422


# ------------------------------------------------ 14. audit trail immutable --


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
@pytest.mark.parametrize("suffix", ["", "/history", "/status", "/notes", "/history/1", "/notes/1"])
def test_no_api_route_can_edit_or_delete_history(client, auth, pid, method, suffix):
    h = auth[Role.ADMINISTRATOR]  # even the most privileged role
    r = getattr(client, method)(f"/api/projects/{pid}/investigation{suffix}", headers=h)
    assert r.status_code in (404, 405)


def test_history_survives_attempted_api_tampering(client, auth, pid):
    h = auth[Role.ADMINISTRATOR]
    _set_status(client, h, pid, "UNDER_REVIEW")
    before = _get(client, h, pid)["history"]
    client.delete(f"/api/projects/{pid}/investigation", headers=h)
    client.put(f"/api/projects/{pid}/investigation", json={"status": "NEW"}, headers=h)
    assert _get(client, h, pid)["history"] == before


def test_orm_refuses_to_update_or_delete_history_rows(engine, client, auth, pid):
    _set_status(client, auth[Role.INVESTIGATOR], pid, "UNDER_REVIEW")
    with sessionmaker(bind=engine)() as s:
        row = s.scalars(select(InvestigationHistory).where(InvestigationHistory.project_id == pid)).one()
        row.note = "rewritten"
        with pytest.raises(AuditTrailImmutableError):
            s.commit()
        s.rollback()
        s.delete(s.scalars(select(InvestigationHistory).where(InvestigationHistory.project_id == pid)).one())
        with pytest.raises(AuditTrailImmutableError):
            s.commit()
        s.rollback()
    assert len(_get(client, auth[Role.VIEWER], pid)["history"]) == 1


# ------------------------------------- 15. existing project / risk APIs --


def test_existing_project_and_risk_apis_still_work(client, auth):
    h = auth[Role.INVESTIGATOR]
    assert len(client.get("/api/projects", headers=h).json()) == 200
    assert client.get("/api/projects/P-1023", headers=h).status_code == 200
    r = client.get("/api/projects/P-1023/risk", headers=h).json()
    assert (r["risk_score"], r["risk_level"]) == (68.8, "HIGH")
    assert client.get("/api/projects/P-1001/risk", headers=h).json()["risk_score"] == 19.4
    assert client.get("/api/projects/P-1023/relationships", headers=h).status_code == 200
    assert client.get("/api/projects/P-1023/geography", headers=h).status_code == 200
    assert client.get("/api/dashboard/summary", headers=h).status_code == 200


def test_viewer_permissions_on_existing_v1_routes_are_unchanged(client, auth):
    v = auth[Role.VIEWER]
    assert client.get("/api/projects/P-1023/risk", headers=v).status_code == 200
    for path in ("/api/projects/P-1023", "/api/projects/P-1023/relationships", "/api/investigation-queue"):
        assert client.get(path, headers=v).status_code == 403


def test_workflow_status_never_changes_risk_or_queue_ranking(client, auth):
    h = auth[Role.INVESTIGATOR]
    queue_before = client.get("/api/investigation-queue", headers=h).json()
    risk_before = client.get("/api/projects/P-1023/risk", headers=h).json()

    for s in ("UNDER_REVIEW", "ESCALATED", "REVIEWED_NO_CONCERN"):
        assert _set_status(client, h, "P-1023", s).status_code == 200
    client.post(_notes_url("P-1023"), json={"note": "Reviewed, no concern."}, headers=h)

    assert client.get("/api/projects/P-1023/risk", headers=h).json() == risk_before
    assert client.get("/api/investigation-queue", headers=h).json() == queue_before  # same members, same order


def test_low_risk_project_stays_out_of_queue_even_with_workflow_state(client, auth):
    h = auth[Role.INVESTIGATOR]
    assert _set_status(client, h, "P-1001", "ESCALATED").status_code == 200  # opened directly
    assert _get(client, h, "P-1001")["status"] == "ESCALATED"
    queue_ids = {i["project_id"] for i in client.get("/api/investigation-queue", headers=h).json()["items"]}
    assert "P-1001" not in queue_ids
    assert client.get("/api/projects/P-1001/risk", headers=h).json()["risk_level"] == "LOW"


def test_workflow_tables_are_additive_and_source_data_untouched(engine, client, auth):
    with sessionmaker(bind=engine)() as s:
        assert s.scalar(select(func.count()).select_from(Project)) == 200


def test_system_text_never_asserts_fraud(client, auth, pid):
    h = auth[Role.INVESTIGATOR]
    _set_status(client, h, pid, "ESCALATED")
    text = str(_get(client, h, pid)).lower()
    assert not any(phrase in text for phrase in FRAUD_PHRASES)
