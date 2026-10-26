"""Password login (bcrypt) with a lockout, and short-lived HS256 JWTs.

The token carries only tenant id and user id. Role and scope are re-read from the DB on every
request, so the token can't be used to claim a role.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import Engine, delete, func, select

from app.config import get_settings
from app.core.db import tenant_session
from app.core.models import LoginFailure, Organization, User
from app.core.passwords import verify_password
from app.core.tenancy import SLUG_RE, load_context, tenant_id_for

ALGORITHM = "HS256"


class AuthError(Exception):
    pass


class InvalidCredentials(AuthError):
    """Wrong tenant, email or password: one error for all of them."""


class LockedOut(AuthError):
    """Too many recent failures for this tenant+email."""


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_at: datetime


def issue_token_with_expiry(
    tenant_id: uuid.UUID, user_id: uuid.UUID, now: datetime | None = None
) -> IssuedToken:
    s = get_settings()
    now = now or datetime.now(UTC)
    expires_at = now + timedelta(minutes=s.jwt_ttl_minutes)
    claims = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "iat": now,
        "exp": expires_at,
    }
    return IssuedToken(jwt.encode(claims, s.jwt_secret, algorithm=ALGORITHM), expires_at)


def issue_token(tenant_id: uuid.UUID, user_id: uuid.UUID, now: datetime | None = None) -> str:
    return issue_token_with_expiry(tenant_id, user_id, now).token


def read_token(token: str) -> tuple[uuid.UUID, uuid.UUID]:
    """(tenant_id, user_id) from a valid token. Raises AuthError otherwise."""
    s = get_settings()
    try:
        claims = jwt.decode(
            token,
            s.jwt_secret,
            algorithms=[ALGORITHM],  # pinned: rejects "none" and algorithm confusion
            issuer=s.jwt_issuer,
            audience=s.jwt_audience,
            options={"require": ["exp", "sub", "tid", "iss", "aud"]},
        )
        return uuid.UUID(claims["tid"]), uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise AuthError("invalid token") from exc


# Valid slug that no tenant uses: unknown tenants still run the same queries (timing).
_NO_TENANT_SLUG = "_no_such_tenant"


def email_key(email: str) -> str:
    """Lockout key for an email: case and surrounding spaces don't give extra attempts."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def authenticate(
    engine: Engine, tenant_slug: str, email: str, password: str, now: datetime | None = None
) -> IssuedToken:
    """A token for a user whose password matches its bcrypt hash.

    Raises InvalidCredentials for every kind of mismatch (same error, same queries, and always
    one bcrypt check, so neither the body nor the timing tells which part was wrong), and
    LockedOut once the tenant+email has too many recent failures. Unknown emails are counted
    too, so a 429 doesn't reveal whether an account exists.
    """
    s = get_settings()
    now = now or datetime.now(UTC)
    slug = tenant_slug if SLUG_RE.match(tenant_slug) else _NO_TENANT_SLUG
    tenant_id = tenant_id_for(slug)
    key = email_key(email)
    since = now - timedelta(minutes=s.login_window_minutes)
    recent = (LoginFailure.email_hash == key) & (LoginFailure.failed_at > since)
    with tenant_session(tenant_id, engine) as session:
        org_exists = session.get(Organization, tenant_id) is not None
        failures = session.scalar(select(func.count()).select_from(LoginFailure).where(recent))
        row = session.execute(
            select(User.id, User.password_hash, User.password_is_demo).where(User.email == email)
        ).first()
        user_id, stored_hash, is_demo = row if row else (None, None, False)
        ctx = load_context(session, tenant_id, user_id or uuid.UUID(int=0))
    if failures >= s.login_max_failures:
        raise LockedOut()
    # bcrypt is CPU only; run it with no transaction (and no pooled connection) held open.
    password_ok = verify_password(password, stored_hash)
    # A known demo password is only accepted while demo accounts are on (never in prod), even
    # if a dev-seeded hash is still in the DB.
    demo_ok = not is_demo or (s.demo_auth and s.app_env != "prod")
    ok = bool(password_ok and demo_ok and org_exists and user_id and ctx)
    with tenant_session(tenant_id, engine) as session:
        mine = LoginFailure.email_hash == key
        if ok:
            session.execute(delete(LoginFailure).where(mine))
        elif org_exists:  # no organization row to attach a failure to otherwise (FK)
            # Prune the tenant's expired rows (every key), so one-off emails can't grow the table.
            session.execute(delete(LoginFailure).where(LoginFailure.failed_at <= since))
            session.add(LoginFailure(tenant_id=tenant_id, email_hash=key, failed_at=now))
    if not ok:
        raise InvalidCredentials()
    return issue_token_with_expiry(tenant_id, user_id, now)
