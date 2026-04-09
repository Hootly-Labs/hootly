"""Tests for JWT creation/decoding and password hashing."""
import pytest
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException

from services.auth_service import (
    JWT_ALGO,
    JWT_SECRET,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_differs_from_plaintext(self):
        assert hash_password("secret123") != "secret123"

    def test_verify_correct_password(self):
        hashed = hash_password("mypassword")
        assert verify_password("mypassword", hashed) is True

    def test_reject_wrong_password(self):
        hashed = hash_password("mypassword")
        assert verify_password("wrong", hashed) is False

    def test_bcrypt_salted_different_each_time(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2

    def test_verify_still_works_after_re_hashing(self):
        hashed = hash_password("pw")
        # Verify twice — should not mutate state
        assert verify_password("pw", hashed) is True
        assert verify_password("pw", hashed) is True

    def test_empty_password_hashes(self):
        # Empty string is technically valid to hash
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("notempty", hashed) is False


class TestJWT:
    def test_create_and_decode_roundtrip(self):
        token = create_token("user-abc-123")
        payload = decode_token(token)
        assert payload["sub"] == "user-abc-123"

    def test_different_users_get_different_tokens(self):
        t1 = create_token("user-1")
        t2 = create_token("user-2")
        assert t1 != t2

    def test_expired_token_raises_401(self):
        payload = {
            "sub": "user-123",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        expired = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
        with pytest.raises(HTTPException) as exc:
            decode_token(expired)
        assert exc.value.status_code == 401

    def test_invalid_token_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            decode_token("not.a.valid.jwt")
        assert exc.value.status_code == 401

    def test_empty_token_raises_401(self):
        with pytest.raises(HTTPException):
            decode_token("")

    def test_wrong_secret_raises_401(self):
        payload = {
            "sub": "user-123",
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
        }
        bad_token = jwt.encode(payload, "wrong-secret", algorithm=JWT_ALGO)
        with pytest.raises(HTTPException) as exc:
            decode_token(bad_token)
        assert exc.value.status_code == 401

    def test_tampered_signature_raises_401(self):
        token = create_token("user-123")
        parts = token.split(".")
        parts[-1] = parts[-1][:-4] + "XXXX"
        with pytest.raises(HTTPException):
            decode_token(".".join(parts))
