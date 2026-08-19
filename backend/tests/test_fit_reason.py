"""fit_reason.generate_fit_reason mirrors cover_letter.py's own prompt-building pattern --
tests here guard the contract (raises without a Gemini key, calls generate_with_gemini with
the resume/posting facts) without making a real API call. The route-level caching behavior
(app/routers/swipe.py's explain()) is covered separately in test_swipe_explain_cache.py."""

from dataclasses import dataclass
from unittest.mock import patch

import pytest

from pipeline.fit_reason import generate_fit_reason


@dataclass
class _FakePosting:
    company: str = "Acme Co"
    title: str = "Software Engineer"
    description_text: str = "Build things with Python and React."


_RESUME = {
    "name": "Jane Doe",
    "experience": {"relevant": [{"title": "Backend Dev", "company": "Old Co", "dates": "2022-2025", "bullets": ["Built APIs"]}]},
    "skills": {"languages": ["Python"]},
}


def test_raises_without_gemini_key(monkeypatch):
    monkeypatch.setattr("pipeline.fit_reason.load_secrets", lambda user: {})
    with pytest.raises(RuntimeError):
        generate_fit_reason("user-1", _RESUME, _FakePosting(), ["python"])


def test_calls_generate_with_gemini_with_expected_args(monkeypatch):
    monkeypatch.setattr("pipeline.fit_reason.load_secrets", lambda user: {"GEMINI_API_KEY": "test-key"})
    with patch("pipeline.fit_reason.generate_with_gemini", return_value="Great fit because of Python.") as mock_gen:
        result = generate_fit_reason("user-1", _RESUME, _FakePosting(), ["python"])

    assert result == "Great fit because of Python."
    args, kwargs = mock_gen.call_args
    assert args[0] == "test-key"
    assert "Jane Doe" in args[3]
    assert "Acme Co" in args[3]
    assert kwargs["max_output_tokens"] == 2048
