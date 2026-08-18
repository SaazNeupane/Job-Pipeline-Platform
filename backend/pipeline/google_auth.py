"""DB-backed replacement for the old file-based pipeline/google_auth.py. Same public
functions/signatures as the original (get_sheets_service(user), get_gmail_service(user),
get_drive_service(user), send_email(user, ...)) so sheet_log.py, cold_email.py,
drive_storage.py, daily_report.py all work completely unmodified -- only where the refresh
token comes from changed.

Biggest real change from the original: the OAuth *grant* itself. The old version used an
installed-app flow (one Desktop OAuth client, `flow.run_local_server()`, one refresh token
per user written to a local secrets.env). That doesn't work for a hosted multi-tenant app --
there's no local browser/port to run a server on for a stranger's signup. This version uses
a real web OAuth flow: one shared "Web application" Google Cloud OAuth client (client id/
secret from env vars, not per-user), a redirect URI on the hosted domain, and each user's own
consent grant produces their own refresh token, stored Fernet-encrypted in the
oauth_credentials table (see app/models.py).

Requesting gmail.send/drive.file for arbitrary third-party accounts requires Google's OAuth
app verification before this can go out to real open signup -- see the plan doc, this is a
one-time external process, not something this module can route around.
"""

from __future__ import annotations

import base64
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.crypto import decrypt, encrypt
from app.models import OAuthCredential
from pipeline.config import _require_session

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "")

_CLIENT_CONFIG = {
    "web": {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [GOOGLE_REDIRECT_URI],
    }
}

# Per-process caches, same reasoning as the original: avoid a redundant token-endpoint
# round trip on every single sheet_log.py/cold_email.py call within one process.
_credentials_cache: dict[str, Credentials] = {}
_service_cache: dict[tuple[str, str], object] = {}

# googleapiclient services here wrap an httplib2.Http connection, which is not thread-safe --
# two threads doing concurrent I/O through the same cached service (keyed per user, shared
# across requests) corrupts the native heap (crashed the process with SIGSEGV in production,
# see postings_store.py's _MIRROR_EXECUTOR for the first occurrence of this bug). Any
# background thread that ends up calling into this module must go through this single-worker
# executor instead of spawning its own raw thread.
from concurrent.futures import ThreadPoolExecutor

BACKGROUND_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="google-api-bg")


def build_authorization_url(state: str) -> tuple[str, str]:
    """Step 1 of the web OAuth flow -- webapp's "Connect Google" button redirects here.
    Returns (authorization_url, code_verifier) -- the PKCE verifier the Flow object just
    generated internally, which the caller must hand back to exchange_code_for_credential
    in step 2 since that runs in a separate request against a brand new Flow object."""
    flow = Flow.from_client_config(_CLIENT_CONFIG, scopes=SCOPES, redirect_uri=GOOGLE_REDIRECT_URI)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # forces a refresh_token to be returned even on a repeat consent
        state=state,
    )
    return auth_url, flow.code_verifier


def exchange_code_for_credential(user_id: str, code: str, code_verifier: str) -> OAuthCredential:
    """Step 2 -- Google redirects back to GOOGLE_OAUTH_REDIRECT_URI with ?code=...&state=...
    The route handler in app/main.py calls this with that code. Stores (or replaces) the
    encrypted refresh token for this user and returns the granted email for display."""
    db = _require_session()
    flow = Flow.from_client_config(_CLIENT_CONFIG, scopes=SCOPES, redirect_uri=GOOGLE_REDIRECT_URI)
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    creds = flow.credentials
    if not creds.refresh_token:
        raise RuntimeError(
            "Google did not return a refresh_token -- this happens on a repeat consent "
            "without prompt=consent, or if access_type wasn't offline. Check "
            "build_authorization_url's params."
        )

    # Fetch the granted account's own email once, at connect time -- finalize() needs it
    # for gmail_address/report_email, and the dashboard shows it so a user can tell which
    # Google account is connected.
    granted_email = build("gmail", "v1", credentials=creds).users().getProfile(userId="me").execute()["emailAddress"]

    existing = db.query(OAuthCredential).filter(
        OAuthCredential.user_id == user_id, OAuthCredential.provider == "google"
    ).one_or_none()
    if existing is None:
        existing = OAuthCredential(user_id=user_id, provider="google")
        db.add(existing)
    existing.refresh_token_encrypted = encrypt(creds.refresh_token)
    existing.scopes = " ".join(creds.scopes or SCOPES)
    existing.granted_email = granted_email
    db.commit()

    _credentials_cache.pop(user_id, None)
    for key in [k for k in _service_cache if k[0] == user_id]:
        _service_cache.pop(key, None)
    return existing


def get_credentials(user: str) -> Credentials:
    creds = _credentials_cache.get(user)
    if creds is None:
        db = _require_session()
        row = db.query(OAuthCredential).filter(
            OAuthCredential.user_id == user, OAuthCredential.provider == "google"
        ).one_or_none()
        if row is None:
            raise RuntimeError(
                f"No Google OAuth credential stored for user {user!r} -- they need to "
                f"complete the 'Connect Google' step in the webapp first."
            )
        creds = Credentials(
            token=None,
            refresh_token=decrypt(row.refresh_token_encrypted),
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=SCOPES,
        )
        _credentials_cache[user] = creds
    if not creds.valid:
        creds.refresh(Request())
    return creds


def _get_service(user: str, api_name: str, api_version: str):
    creds = get_credentials(user)
    cache_key = (user, api_name)
    if cache_key not in _service_cache:
        _service_cache[cache_key] = build(api_name, api_version, credentials=creds)
    return _service_cache[cache_key]


def get_sheets_service(user: str):
    return _get_service(user, "sheets", "v4")


def get_gmail_service(user: str):
    return _get_service(user, "gmail", "v1")


def get_drive_service(user: str):
    return _get_service(user, "drive", "v3")


def send_email(user: str, to_email: str, subject: str, body: str, html_body: str | None = None) -> dict:
    gmail = get_gmail_service(user)
    if html_body:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
    else:
        msg = MIMEText(body)
    msg["to"] = to_email
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
