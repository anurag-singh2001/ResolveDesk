import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import get_settings
from app.core.auth import AuthError, issue_token, read_token


def _claims(**overrides):
    s = get_settings()
    claims = {
        "sub": str(uuid.uuid4()),
        "tid": str(uuid.uuid4()),
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def _sign(claims, secret=None):
    return jwt.encode(claims, secret or get_settings().jwt_secret, algorithm="HS256")


def test_round_trip():
    tid, uid = uuid.uuid4(), uuid.uuid4()
    assert read_token(issue_token(tid, uid)) == (tid, uid)


def test_well_formed_hand_signed_token_accepted():
    """Guards the negative tests below: they fail for the stated reason, not a missing claim."""
    claims = _claims()
    assert read_token(_sign(claims)) == (uuid.UUID(claims["tid"]), uuid.UUID(claims["sub"]))


def test_expired_token_rejected():
    old = datetime.now(UTC) - timedelta(days=2)
    with pytest.raises(AuthError):
        read_token(issue_token(uuid.uuid4(), uuid.uuid4(), now=old))


def test_wrong_secret_rejected():
    with pytest.raises(AuthError):
        read_token(_sign(_claims(), secret="x" * 48))


def test_unsigned_token_rejected():
    with pytest.raises(AuthError):
        read_token(jwt.encode(_claims(), None, algorithm="none"))


def test_tampered_payload_rejected():
    header, _, sig = issue_token(uuid.uuid4(), uuid.uuid4()).split(".")
    forged_payload = _sign(_claims()).split(".")[1]
    with pytest.raises(AuthError):
        read_token(f"{header}.{forged_payload}.{sig}")


@pytest.mark.parametrize("claim,value", [("iss", "someone-else"), ("aud", "other-api")])
def test_wrong_issuer_or_audience_rejected(claim, value):
    with pytest.raises(AuthError):
        read_token(_sign(_claims(**{claim: value})))


@pytest.mark.parametrize("missing", ["sub", "tid", "exp", "iss", "aud"])
def test_required_claims(missing):
    claims = _claims()
    del claims[missing]
    with pytest.raises(AuthError):
        read_token(_sign(claims))
