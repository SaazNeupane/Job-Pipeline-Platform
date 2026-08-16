"""Platform transactional email (signup verification, later maybe password reset) --
sent from the app's own identity via Brevo's API, not from any user's connected Gmail
(that's a completely separate thing, see pipeline/google_auth.py/cold_email.py, sent as
that specific user, for cold outreach). Needs BREVO_API_KEY and BREVO_FROM_EMAIL in the
environment; if either is missing this logs a warning and no-ops instead of raising, so a
local dev environment without a Brevo key configured yet doesn't break signup."""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
BREVO_FROM_EMAIL = os.environ.get("BREVO_FROM_EMAIL", "")
BREVO_FROM_NAME = os.environ.get("BREVO_FROM_NAME", "Crond")

_API_URL = "https://api.brevo.com/v3/smtp/email"
_REQUEST_TIMEOUT_SECONDS = 15


def send_email(to_email: str, subject: str, html: str) -> bool:
    """Returns True if Brevo accepted the send, False if skipped (no key configured) or
    the request itself failed -- callers treat this as best-effort, never let a failed
    transactional email block the thing that triggered it (e.g. signup)."""
    if not BREVO_API_KEY or not BREVO_FROM_EMAIL:
        logger.warning("BREVO_API_KEY/BREVO_FROM_EMAIL not set -- skipping email to %r (%r)", to_email, subject)
        return False

    try:
        resp = requests.post(
            _API_URL,
            headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json", "Accept": "application/json"},
            json={
                "sender": {"name": BREVO_FROM_NAME, "email": BREVO_FROM_EMAIL},
                "to": [{"email": to_email}],
                "subject": subject,
                "htmlContent": html,
            },
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return True
    except Exception:  # noqa: BLE001 -- logged, never raised, see module docstring
        logger.exception("Brevo send failed for %r (%r)", to_email, subject)
        return False
