"""
Stage 6.6 — authentication and role-authorization dependencies.

  get_current_user        valid, unexpired, un-revoked token + a user that
                          still exists and is active  -> 401 otherwise
  require_roles(*roles)   same, and the user's role must be one of `roles`
                          -> 403 otherwise

The user's role is read from the database on every request. Authorization is
decided here, on the server; hiding things in React is only a UX nicety.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.auth.models import RevokedToken, Role, User
from backend.app.auth.security import InvalidTokenError, TokenClaims, decode_access_token
from backend.app.db.database import get_db

# auto_error=False so a missing header produces our own consistent 401.
_bearer = HTTPBearer(auto_error=False)

ALL_ROLES: tuple[Role, ...] = (Role.ADMINISTRATOR, Role.INVESTIGATOR, Role.VIEWER)
INVESTIGATOR_UP: tuple[Role, ...] = (Role.ADMINISTRATOR, Role.INVESTIGATOR)
ADMIN_ONLY: tuple[Role, ...] = (Role.ADMINISTRATOR,)


def _unauthorized(detail: str = "Authentication required.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def get_token_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> TokenClaims:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    try:
        claims = decode_access_token(credentials.credentials)
    except InvalidTokenError:
        raise _unauthorized("Invalid or expired token.")
    if db.get(RevokedToken, claims.jti) is not None:
        raise _unauthorized("Session has ended. Please sign in again.")
    return claims


def get_current_user(
    claims: TokenClaims = Depends(get_token_claims),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise _unauthorized("Account is not available.")
    return user


def require_roles(*roles: Role):
    """Build a dependency that admits only the given roles (401 if unauthenticated, 403 if wrong role)."""
    allowed = frozenset(roles)

    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role does not permit access to this resource.",
            )
        return user

    return _checker
