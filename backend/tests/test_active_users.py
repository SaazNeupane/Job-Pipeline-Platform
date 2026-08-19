"""GitHub Actions cron runs are best-effort and routinely fire late or get dropped -- an
exact-hour match on active_users() means a trigger landing at 15:05 instead of 14:30 would
silently skip every 14:00 user for the whole day. Regression coverage for the fix:
run_hour_utc <= now_hour (hour has passed) AND no DailySummary row for today yet."""

from datetime import datetime
from unittest.mock import patch

from app.main import active_users
from app.models import DailySummary, Profile, User


def _make_user(db_session, run_hour_utc, email="user@example.com"):
    user = User(email=email, password_hash="x")
    db_session.add(user)
    db_session.flush()
    db_session.add(Profile(user_id=user.id, run_hour_utc=run_hour_utc))
    db_session.commit()
    return user


def test_catches_up_a_missed_earlier_hour(db_session):
    # scheduled for 14:00 UTC, cron didn't fire until 15:00 -- still due since it hasn't run.
    user = _make_user(db_session, run_hour_utc=14)
    with patch("app.main.utcnow") as mock_utcnow:
        mock_utcnow.return_value = datetime(2026, 8, 18, 15, 0)
        result = active_users(db_session)
    assert user.id in result["user_ids"]


def test_excludes_user_whose_hour_hasnt_arrived_yet(db_session):
    user = _make_user(db_session, run_hour_utc=20)
    with patch("app.main.utcnow") as mock_utcnow:
        mock_utcnow.return_value = datetime(2026, 8, 18, 15, 0)
        result = active_users(db_session)
    assert user.id not in result["user_ids"]


def test_excludes_user_already_run_today(db_session):
    user = _make_user(db_session, run_hour_utc=14)
    db_session.add(DailySummary(user_id=user.id, date="2026-08-18"))
    db_session.commit()
    with patch("app.main.utcnow") as mock_utcnow:
        mock_utcnow.return_value = datetime(2026, 8, 18, 16, 0)
        result = active_users(db_session)
    assert user.id not in result["user_ids"]


def test_user_mid_wizard_with_no_profile_is_excluded(db_session):
    user = User(email="nowizard@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    with patch("app.main.utcnow") as mock_utcnow:
        mock_utcnow.return_value = datetime(2026, 8, 18, 16, 0)
        result = active_users(db_session)
    assert user.id not in result["user_ids"]
