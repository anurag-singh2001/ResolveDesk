import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import get_settings
from app.core.auth import AuthError, issue_token, read_token


def test_round_trip():
    tid, uid = uuid.uuid4(), uuid.uuid4()
    assert read_token(issue_token(tid, uid)) == (tid, uid)


def test_expired_token_rejected():
    old = datetime.now(UTC) - timedelta(days=2)
    with pytest.raises(AuthError):
        read_token(issue_token(uuid.uuid4(), uuid.uuid4(), now=old))


def test_wrong_secret_rejected():
    claims = {
        "sub": str(uuid.uuid4()),
        "tid": str(uuid.uuid4()),
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    with pytest.raises(AuthError):
        read_token(jwt.encode(claims, "x" * 48, algorithm="HS256"))


def test_unsigned_token_rejected():
    claims = {
        "sub": str(uuid.uuid4()),
        "tid": str(uuid.uuid4()),
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    with pytest.raises(AuthError):
        read_token(jwt.encode(claims, None, algorithm="none"))


def test_tampered_tenant_rejected():
    token = issue_token(uuid.uuid4(), uuid.uuid4())
    header, payload, sig = token.split(".")
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tid": str(uuid.uuid4()),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        get_settings().jwt_secret,
        algorithm="HS256",
    ).split(".")[1]
    with pytest.raises(AuthError):
        read_token(f"{header}.{forged}.{sig}")


@pytest.mark.parametrize("missing", ["sub", "tid", "exp"])
def test_required_claims(missing):
    claims = {
        "sub": str(uuid.uuid4()),
        "tid": str(uuid.uuid4()),
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    del claims[missing]
    with pytest.raises(AuthError):
        read_token(jwt.encode(claims, get_settings().jwt_secret, algorithm="HS256"))
