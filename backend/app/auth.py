"""Minimal email/password session auth for the app account itself -- separate from the
per-user Google OAuth grant in pipeline/google_auth.py, which authorizes Sheets/Gmail/Drive
access, not login to this app."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_MINUTES = 60 * 24 * 7  # one week

bearer_scheme = HTTPBearer()

# bcrypt itself caps input at 72 bytes -- truncate deliberately up front rather than let a
# long password silently only have its first 72 bytes matter (bcrypt's own behavior either
# way, this just makes it explicit rather than relying on library internals).
_MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    truncated = password.encode("utf-8")[:_MAX_PASSWORD_BYTES]
    return bcrypt.hashpw(truncated, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    truncated = password.encode("utf-8")[:_MAX_PASSWORD_BYTES]
    return bcrypt.checkpw(truncated, password_hash.encode("utf-8"))


def create_access_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRES_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


_VERIFY_EMAIL_EXPIRES_HOURS = 24


def create_email_verification_token(user_id: str) -> str:
    """A separate token type from create_access_token, not a login session -- purpose
    claim keeps a verification link from working as a login token if it leaked (e.g. an
    email client that prefetches links), and vice versa."""
    payload = {
        "sub": user_id,
        "purpose": "verify_email",
        "exp": datetime.now(timezone.utc) + timedelta(hours=_VERIFY_EMAIL_EXPIRES_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_email_verification_token(token: str) -> str:
    """Returns the user id if valid, raises HTTPException otherwise."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This verification link is invalid or expired.")
    if payload.get("purpose") != "verify_email":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This verification link is invalid or expired.")
    return payload["sub"]


_RESET_PASSWORD_EXPIRES_MINUTES = 30


def create_password_reset_token(user_id: str, password_hash: str) -> str:
    """Purpose-scoped like create_email_verification_token. Bakes in a hash of the
    current password_hash so any token issued before a successful reset (or a second
    concurrent reset request) is invalidated the moment the password actually changes,
    without needing a separate revocation table -- once password_hash changes, no
    previously issued token's embedded fingerprint matches anymore."""
    payload = {
        "sub": user_id,
        "purpose": "reset_password",
        "pwfp": password_hash[-16:],
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_RESET_PASSWORD_EXPIRES_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_password_reset_token(token: str, current_password_hash: str) -> str:
    """Returns the user id if valid, raises HTTPException otherwise."""
    invalid = HTTPException(status.HTTP_400_BAD_REQUEST, "This reset link is invalid or expired.")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise invalid
    if payload.get("purpose") != "reset_password":
        raise invalid
    if payload.get("pwfp") != current_password_hash[-16:]:
        raise invalid
    return payload["sub"]


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, payload["sub"])
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user
