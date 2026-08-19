"""Exercises app.main.signup() directly (same function FastAPI routes to) against the
db_session fixture, skipping the HTTP/TestClient layer -- app.db's module-level engine is
bound to whatever DATABASE_URL existed at import time, so going through a real request would
mean juggling two separate engines. Calling the route function directly keeps this testing
the real invite-consumption code path without that plumbing."""

from fastapi import BackgroundTasks, HTTPException
import pytest

from app.main import SignupRequest, signup
from app.models import Invite, User


def _make_invite(db_session, code="invite-1"):
    invite = Invite(code=code)
    db_session.add(invite)
    db_session.commit()
    return invite


def test_signup_consumes_invite(db_session):
    _make_invite(db_session, "invite-1")
    body = SignupRequest(email="new@example.com", password="hunter2hunter2", invite_code="invite-1")
    signup(body, BackgroundTasks(), db_session)

    invite = db_session.query(Invite).filter(Invite.code == "invite-1").one()
    assert invite.used_at is not None
    user = db_session.query(User).filter(User.email == "new@example.com").one()
    assert invite.used_by_user_id == user.id


def test_signup_rejects_already_used_invite(db_session):
    invite = _make_invite(db_session, "invite-1")
    body = SignupRequest(email="first@example.com", password="hunter2hunter2", invite_code="invite-1")
    signup(body, BackgroundTasks(), db_session)

    body2 = SignupRequest(email="second@example.com", password="hunter2hunter2", invite_code="invite-1")
    with pytest.raises(HTTPException) as exc_info:
        signup(body2, BackgroundTasks(), db_session)
    assert exc_info.value.status_code == 403
    # the first signup must be untouched by the second (rejected) attempt
    assert db_session.query(User).filter(User.email == "second@example.com").one_or_none() is None


def test_signup_rejects_unknown_invite_code(db_session):
    body = SignupRequest(email="new@example.com", password="hunter2hunter2", invite_code="does-not-exist")
    with pytest.raises(HTTPException) as exc_info:
        signup(body, BackgroundTasks(), db_session)
    assert exc_info.value.status_code == 403


def test_signup_rejects_duplicate_email(db_session):
    _make_invite(db_session, "invite-1")
    _make_invite(db_session, "invite-2")
    body = SignupRequest(email="dup@example.com", password="hunter2hunter2", invite_code="invite-1")
    signup(body, BackgroundTasks(), db_session)

    body2 = SignupRequest(email="dup@example.com", password="hunter2hunter2", invite_code="invite-2")
    with pytest.raises(HTTPException) as exc_info:
        signup(body2, BackgroundTasks(), db_session)
    assert exc_info.value.status_code == 409
