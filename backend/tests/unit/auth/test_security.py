import time
import uuid

import jwt
import pytest

from app.common.enums import UserRole
from app.core.config import get_settings
from app.modules.auth.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password_does_not_store_plaintext():
    hashed = hash_password("correct-horse-battery-staple")
    assert hashed != "correct-horse-battery-staple"


def test_verify_password_accepts_correct_and_rejects_wrong():
    hashed = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_create_and_decode_access_token_round_trips_user_id():
    user_id = uuid.uuid4()
    token = create_access_token(user_id, UserRole.TRADER)

    decoded_user_id = decode_access_token(token)

    assert decoded_user_id == user_id


def test_create_access_token_accepts_plain_string_role():
    # ORM objects fresh off a String-typed column come back as plain str, not
    # re-wrapped as UserRole -- this must not blow up.
    token = create_access_token(uuid.uuid4(), "TRADER")
    payload = jwt.decode(token, options={"verify_signature": False})
    assert payload["role"] == "TRADER"


def test_decode_access_token_rejects_garbage():
    with pytest.raises(InvalidTokenError):
        decode_access_token("not-a-real-token")


def test_decode_access_token_rejects_expired_token(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "jwt_access_token_expire_minutes", -1)  # already expired

    token = create_access_token(uuid.uuid4(), UserRole.ADMIN)
    time.sleep(0.01)

    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_access_token_rejects_wrong_signature():
    settings = get_settings()
    token = create_access_token(uuid.uuid4(), UserRole.ADMIN)
    tampered = jwt.encode(
        jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]),
        "a-different-secret-entirely-and-long-enough-to-avoid-a-warning",
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered)
