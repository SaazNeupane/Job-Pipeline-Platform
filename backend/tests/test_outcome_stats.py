import pytest

from app.models import User
from pipeline import postings_store as store


@pytest.fixture(autouse=True)
def _no_sheet_mirror(monkeypatch):
    monkeypatch.setattr(store, "_fire_mirror", lambda user, fn: None)


@pytest.fixture()
def user_id(db_session):
    user = User(email="outcomes@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    return user.id


def _applied_posting(user_id, key, lane, source, outcome=""):
    store.create_posting(user_id, "applied", {
        "posting_key": key, "lane": lane, "source": source, "company": "Acme",
        "application_status": "submitted", "outcome": outcome,
    })


def test_set_posting_outcome_updates_row(user_id):
    _applied_posting(user_id, "a", "it_tech", "greenhouse")
    result = store.set_posting_outcome(user_id, "a", "interview")
    assert result["outcome"] == "interview"
    assert result["outcome_updated_at"]


def test_set_posting_outcome_returns_none_for_unknown_key(user_id):
    assert store.set_posting_outcome(user_id, "missing", "interview") is None


def test_outcome_stats_only_counts_applied_postings(user_id):
    # queued/pending postings haven't been decided on yet -- shouldn't count toward the
    # applied-funnel denominator at all.
    store.create_posting(user_id, "queued", {"posting_key": "q1", "lane": "it_tech", "source": "greenhouse"})
    _applied_posting(user_id, "a1", "it_tech", "greenhouse", outcome="interview")

    stats = store.get_outcome_stats(user_id)
    assert stats["overall"]["applied"] == 1
    assert stats["overall"]["interview"] == 1


def test_outcome_stats_grouped_by_lane_and_source(user_id):
    _applied_posting(user_id, "a1", "it_tech", "greenhouse", outcome="interview")
    _applied_posting(user_id, "a2", "it_tech", "adzuna", outcome="")
    _applied_posting(user_id, "a3", "ops_supervisor", "greenhouse", outcome="rejected")

    stats = store.get_outcome_stats(user_id)

    assert stats["overall"]["applied"] == 3
    assert stats["overall"]["interview"] == 1
    assert stats["overall"]["rejected"] == 1

    assert stats["by_lane"]["it_tech"]["applied"] == 2
    assert stats["by_lane"]["it_tech"]["interview"] == 1
    assert stats["by_lane"]["ops_supervisor"]["applied"] == 1
    assert stats["by_lane"]["ops_supervisor"]["rejected"] == 1

    assert stats["by_source"]["greenhouse"]["applied"] == 2
    assert stats["by_source"]["adzuna"]["applied"] == 1
