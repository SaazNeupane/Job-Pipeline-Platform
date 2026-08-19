"""explain() must never call the Gemini-backed generate_fit_reason a second time for the
same posting -- once cached in Posting.fit_reason, that's the whole point (see
fit_reason.py's own docstring: this is a real API call, on-demand, and shouldn't fire twice
for the same posting)."""

from unittest.mock import patch

import app.routers.swipe as swipe_module


def test_explain_returns_cached_reason_without_regenerating():
    with patch("app.routers.swipe.get_posting", return_value={"fit_reason": "Already explained."}), \
         patch("app.routers.swipe.generate_fit_reason") as mock_generate:
        result = swipe_module.explain("some-key", user=type("U", (), {"id": "user-1"})())

    assert result == {"fit_reason": "Already explained."}
    mock_generate.assert_not_called()
