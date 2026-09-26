import uuid

import jwt
import pytest

from muse.modules.auth.auth_handler import InvalidSession, SessionCodec
from muse.modules.auth.auth_schema import Principal

SECRET = "s" * 32


def test_session_round_trip():
    codec = SessionCodec(SECRET, ttl_seconds=60)
    principal = Principal(id=uuid.uuid4(), username="owner")
    assert codec.decode(codec.encode(principal)) == principal


def test_session_signed_with_another_secret_is_rejected():
    token = SessionCodec("x" * 32, 60).encode(Principal(id=uuid.uuid4(), username="owner"))
    with pytest.raises(InvalidSession):
        SessionCodec(SECRET, 60).decode(token)


def test_centrifugo_style_token_is_not_a_session():
    # Same secret, missing audience: a realtime token must not work as a session.
    token = jwt.encode({"sub": str(uuid.uuid4())}, SECRET, algorithm="HS256")
    with pytest.raises(InvalidSession):
        SessionCodec(SECRET, 60).decode(token)


def test_expired_session_is_rejected():
    codec = SessionCodec(SECRET, ttl_seconds=-1)
    with pytest.raises(InvalidSession):
        codec.decode(codec.encode(Principal(id=uuid.uuid4(), username="owner")))


def test_short_secret_is_refused():
    with pytest.raises(ValueError):
        SessionCodec("short", 60)
