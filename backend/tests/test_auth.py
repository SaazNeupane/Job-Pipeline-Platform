import pytest

from app.auth import (
    create_password_reset_token,
    decode_password_reset_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_roundtrip():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h)


def test_verify_rejects_wrong_password():
    h = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", h)


def test_hash_truncates_at_72_bytes_like_bcrypt():
    # bcrypt itself caps input at 72 bytes -- two passwords that only differ after byte 72
    # must hash/verify identically, since hash_password truncates explicitly up front.
    base = "a" * 72
    h = hash_password(base + "tail-that-should-be-ignored")
    assert verify_password(base + "a-different-tail-entirely", h)


def test_password_reset_token_roundtrip():
    token = create_password_reset_token("user-1", "hash-abc")
    assert decode_password_reset_token(token, "hash-abc") == "user-1"


def test_password_reset_token_invalidated_after_password_change():
    # Token embeds a fingerprint of the password hash at issue time -- once the real hash
    # changes (a successful reset, or a second concurrent reset), the old token must stop
    # working even though it hasn't expired yet.
    token = create_password_reset_token("user-1", "hash-abc")
    with pytest.raises(Exception):
        decode_password_reset_token(token, "hash-xyz-now-different")


def test_password_reset_token_rejects_garbage():
    with pytest.raises(Exception):
        decode_password_reset_token("not-a-real-token", "hash-abc")
