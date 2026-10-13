"""
Stage 6.6 — development/demo user seeding.

    python -m backend.app.auth.seed

Creates one account per role if it does not exist yet (existing accounts are
left untouched, so re-running is safe and never resets a changed password).

THESE ARE DEVELOPMENT / DEMO CREDENTIALS ONLY. The passwords below exist so a
fresh checkout can be exercised locally; they must never be used for anything
real. Override any of them without editing code:

    NIDHIGUARD_DEMO_ADMIN_PASSWORD, NIDHIGUARD_DEMO_INVESTIGATOR_PASSWORD,
    NIDHIGUARD_DEMO_VIEWER_PASSWORD

Seeding is an explicit command — the server never creates users on startup.
"""

from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth.models import Role, User
from backend.app.auth.security import hash_password

# (username, role, env override name, DEMO-ONLY default password)
DEMO_ACCOUNTS: list[tuple[str, Role, str, str]] = [
    ("admin", Role.ADMINISTRATOR, "NIDHIGUARD_DEMO_ADMIN_PASSWORD", "Admin@Demo2026"),
    ("investigator", Role.INVESTIGATOR, "NIDHIGUARD_DEMO_INVESTIGATOR_PASSWORD", "Investigator@Demo2026"),
    ("viewer", Role.VIEWER, "NIDHIGUARD_DEMO_VIEWER_PASSWORD", "Viewer@Demo2026"),
]


def get_demo_password(username: str) -> str:
    """The demo password for a seeded account (env override, else the DEMO-ONLY default)."""
    for name, _role, env_name, default_password in DEMO_ACCOUNTS:
        if name == username:
            return os.environ.get(env_name, default_password)
    raise KeyError(username)


def seed_demo_users(session: Session) -> list[str]:
    """Insert any missing demo accounts. Returns the usernames that were created."""
    created: list[str] = []
    for username, role, _env_name, _default in DEMO_ACCOUNTS:
        if session.scalar(select(User).where(User.username == username)) is not None:
            continue
        session.add(
            User(
                username=username,
                password_hash=hash_password(get_demo_password(username)),
                role=role,
                is_active=True,
            )
        )
        created.append(username)
    session.commit()
    return created


def main() -> None:
    from backend.app.db.database import SessionLocal, init_db

    init_db()
    with SessionLocal() as session:
        created = seed_demo_users(session)
    if created:
        print("Created DEVELOPMENT/DEMO users: " + ", ".join(created))
        print("Default demo passwords are documented in backend/README_AUTH.md (demo use only).")
    else:
        print("Demo users already exist; nothing to do.")


if __name__ == "__main__":
    main()
