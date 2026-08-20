"""run_now()'s manual-run quota (PLAN_MANUAL_RUN_LIMITS, User.manual_run_count/_period) --
counts every user-clicked run (full or scoped) toward a monthly cap by plan, separate from
the same-day guard covered in test_run_now_race.py. Calls run_now() directly against the
db_session fixture, same pattern as test_invite_signup.py, so a real HTTPException with the
right status/detail is exercised without the TestClient/engine-juggling layer."""

from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException
import pytest

from app.main import RunNowRequest, run_now
from app.models import Profile, User


def _make_user(db_session, plan="free"):
    user = User(email=f"{plan}@example.com", password_hash="x", plan=plan)
    db_session.add(user)
    db_session.flush()
    db_session.add(Profile(user_id=user.id))
    db_session.commit()
    return user


def test_free_plan_blocked_after_limit(db_session):
    user = _make_user(db_session, plan="free")
    with patch("pipeline.run_pipeline.run"):
        for _ in range(3):
            run_now(BackgroundTasks(), RunNowRequest(cold_email_only=True), db_session, user)

    with pytest.raises(HTTPException) as exc_info:
        run_now(BackgroundTasks(), RunNowRequest(cold_email_only=True), db_session, user)
    assert exc_info.value.status_code == 429

    db_session.refresh(user)
    assert user.manual_run_count == 3


def test_paid_plan_gets_higher_limit(db_session):
    user = _make_user(db_session, plan="paid")
    with patch("pipeline.run_pipeline.run"):
        for _ in range(50):
            run_now(BackgroundTasks(), RunNowRequest(cold_email_only=True), db_session, user)

    with pytest.raises(HTTPException) as exc_info:
        run_now(BackgroundTasks(), RunNowRequest(cold_email_only=True), db_session, user)
    assert exc_info.value.status_code == 429


def test_quota_not_consumed_when_same_day_guard_blocks(db_session, monkeypatch):
    """A full (unscoped) run-now that 409s on the same-day guard shouldn't burn a quota
    slot -- the run never actually queued."""
    user = _make_user(db_session, plan="free")
    monkeypatch.setattr(
        "pipeline.postings_store.get_daily_summaries",
        lambda uid: [{"date": __import__("app.time_utils", fromlist=["utcnow"]).utcnow().date().isoformat()}],
    )

    with pytest.raises(HTTPException) as exc_info:
        run_now(BackgroundTasks(), RunNowRequest(), db_session, user)
    assert exc_info.value.status_code == 409

    db_session.refresh(user)
    assert user.manual_run_count == 0
