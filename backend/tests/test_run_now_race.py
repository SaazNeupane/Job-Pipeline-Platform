"""Two quick /api/run-now clicks used to both pass the same-day check-then-act guard in the
route handler and both get submitted before either finished writing its DailySummary row.
The real fix is that _run_pipeline_worker only ever runs on a per-user single-worker
executor (see google_auth.submit_for_user) -- this covers the guard itself: given a
DailySummary row already exists for today, the worker must skip without calling run()."""

from unittest.mock import patch

import app.main as main_module
from app.models import Profile, User


def test_worker_skips_full_run_if_already_ran_today(db_session, monkeypatch):
    user = User(email="race@example.com", password_hash="x")
    db_session.add(user)
    db_session.flush()
    db_session.add(Profile(user_id=user.id))
    db_session.commit()

    monkeypatch.setattr(main_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(
        "pipeline.postings_store.get_daily_summaries",
        lambda uid: [{"date": main_module.utcnow().date().isoformat()}],
    )

    with patch("pipeline.run_pipeline.run") as mock_run:
        main_module._run_pipeline_worker(user.id, None, None, False)

    mock_run.assert_not_called()


def test_worker_runs_when_no_summary_exists_yet(db_session, monkeypatch):
    user = User(email="norace@example.com", password_hash="x")
    db_session.add(user)
    db_session.flush()
    db_session.add(Profile(user_id=user.id))
    db_session.commit()

    monkeypatch.setattr(main_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr("pipeline.postings_store.get_daily_summaries", lambda uid: [])

    with patch("pipeline.run_pipeline.run") as mock_run:
        main_module._run_pipeline_worker(user.id, None, None, False)

    mock_run.assert_called_once()
