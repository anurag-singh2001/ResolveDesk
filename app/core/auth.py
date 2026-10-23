"""Demo auth: password login for seeded users, short-lived HS256 JWTs.

The token carries only tenant id and user id. Role and scope are re-read from the DB on every
request, so the token can't be used to claim a role.
"""

import hmac
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import Engine, select

from app.config import get_settings
from app.core.db import tenant_session
from app.core.models import Organization, User
from app.core.tenancy import SLUG_RE, load_context, tenant_id_for

ALGORITHM = "HS256"


class AuthError(Exception):
    pass


def issue_token(tenant_id: uuid.UUID, user_id: uuid.UUID, now: datetime | None = None) -> str:
    s = get_settings()
    now = now or datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "iat": now,
        "exp": now + timedelta(minutes=s.jwt_ttl_minutes),
    }
    return jwt.encode(claims, s.jwt_secret, algorithm=ALGORITHM)


def read_token(token: str) -> tuple[uuid.UUID, uuid.UUID]:
    """(tenant_id, user_id) from a valid token. Raises AuthError otherwise."""
    try:
        claims = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=[ALGORITHM],  # pinned: rejects "none" and algorithm confusion
            options={"require": ["exp", "sub", "tid"]},
        )
        return uuid.UUID(claims["tid"]), uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise AuthError("invalid token") from exc


def authenticate(engine: Engine, tenant_slug: str, email: str, password: str) -> str | None:
    """Token for a seeded demo user, or None. Same None for every failure (no user probing)."""
    s = get_settings()
    if not s.demo_auth or not hmac.compare_digest(password.encode(), s.demo_password.encode()):
        return None
    if not SLUG_RE.match(tenant_slug):
        return None
    tenant_id = tenant_id_for(tenant_slug)
    with tenant_session(tenant_id, engine) as session:
        if session.get(Organization, tenant_id) is None:
            return None
        user_id = session.scalar(select(User.id).where(User.email == email))
        if user_id is None or load_context(session, tenant_id, user_id) is None:
            return None
    return issue_token(tenant_id, user_id)
