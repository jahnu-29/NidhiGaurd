"""
Stage 6.6 — authentication + role-based authorization tests.

Uses one freshly ingested temporary database (never backend/nidhiguard.db),
injected via dependency override on get_db, exactly like test_api.py. Tests
that change users create their own throw-away accounts through the admin API
so they cannot affect each other.
"""

import base64
import itertools
import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import sessionmaker

from backend.app.auth.dependencies import ADMIN_ONLY, ALL_ROLES, INVESTIGATOR_UP
from backend.app.auth.models import RevokedToken, Role, User
from backend.app.auth.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from backend.app.auth.seed import DEMO_ACCOUNTS, get_demo_password, seed_demo_users
from backend.app.db.database import create_db_engine, get_db, init_db
from backend.app.ingestion import ingest_all
from backend.app.main import app

# (path, roles that are allowed). This is the intended permission table.
PROTECTED = [
    ("/api/dashboard/summary", ALL_ROLES),
    ("/api/projects", ALL_ROLES),
    ("/api/projects/P-1023/risk", ALL_ROLES),
    ("/api/risk-results", ALL_ROLES),
    ("/api/projects/P-1023", INVESTIGATOR_UP),
    ("/api/projects/P-1023/relationships", INVESTIGATOR_UP),
    ("/api/projects/P-1023/geography", INVESTIGATOR_UP),
    ("/api/contractors", INVESTIGATOR_UP),
    ("/api/contractors/C-054", INVESTIGATOR_UP),
    ("/api/geography", INVESTIGATOR_UP),
    ("/api/investigation-queue", INVESTIGATOR_UP),
    ("/api/users", ADMIN_ONLY),
]
ROLE_USERNAME = {Role.ADMINISTRATOR: "admin", Role.INVESTIGATOR: "investigator", Role.VIEWER: "viewer"}


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    eng = create_db_engine(f"sqlite:///{tmp_path_factory.mktemp('auth') / 'auth_test.db'}")
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
    with TestClient(app) as c:  # note: no default Authorization header
        yield c
    app.dependency_overrides.clear()


def _login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def tokens(client):
    out = {}
    for role, username in ROLE_USERNAME.items():
        resp = _login(client, username, get_demo_password(username))
        assert resp.status_code == 200, resp.text
        out[role] = resp.json()["access_token"]
    return out


_counter = itertools.count(1)


@pytest.fixture
def make_user(client, tokens):
    """Create a throw-away user via the Administrator API; returns (user_json, password)."""

    def _make(role=Role.VIEWER):
        username = f"tmp-user-{next(_counter)}"
        password = "Tmp-Password-123"
        resp = client.post(
            "/api/users",
            json={"username": username, "password": password, "role": role.value},
            headers=_headers(tokens[Role.ADMINISTRATOR]),
        )
        assert resp.status_code == 201, resp.text
        return resp.json(), password

    return _make


# ------------------------------------------------------- 1. valid login --


@pytest.mark.parametrize("role,username", list(ROLE_USERNAME.items()))
def test_valid_login_returns_token_and_role(client, role, username):
    resp = _login(client, username, get_demo_password(username))
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_at"] > time.time()
    assert body["user"]["username"] == username
    assert body["user"]["role"] == role.value
    assert body["user"]["is_active"] is True
    assert "password" not in json.dumps(body).lower()  # no password / password_hash in the response


def test_login_username_is_case_insensitive(client):
    assert _login(client, "  ADMIN ", get_demo_password("admin")).status_code == 200


# ------------------------------------------------ 2. invalid credentials --


def test_invalid_password_is_rejected(client):
    resp = _login(client, "admin", "definitely-wrong")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


def test_unknown_user_and_wrong_password_look_identical(client):
    wrong_pw = _login(client, "admin", "definitely-wrong")
    no_user = _login(client, "no-such-user", "definitely-wrong")
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()  # never reveals which part was wrong


def test_login_rejects_empty_fields(client):
    assert _login(client, "", "x").status_code == 422
    assert _login(client, "admin", "").status_code == 422


# ----------------------------------------------------- 3. inactive user --


def test_inactive_user_cannot_log_in(client, tokens, make_user):
    user, password = make_user(Role.VIEWER)
    assert _login(client, user["username"], password).status_code == 200
    resp = client.patch(f"/api/users/{user['id']}", json={"is_active": False}, headers=_headers(tokens[Role.ADMINISTRATOR]))
    assert resp.status_code == 200 and resp.json()["is_active"] is False

    denied = _login(client, user["username"], password)
    assert denied.status_code == 401
    assert denied.json() == _login(client, "admin", "definitely-wrong").json()  # same generic message


def test_deactivating_a_user_kills_their_existing_token(client, tokens, make_user):
    user, password = make_user(Role.VIEWER)
    token = _login(client, user["username"], password).json()["access_token"]
    assert client.get("/api/auth/me", headers=_headers(token)).status_code == 200

    client.patch(f"/api/users/{user['id']}", json={"is_active": False}, headers=_headers(tokens[Role.ADMINISTRATOR]))
    assert client.get("/api/auth/me", headers=_headers(token)).status_code == 401


# ----------------------------------------------- 4. missing authentication --


@pytest.mark.parametrize("path", [p for p, _ in PROTECTED])
def test_protected_routes_require_authentication(client, path):
    resp = client.get(path)
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


def test_me_and_logout_require_authentication(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/logout").status_code == 401


def test_public_routes_remain_public(client):
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200


@pytest.mark.parametrize("header", ["Bearer not-a-token", "Bearer a.b.c", "Basic YWRtaW46YWRtaW4=", "Bearer"])
def test_garbage_credentials_are_rejected(client, header):
    assert client.get("/api/projects", headers={"Authorization": header}).status_code == 401


# --------------------------------------------- 5. valid authenticated use --


def test_me_returns_identity_and_role(client, tokens):
    for role, username in ROLE_USERNAME.items():
        body = client.get("/api/auth/me", headers=_headers(tokens[role])).json()
        assert (body["username"], body["role"]) == (username, role.value)


def test_authenticated_request_returns_data(client, tokens):
    resp = client.get("/api/projects", headers=_headers(tokens[Role.VIEWER]))
    assert resp.status_code == 200
    assert len(resp.json()) == 200


# --------------------- 6-9. Administrator / Investigator / Viewer matrix --


DENIED = [(role, path) for path, allowed in PROTECTED for role in Role if role not in allowed]


@pytest.mark.parametrize("role,path", DENIED, ids=[f"{r.value}-{p}" for r, p in DENIED])
def test_role_is_denied_with_403_where_not_permitted(client, tokens, role, path):
    """Every disallowed (role, endpoint) pair is a 403 — decided before any data work happens."""
    resp = client.get(path, headers=_headers(tokens[role]))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Your role does not permit access to this resource."


def test_administrator_authorization(client, tokens):
    h = _headers(tokens[Role.ADMINISTRATOR])
    for path in ("/api/projects", "/api/contractors", "/api/contractors/C-054", "/api/users", "/api/projects/P-1023"):
        assert client.get(path, headers=h).status_code == 200, path
    assert client.get("/api/geography", headers=h).status_code == 200  # heavy route, checked once


def test_investigator_authorization(client, tokens):
    h = _headers(tokens[Role.INVESTIGATOR])
    for path in ("/api/projects", "/api/contractors", "/api/contractors/C-054", "/api/projects/P-1023"):
        assert client.get(path, headers=h).status_code == 200, path
    assert client.get("/api/investigation-queue", headers=h).status_code == 200  # heavy route, checked once
    assert client.get("/api/users", headers=h).status_code == 403  # Investigator must NOT manage users


def test_viewer_authorization(client, tokens):
    h = _headers(tokens[Role.VIEWER])
    assert client.get("/api/projects", headers=h).status_code == 200
    assert client.get("/api/projects/P-1023/risk", headers=h).status_code == 200
    assert client.get("/api/risk-results", headers=h).status_code == 200
    assert client.get("/api/dashboard/summary", headers=h).status_code == 200


def test_viewer_denied_from_investigator_and_admin_endpoints(client, tokens):
    h = _headers(tokens[Role.VIEWER])
    for path in ("/api/investigation-queue", "/api/contractors", "/api/geography", "/api/users", "/api/projects/P-1023"):
        assert client.get(path, headers=h).status_code == 403, path
    # user-management writes are denied too
    assert client.post("/api/users", json={"username": "x-y-z", "password": "Password-1234", "role": "Viewer"}, headers=h).status_code == 403
    assert client.patch("/api/users/1", json={"role": "Viewer"}, headers=h).status_code == 403


def test_investigator_cannot_use_user_management_writes(client, tokens):
    h = _headers(tokens[Role.INVESTIGATOR])
    assert client.post("/api/users", json={"username": "x-y-z", "password": "Password-1234", "role": "Viewer"}, headers=h).status_code == 403
    assert client.patch("/api/users/1", json={"role": "Viewer"}, headers=h).status_code == 403


def test_forbidden_precedes_not_found(client, tokens):
    """A Viewer probing a non-existent id must get 403, not a 404 that leaks what exists."""
    assert client.get("/api/projects/P-9999", headers=_headers(tokens[Role.VIEWER])).status_code == 403
    assert client.get("/api/projects/P-9999").status_code == 401


def test_role_change_takes_effect_immediately(client, tokens, make_user):
    user, password = make_user(Role.VIEWER)
    token = _login(client, user["username"], password).json()["access_token"]
    assert client.get("/api/contractors", headers=_headers(token)).status_code == 403

    resp = client.patch(f"/api/users/{user['id']}", json={"role": "Investigator"}, headers=_headers(tokens[Role.ADMINISTRATOR]))
    assert resp.status_code == 200 and resp.json()["role"] == "Investigator"
    assert client.get("/api/contractors", headers=_headers(token)).status_code == 200  # same token, new role


# ---------------------------------------------------- 10. logout/revoke --


def test_logout_invalidates_the_token(client):
    token = _login(client, "viewer", get_demo_password("viewer")).json()["access_token"]
    assert client.get("/api/projects", headers=_headers(token)).status_code == 200

    out = client.post("/api/auth/logout", headers=_headers(token))
    assert out.status_code == 200 and out.json() == {"status": "logged_out"}

    assert client.get("/api/projects", headers=_headers(token)).status_code == 401
    assert client.get("/api/auth/me", headers=_headers(token)).status_code == 401
    # logging out twice is harmless (token already unusable -> 401, not a crash)
    assert client.post("/api/auth/logout", headers=_headers(token)).status_code == 401


def test_logout_only_ends_that_session(client):
    first = _login(client, "viewer", get_demo_password("viewer")).json()["access_token"]
    second = _login(client, "viewer", get_demo_password("viewer")).json()["access_token"]
    client.post("/api/auth/logout", headers=_headers(first))
    assert client.get("/api/projects", headers=_headers(first)).status_code == 401
    assert client.get("/api/projects", headers=_headers(second)).status_code == 200


# --------------------------------------------------------- user admin --


def test_admin_can_list_create_and_update_users(client, tokens):
    h = _headers(tokens[Role.ADMINISTRATOR])
    users = client.get("/api/users", headers=h).json()
    assert {u["username"] for u in users} >= {"admin", "investigator", "viewer"}
    assert all("password" not in u and "password_hash" not in u for u in users)


def test_duplicate_username_is_conflict(client, tokens):
    resp = client.post(
        "/api/users",
        json={"username": "ADMIN", "password": "Password-1234", "role": "Viewer"},
        headers=_headers(tokens[Role.ADMINISTRATOR]),
    )
    assert resp.status_code == 409


def test_create_user_validates_input(client, tokens):
    h = _headers(tokens[Role.ADMINISTRATOR])
    assert client.post("/api/users", json={"username": "ok-user", "password": "short", "role": "Viewer"}, headers=h).status_code == 422
    assert client.post("/api/users", json={"username": "ok-user", "password": "Password-1234", "role": "Root"}, headers=h).status_code == 422


def test_admin_cannot_demote_or_disable_themselves(client, tokens):
    h = _headers(tokens[Role.ADMINISTRATOR])
    me = client.get("/api/auth/me", headers=h).json()
    assert client.patch(f"/api/users/{me['id']}", json={"role": "Viewer"}, headers=h).status_code == 400
    assert client.patch(f"/api/users/{me['id']}", json={"is_active": False}, headers=h).status_code == 400
    assert client.get("/api/auth/me", headers=h).json()["role"] == "Administrator"


def test_update_unknown_user_is_404(client, tokens):
    assert client.patch("/api/users/99999", json={"is_active": False}, headers=_headers(tokens[Role.ADMINISTRATOR])).status_code == 404


# ------------------------------------------------ token / hash internals --


def test_passwords_are_hashed_never_stored_in_plaintext(engine):
    with sessionmaker(bind=engine)() as s:
        users = list(s.scalars(select(User)))
    assert users
    for u in users:
        assert u.password_hash.startswith("scrypt$")
        for _, _, _, default in DEMO_ACCOUNTS:
            assert default not in u.password_hash


def test_password_hash_is_salted_and_verifies():
    a, b = hash_password("Same-Password-1"), hash_password("Same-Password-1")
    assert a != b  # per-hash salt
    assert verify_password("Same-Password-1", a) and verify_password("Same-Password-1", b)
    assert not verify_password("same-password-1", a)
    assert not verify_password("x", "not-a-valid-hash")


def test_token_round_trip_and_tamper_detection():
    token, claims = create_access_token(7, secret="s1", minutes=5)
    assert decode_access_token(token, secret="s1").user_id == 7
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, secret="a-different-secret")
    head, payload, sig = token.split(".")
    forged = base64.urlsafe_b64encode(json.dumps({"sub": "1", "jti": claims.jti, "iat": 0, "exp": 9999999999}).encode()).rstrip(b"=").decode()
    with pytest.raises(InvalidTokenError):
        decode_access_token(f"{head}.{forged}.{sig}", secret="s1")  # payload edited, signature stale


def test_expired_token_is_rejected():
    token, _ = create_access_token(7, secret="s1", minutes=1, now=int(time.time()) - 3600)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, secret="s1")


def test_alg_none_token_is_rejected():
    b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    unsigned = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': '1', 'jti': 'x', 'iat': 0, 'exp': 9999999999})}."
    with pytest.raises(InvalidTokenError):
        decode_access_token(unsigned, secret="s1")


def test_expired_and_forged_tokens_get_401_over_http(client):
    expired, _ = create_access_token(1, minutes=1, now=int(time.time()) - 3600)
    forged, _ = create_access_token(1, secret="not-the-server-secret")
    for token in (expired, forged):
        assert client.get("/api/projects", headers=_headers(token)).status_code == 401


def test_token_for_deleted_or_unknown_user_is_rejected(client):
    token, _ = create_access_token(987654)
    assert client.get("/api/projects", headers=_headers(token)).status_code == 401


# ------------------------------------------------------------- seeding --


def test_seed_is_idempotent_and_creates_one_account_per_role(engine):
    with sessionmaker(bind=engine)() as s:
        assert seed_demo_users(s) == []  # already seeded by the fixture; nothing re-created
        roles = sorted(u.role.value for u in s.scalars(select(User)) if u.username in ROLE_USERNAME.values())
    assert roles == ["Administrator", "Investigator", "Viewer"]


def test_auth_tables_exist(engine):
    assert {"users", "revoked_tokens"} <= set(inspect(engine).get_table_names())


def test_logout_records_revocation_row(client, engine):
    token = _login(client, "investigator", get_demo_password("investigator")).json()["access_token"]
    jti = decode_access_token(token).jti
    client.post("/api/auth/logout", headers=_headers(token))
    with sessionmaker(bind=engine)() as s:
        assert s.get(RevokedToken, jti) is not None
