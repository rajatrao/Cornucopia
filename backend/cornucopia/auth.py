"""Operator authentication: argon2id password hashes and signed sessions.

Sessions are HS256 JWTs signed with a secret only the API holds. The
frontend keeps the token in an HttpOnly cookie and forwards it server-side;
the browser's JavaScript never sees it. Every request re-checks that the
operator still exists and is active, so deactivation takes effect at once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import BaseModel

Role = Literal["viewer", "operator", "approver", "admin"]
ROLE_RANK: dict[str, int] = {"viewer": 0, "operator": 1, "approver": 2, "admin": 3}

_hasher = PasswordHasher()
# A real hash of a random string, used to equalise timing for unknown users.
_DUMMY_HASH = _hasher.hash("cornucopia-timing-equaliser")


class OperatorIdentity(BaseModel):
    id: UUID
    username: str
    display_name: str
    role: Role

    @property
    def actor(self) -> str:
        return f"operator:{self.username}"

    def at_least(self, role: Role) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("passwords must be at least 12 characters")
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def issue_session(
    op: OperatorIdentity, org: UUID, secret: str, ttl_minutes: int
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=ttl_minutes)
    token = jwt.encode(
        {
            "sub": str(op.id),
            "usr": op.username,
            "role": op.role,
            "org": str(org),
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "iss": "cornucopia-api",
        },
        secret,
        algorithm="HS256",
    )
    return token, exp


def decode_session(token: str, secret: str, org: UUID) -> UUID:
    """Return the operator id from a valid session for this organization."""
    claims = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        issuer="cornucopia-api",
        options={"require": ["exp", "sub", "org"]},
    )
    if claims["org"] != str(org):
        raise jwt.InvalidTokenError("session belongs to another organization")
    return UUID(claims["sub"])
