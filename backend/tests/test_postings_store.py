"""Status-transition logic in pipeline/postings_store.py, against real SQLite (not mocked)
-- Sheet-mirror writes are monkeypatched to no-ops since they need a real Google credential
and aren't what's under test here (the Postgres source-of-truth logic is)."""

import pytest

from app.models import User
from pipeline import postings_store as store


@pytest.fixture(autouse=True)
def _no_sheet_mirror(monkeypatch):
    monkeypatch.setattr(store, "_fire_mirror", lambda user, fn: None)


@pytest.fixture()
def user_id(db_session):
    user = User(email="test@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    return user.id


def _posting_fields(**overrides):
    fields = dict(
        posting_key="greenhouse:123",
        date="2026-08-18",
        lane="it_tech",
        company="Acme Co",
        role="Software Engineer",
        source="greenhouse",
        location="Toronto, ON",
    )
    fields.update(overrides)
    return fields


def test_create_posting_defaults_to_queued_status(user_id):
    result = store.create_posting(user_id, "queued", _posting_fields())
    assert result["status"] == "queued"
    assert result["posting_key"] == "greenhouse:123"


def test_transition_posting_moves_status_and_records_history(user_id):
    store.create_posting(user_id, "queued", _posting_fields())
    result = store.transition_posting(user_id, "greenhouse:123", "pending", {"reason_held": "manual review"})
    assert result["status"] == "pending"
    assert result["reason_held"] == "manual review"


def test_transition_posting_returns_none_for_unknown_key(user_id):
    assert store.transition_posting(user_id, "does-not-exist", "pending") is None


def test_dismissed_posting_no_longer_appears_in_queued_list(user_id):
    store.create_posting(user_id, "queued", _posting_fields())
    store.transition_posting(user_id, "greenhouse:123", "dismissed")
    assert store.get_postings(user_id, status="queued") == []
    dismissed = store.get_postings(user_id, status="dismissed")
    assert len(dismissed) == 1


def test_get_existing_dedupe_keys_includes_dismissed(user_id):
    # This is the regression class the audit called out by name: a dedupe gap here silently
    # re-surfaces a job the user already dismissed, and nobody notices for weeks.
    store.create_posting(user_id, "queued", _posting_fields())
    store.transition_posting(user_id, "greenhouse:123", "dismissed")
    keys = store.get_existing_dedupe_keys(user_id)
    assert "greenhouse:123" in keys


def test_get_existing_fingerprints_matches_reindexed_posting(user_id):
    from pipeline.filter import posting_fingerprint

    store.create_posting(user_id, "queued", _posting_fields())
    store.transition_posting(user_id, "greenhouse:123", "dismissed")
    fps = store.get_existing_fingerprints(user_id)
    expected = posting_fingerprint("greenhouse", "Acme Co", "Software Engineer", "Toronto, ON")
    assert expected in fps


def test_dismiss_postings_bulk_only_touches_pending(user_id):
    store.create_posting(user_id, "queued", _posting_fields(posting_key="a"))
    store.create_posting(user_id, "pending", _posting_fields(posting_key="b"))
    count = store.dismiss_postings_bulk(user_id, ["a", "b"])
    assert count == 1
    assert store.get_posting(user_id, "a")["status"] == "queued"
    assert store.get_posting(user_id, "b")["status"] == "dismissed"
