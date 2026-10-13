"""
Stage 6.6 — authentication tables: users and revoked tokens.

These tables belong to NidhiGuard's own access-control layer. They are not
part of the MPLADS/eSAKSHI-derived dataset and are never touched by CSV
ingestion or by the intelligence engine.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.database import Base


class Role(str, enum.Enum):
    """The three NidhiGuard roles. One login system; the role decides access."""

    ADMINISTRATOR = "Administrator"
    INVESTIGATOR = "Investigator"
    VIEWER = "Viewer"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Stored lower-cased and stripped, so lookups are case-insensitive.
    username: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    # Salted scrypt hash string (see security.py). Never a plaintext password.
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, native_enum=False, validate_strings=True, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class RevokedToken(Base):
    """
    Tokens invalidated by logout. Access tokens are stateless signed values, so
    logout is implemented as a server-side deny-list keyed by the token's `jti`.
    Rows are only needed until the token would have expired anyway.
    """

    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String, primary_key=True)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)  # epoch seconds
