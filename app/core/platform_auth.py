"""Platform-admin principal (S9.1): the operator of the whole platform, NOT a tenant user.

Credentials come from the environment only (PLATFORM_ADMIN_EMAIL + a bcrypt hash). The token is
a different type from a tenant token: other audience, `typ=platform_admin`, no `tid`. So a
tenant route (which requires aud=resolvedesk-api and `tid`) rejects it, and a platform route
(which requires the platform audience and refuses any `tid`) rejects a tenant token.

Platform tokens are signed with PLATFORM_JWT_SECRET, never the tenant secret.
Failed logins are rate limited in memory per process (a slot is reserved before bcrypt):
the platform role has no table rights, so there is nowhere in the database to keep a
lockout row. A restart resets it; bcrypt cost and the 429 bound online guessing for a
single-operator login.
"""

import hmac
import logging
import threading
from datetime import UTC, datetime, timedelta

import jwt

from app.config import get_settings, platform_admin_enabled
from app.core.auth import ALGORITHM, AuthError, IssuedToken, read_token
from app.core.passwords import verify_password

log = logging.getLogger(__name__)
PRINCIPAL = "platform_admin"
MAX_FAILURES = 5
WINDOW = timedelta(minutes=15)

_lock = threading.Lock()
_failures: list[datetime] = []


class PlatformDisabled(AuthError):
    """Not configured: callers answer 404 as if the feature did not exist."""


class PlatformLocked(AuthError):
    pass


class WrongPrincipal(AuthError):
    """A valid tenant token presented to a platform route (answered 403)."""


def _platform_key() -> str:
    return get_settings().platform_jwt_secret.get_secret_value()  # type: ignore[union-attr]


def reset_failures() -> None:
    with _lock:
        _failures.clear()


def _recent(now: datetime) -> list[datetime]:
    cutoff = now - WINDOW
    _failures[:] = [t for t in _failures if t > cutoff]
    return _failures


def authenticate_platform(email: str, password: str, now: datetime | None = None) -> IssuedToken:
    s = get_settings()
    if not platform_admin_enabled(s):
        raise PlatformDisabled()
    now = now or datetime.now(UTC)
    # Reserve an attempt slot BEFORE the slow bcrypt check, under the lock: parallel guesses
    # each take a slot, so at most MAX_FAILURES run at all. A success gives its slot back.
    with _lock:
        if len(_recent(now)) >= MAX_FAILURES:
            log.warning("platform login locked out")
            raise PlatformLocked()
        _failures.append(now)
    # Always one bcrypt run and a constant-time email compare, so timing doesn't say which
    # part was wrong.
    stored = s.platform_admin_password_hash.get_secret_value().strip()  # type: ignore[union-attr]
    password_ok = verify_password(password, stored)
    email_ok = hmac.compare_digest(
        email.strip().lower().encode(), (s.platform_admin_email or "").strip().lower().encode()
    )
    if not (password_ok and email_ok):
        log.warning("platform login failed")  # never the email or password
        raise AuthError("invalid credentials")
    with _lock:
        _failures.clear()
    expires_at = now + timedelta(minutes=min(s.jwt_ttl_minutes, s.platform_jwt_ttl_minutes))
    claims = {
        "sub": PRINCIPAL,
        "typ": PRINCIPAL,
        "iss": s.jwt_issuer,
        "aud": s.platform_jwt_audience,
        "iat": now,
        "exp": expires_at,
    }
    return IssuedToken(jwt.encode(claims, _platform_key(), algorithm=ALGORITHM), expires_at)


def read_platform_token(token: str) -> str:
    """The actor label of a valid platform token. Raises WrongPrincipal for a tenant token and
    AuthError for anything else invalid. Fails closed when the feature is off."""
    s = get_settings()
    if not platform_admin_enabled(s):
        raise PlatformDisabled()
    try:
        claims = jwt.decode(
            token,
            _platform_key(),
            algorithms=[ALGORITHM],
            issuer=s.jwt_issuer,
            audience=s.platform_jwt_audience,
            options={"require": ["exp", "sub", "typ", "iss", "aud"]},
        )
    except jwt.PyJWTError:
        try:
            read_token(token)  # a genuine tenant token: right system, wrong principal
        except AuthError:
            raise AuthError("invalid token") from None
        raise WrongPrincipal() from None
    if claims["typ"] != PRINCIPAL or claims["sub"] != PRINCIPAL or "tid" in claims:
        raise AuthError("invalid token")
    return PRINCIPAL
