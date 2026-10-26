"""bcrypt password hashing. Every check costs one bcrypt run, also for unknown users."""

from functools import lru_cache

import bcrypt

from app.config import get_settings

# bcrypt only reads the first 72 bytes; longer passwords are refused rather than truncated,
# so two different long passwords can't both match one hash.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str, rounds: int | None = None) -> str:
    raw = password.encode()
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password longer than {MAX_PASSWORD_BYTES} bytes")
    salt = bcrypt.gensalt(rounds or get_settings().bcrypt_rounds)
    return bcrypt.hashpw(raw, salt).decode()


@lru_cache
def _dummy_hash(rounds: int) -> bytes:
    """A hash nobody's password matches, at the configured cost, for unknown users."""
    return bcrypt.hashpw(b"no user has this password", bcrypt.gensalt(rounds))


def verify_password(password: str, stored_hash: str | None) -> bool:
    """True only if `password` matches `stored_hash`. Runs bcrypt even when there's no hash
    (unknown user, no password set) or the password is too long, so timing doesn't tell."""
    raw = password.encode()
    target = stored_hash.encode() if stored_hash else None
    usable = target is not None and len(raw) <= MAX_PASSWORD_BYTES
    try:
        ok = bcrypt.checkpw(
            raw if usable else b"x",
            target if usable else _dummy_hash(get_settings().bcrypt_rounds),
        )
    except ValueError:  # malformed stored hash: fail closed
        return False
    return ok and usable
