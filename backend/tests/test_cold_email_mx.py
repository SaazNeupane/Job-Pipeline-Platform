"""Real found emails still bounce on a dead/typo'd domain -- _domain_accepts_mail() gates
sending on a real MX lookup (never on a guessed address, see cold_email.py's own docstring
on why guessing is banned). A definitive DNS negative should exclude the candidate; a lookup
error/timeout should fail open rather than drop a real contact over a network hiccup."""

from dataclasses import dataclass

import dns.exception
import dns.resolver
import pytest

import pipeline.cold_email as cold_email


@pytest.fixture(autouse=True)
def _clear_mx_cache():
    cold_email._mx_cache.clear()
    yield
    cold_email._mx_cache.clear()


def test_domain_with_mx_records_accepted(monkeypatch):
    monkeypatch.setattr(dns.resolver, "resolve", lambda domain, kind, lifetime: ["mx1.example.com"])
    assert cold_email._domain_accepts_mail("acme.example") is True


def test_domain_with_no_mx_rejected(monkeypatch):
    def _raise(domain, kind, lifetime):
        raise dns.resolver.NXDOMAIN()

    monkeypatch.setattr(dns.resolver, "resolve", _raise)
    assert cold_email._domain_accepts_mail("does-not-exist.invalid") is False


def test_dns_timeout_fails_open(monkeypatch):
    def _raise(domain, kind, lifetime):
        raise dns.exception.Timeout()

    monkeypatch.setattr(dns.resolver, "resolve", _raise)
    assert cold_email._domain_accepts_mail("flaky-dns.example") is True


def test_lookup_result_is_cached(monkeypatch):
    calls = []

    def _resolve(domain, kind, lifetime):
        calls.append(domain)
        return ["mx1.example.com"]

    monkeypatch.setattr(dns.resolver, "resolve", _resolve)
    cold_email._domain_accepts_mail("acme.example")
    cold_email._domain_accepts_mail("acme.example")
    assert calls == ["acme.example"]


@dataclass
class _FakeContact:
    email: str


@dataclass
class _FakePosting:
    title: str = "Software Engineer"
    company: str = "Acme Co"
    location: str = "Toronto, ON"

    def dedupe_key(self) -> str:
        return "greenhouse:1"


def test_send_cold_emails_skips_contact_with_no_mx(monkeypatch):
    from types import SimpleNamespace

    fake_profile = SimpleNamespace(cold_email=SimpleNamespace())
    monkeypatch.setattr(cold_email, "refresh_bounce_and_reply_status", lambda user: None)
    monkeypatch.setattr(cold_email, "compute_daily_cap", lambda user, cfg: 100)
    monkeypatch.setattr(cold_email, "get_cold_email_dedupe_keys", lambda user: set())
    monkeypatch.setattr(cold_email, "count_sent_today", lambda user: 0)
    monkeypatch.setattr(cold_email, "find_contact", lambda posting: _FakeContact(email="hiring@dead-domain.invalid"))
    monkeypatch.setattr(cold_email, "_domain_accepts_mail", lambda domain: False)

    candidates = [(_FakePosting(), ["python"], "it_tech", {})]
    result = cold_email._send_cold_emails("user-1", profile=fake_profile, candidates=candidates)

    assert result["results"] == []
    assert result["generation_failures"] == 0  # skipped before ever attempting generation/send
