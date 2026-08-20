"""run_pipeline.run()'s plan gating (PLAN_ALLOWED_SOURCES/PLAN_APPLY_DAILY_CAP_LIMITS) --
a free-plan lane requesting a paid-only source (e.g. workday) must have that source
stripped before search fan-out (so the paid-only search_* function is never even called)
and get a visible error explaining why, and apply_daily_cap must be clamped to the plan's
ceiling regardless of what's stored on the profile row."""

from unittest.mock import patch

from app.models import Profile as ProfileRow
from app.models import User
from pipeline.run_pipeline import run


def _lane(sources):
    return {
        "name": "main",
        "resume": "resume_main.json",
        "keywords": ["test"],
        "sources": sources,
    }


def _make_user_and_profile(db_session, plan, apply_daily_cap, sources):
    user = User(email=f"{plan}-gating@example.com", password_hash="x", plan=plan)
    db_session.add(user)
    db_session.flush()
    db_session.add(ProfileRow(
        user_id=user.id,
        apply_daily_cap=apply_daily_cap,
        lanes_json=[_lane(sources)],
        cold_email_json={"daily_cap_week1": 0, "daily_cap_week3plus": 0, "ramp_start_date": "2026-01-01"},
        applicant_json={"first_name": "T", "last_name": "User", "country": "us"},
    ))
    db_session.commit()
    return user


@patch("pipeline.run_pipeline.send_daily_report")
@patch("pipeline.run_pipeline.build_daily_summary", return_value={"errors": []})
@patch("pipeline.run_pipeline.cleanup_old_files", return_value=0)
@patch("pipeline.run_pipeline.run_cold_email_pipeline", return_value=None)
@patch("pipeline.run_pipeline.get_existing_fingerprints", return_value=set())
@patch("pipeline.run_pipeline.get_existing_dedupe_keys", return_value=set())
@patch("pipeline.run_pipeline.filter_postings", return_value=[])
@patch("pipeline.run_pipeline.search_greenhouse", return_value=[])
@patch("pipeline.run_pipeline.search_workday")
def test_free_plan_strips_paid_only_source_and_caps_queue(
    mock_workday, mock_greenhouse, mock_filter, mock_dedupe_keys, mock_fingerprints,
    mock_cold_email, mock_cleanup, mock_summary, mock_report, db_session,
):
    user = _make_user_and_profile(db_session, "free", apply_daily_cap=999, sources=["greenhouse", "workday"])

    run(user.id)

    mock_workday.assert_not_called()  # paid-only source never reached search fan-out
    mock_greenhouse.assert_called_once()  # free-allowed source still ran

    errors_passed = mock_summary.call_args.args[2]  # build_daily_summary(user, None, errors, ...)
    assert any("workday" in e and "paid plan" in e for e in errors_passed)


@patch("pipeline.run_pipeline.send_daily_report")
@patch("pipeline.run_pipeline.build_daily_summary", return_value={"errors": []})
@patch("pipeline.run_pipeline.cleanup_old_files", return_value=0)
@patch("pipeline.run_pipeline.run_cold_email_pipeline", return_value=None)
@patch("pipeline.run_pipeline.get_existing_fingerprints", return_value=set())
@patch("pipeline.run_pipeline.get_existing_dedupe_keys", return_value=set())
@patch("pipeline.run_pipeline.filter_postings", return_value=[])
@patch("pipeline.run_pipeline.search_greenhouse", return_value=[])
def test_free_plan_apply_daily_cap_clamped(
    mock_greenhouse, mock_filter, mock_dedupe_keys, mock_fingerprints,
    mock_cold_email, mock_cleanup, mock_summary, mock_report, db_session,
):
    """run() clamps the in-memory Profile.apply_daily_cap to the plan's ceiling before
    using it for the swipe-queue slice -- load_profile is called once inside run() and
    the same Profile object it returns is what gets clamped, so wrapping it here and
    keeping a handle to the returned object lets the test observe the clamp directly."""
    user = _make_user_and_profile(db_session, "free", apply_daily_cap=999, sources=["greenhouse"])

    from pipeline import run_pipeline as run_pipeline_module

    real_load_profile = run_pipeline_module.load_profile
    captured_profile = {}

    def _capture_and_load(uid):
        profile = real_load_profile(uid)
        captured_profile["profile"] = profile
        return profile

    with patch("pipeline.run_pipeline.load_profile", side_effect=_capture_and_load):
        run(user.id)

    assert captured_profile["profile"].apply_daily_cap == 15  # clamped from 999 to free's ceiling
