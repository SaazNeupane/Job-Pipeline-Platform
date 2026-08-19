"""Per-candidate generation/send failures inside _send_cold_emails are individually caught
and skipped (one bad candidate shouldn't sink the whole batch) -- which used to mean a
consistently bad cause (an expired/revoked Gemini key, say) never surfaced anywhere: every
candidate failed silently, contacts_found stayed >0 but sent stayed 0, indistinguishable from
"nothing worth sending today." generation_failures makes that visible."""

from dataclasses import dataclass
from types import SimpleNamespace

import pipeline.cold_email as cold_email

_FAKE_PROFILE = SimpleNamespace(cold_email=SimpleNamespace())


@dataclass
class _FakeContact:
    email: str = "hiring@acme.example"


@dataclass
class _FakePosting:
    title: str = "Software Engineer"
    company: str = "Acme Co"
    location: str = "Toronto, ON"

    def dedupe_key(self) -> str:
        return "greenhouse:1"


def _patch_collaborators(monkeypatch, *, send_raises: bool):
    monkeypatch.setattr(cold_email, "refresh_bounce_and_reply_status", lambda user: None)
    monkeypatch.setattr(cold_email, "compute_daily_cap", lambda user, cfg: 100)
    monkeypatch.setattr(cold_email, "get_cold_email_dedupe_keys", lambda user: set())
    monkeypatch.setattr(cold_email, "count_sent_today", lambda user: 0)
    monkeypatch.setattr(cold_email, "find_contact", lambda posting: _FakeContact())
    monkeypatch.setattr(cold_email, "record_cold_email", lambda user, fields: None)
    monkeypatch.setattr(cold_email, "record_cold_email_dedupe_backup", lambda key: None)

    def _generate(user, resume, posting, matched_terms):
        if send_raises:
            raise RuntimeError("401 Unauthorized: invalid API key")
        return "body text"

    monkeypatch.setattr(cold_email, "generate_cold_email_note", _generate)
    monkeypatch.setattr(cold_email, "send_cold_email", lambda user, to, subject, body: {"threadId": "t1"})


def test_generation_failure_is_counted_not_silently_dropped(monkeypatch):
    _patch_collaborators(monkeypatch, send_raises=True)
    candidates = [(_FakePosting(), ["python"], "it_tech", {})]

    result = cold_email._send_cold_emails("user-1", profile=_FAKE_PROFILE, candidates=candidates)

    assert result["generation_failures"] == 1
    assert result["results"] == []


def test_successful_send_reports_zero_failures(monkeypatch):
    _patch_collaborators(monkeypatch, send_raises=False)
    candidates = [(_FakePosting(), ["python"], "it_tech", {})]

    result = cold_email._send_cold_emails("user-1", profile=_FAKE_PROFILE, candidates=candidates)

    assert result["generation_failures"] == 0
    assert len(result["results"]) == 1
