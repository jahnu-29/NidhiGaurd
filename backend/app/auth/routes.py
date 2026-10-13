"""
Stage 6.6 — auth endpoints.

  POST /api/auth/login     username + password -> access token + user
  GET  /api/auth/me        current user's identity and role
  POST /api/auth/logout    revoke the presented token (server-side deny-list)

  GET   /api/users         (Administrator) list users
  POST  /api/users         (Administrator) create a user — there is no public sign-up
  PATCH /api/users/{id}    (Administrator) change role and/or enable/disable
"""

from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.auth.dependencies import ADMIN_ONLY, get_current_user, get_token_claims, require_roles
from backend.app.auth.models import RevokedToken, Role, User
from backend.app.auth.security import (
    TokenClaims,
    create_access_token,
    dummy_verify,
    hash_password,
    verify_password,
)
from backend.app.db.database import get_db

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
users_router = APIRouter(prefix="/api/users", tags=["users"], dependencies=[Depends(require_roles(*ADMIN_ONLY))])


# --------------------------------------------------------------- schemas --


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: int
    username: str
    role: Role
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: int  # epoch seconds
    user: UserOut


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=150)
    password: str = Field(min_length=8, max_length=256)
    role: Role


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


# ------------------------------------------------------------------ auth --


@auth_router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.scalar(select(User).where(User.username == body.username.strip().lower()))

    # One generic failure for unknown user, wrong password and inactive
    # account, so the response never reveals which part was wrong.
    generic = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if user is None:
        dummy_verify(body.password)
        raise generic
    if not verify_password(body.password, user.password_hash) or not user.is_active:
        raise generic

    token, claims = create_access_token(user.id)
    return LoginResponse(access_token=token, expires_at=claims.expires_at, user=UserOut.model_validate(user))


@auth_router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@auth_router.post("/logout", status_code=status.HTTP_200_OK)
def logout(claims: TokenClaims = Depends(get_token_claims), db: Session = Depends(get_db)) -> dict:
    now = int(time.time())
    # Housekeeping: tokens past their own expiry are rejected anyway.
    db.execute(delete(RevokedToken).where(RevokedToken.expires_at < now))
    if db.get(RevokedToken, claims.jti) is None:
        db.add(RevokedToken(jti=claims.jti, expires_at=claims.expires_at))
    db.commit()
    return {"status": "logged_out"}


# ------------------------------------------------------------ user admin --


@users_router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)))


@users_router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, db: Session = Depends(get_db)) -> User:
    user = User(
        username=body.username.strip().lower(),
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That username already exists.")
    db.refresh(user)
    return user


@users_router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # Lock-out guard: an administrator cannot demote or disable their own
    # account, so at least one active Administrator always remains.
    if user.id == actor.id and (
        (body.role is not None and body.role != user.role) or body.is_active is False
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own role or deactivate your own account.",
        )

    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    db.commit()
    db.refresh(user)
    return user
