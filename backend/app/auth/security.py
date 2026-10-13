"""
Stage 6.6 — password hashing and signed access tokens.

Everything here uses only the Python standard library (hashlib.scrypt, hmac,
secrets). That is deliberate: no compiled third-party crypto wheel is needed,
which matters on locked-down Windows machines (see the earlier SQLAlchemy
Application Control .pyd issue) and keeps the dependency list unchanged.

* Passwords: salted scrypt. The stored string carries its own parameters, so
  they can be raised later without invalidating existing hashes.
* Tokens: standard compact JWT (HS256). Claims: sub (user id), jti, iat, exp.
  The role is NOT put in the token — it is read from the database on every
  request, so a role change or deactivation takes effect immediately.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from backend.app import config

# ------------------------------------------------------------- passwords --

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_SALT_BYTES = 16


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SCRYPT_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64e(salt)}${_b64e(digest)}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time check. Any malformed stored hash simply fails verification."""
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored_hash.split("$")
        if scheme != "scrypt":
            return False
        expected = _b64d(digest_b64)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=_b64d(salt_b64), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


_DUMMY_HASH: str | None = None


def dummy_verify(password: str) -> None:
    """Burn the same work as a real check, so an unknown username isn't distinguishable by timing."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_urlsafe(12))
    verify_password(password, _DUMMY_HASH)


# ---------------------------------------------------------------- tokens --


class InvalidTokenError(Exception):
    """Raised for any token that is malformed, badly signed, or expired."""


@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    jti: str
    issued_at: int
    expires_at: int


_HEADER = {"alg": "HS256", "typ": "JWT"}


def _sign(signing_input: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()


def _json_b64(obj: dict) -> str:
    return _b64e(json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def create_access_token(
    user_id: int,
    *,
    secret: str | None = None,
    minutes: int | None = None,
    now: int | None = None,
) -> tuple[str, TokenClaims]:
    issued = int(time.time()) if now is None else now
    lifetime = (config.AUTH_TOKEN_MINUTES if minutes is None else minutes) * 60
    claims = TokenClaims(user_id=user_id, jti=secrets.token_urlsafe(16), issued_at=issued, expires_at=issued + lifetime)
    signing_input = f"{_json_b64(_HEADER)}.{_json_b64({'sub': str(user_id), 'jti': claims.jti, 'iat': claims.issued_at, 'exp': claims.expires_at})}"
    signature = _sign(signing_input.encode("ascii"), secret or config.AUTH_SECRET)
    return f"{signing_input}.{_b64e(signature)}", claims


def decode_access_token(token: str, *, secret: str | None = None, now: int | None = None) -> TokenClaims:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        header = json.loads(_b64d(header_b64))
        # Pin the algorithm: never trust the token's own header to pick one.
        if header.get("alg") != "HS256":
            raise InvalidTokenError("unsupported algorithm")
        expected = _sign(f"{header_b64}.{payload_b64}".encode("ascii"), secret or config.AUTH_SECRET)
        if not hmac.compare_digest(expected, _b64d(signature_b64)):
            raise InvalidTokenError("bad signature")
        payload = json.loads(_b64d(payload_b64))
        claims = TokenClaims(
            user_id=int(payload["sub"]),
            jti=str(payload["jti"]),
            issued_at=int(payload["iat"]),
            expires_at=int(payload["exp"]),
        )
    except InvalidTokenError:
        raise
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise InvalidTokenError("malformed token") from exc

    if claims.expires_at <= (int(time.time()) if now is None else now):
        raise InvalidTokenError("token expired")
    return claims
