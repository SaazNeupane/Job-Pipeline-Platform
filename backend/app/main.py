"""FastAPI entrypoint. Three groups of routes:
  - /api/auth/*      signup/login for the app account itself
  - /api/oauth/*      the per-user Google Sheets/Gmail/Drive connect flow
  - /api/internal/*   called only by the GitHub Actions scheduler workflow (shared-secret
                      header, not user auth) -- see .github/workflows/daily.yml
Wizard/dashboard/swipe endpoints (profile CRUD, sheet reads, swipe actions) are still to be
ported from the old webapp/app.py + webapp/wizard.py -- this file establishes the
auth/OAuth/scheduler skeleton the plan calls for first; the data-editing routes are the next
slice of work, not included in this pass.
"""

from __future__ import annotations

import os
import secrets as _secrets
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, hash_password, verify_password
from app.db import get_db
from app.models import User
from pipeline import config as pipeline_config
from pipeline import google_auth as pipeline_google_auth

app = FastAPI(title="Job Pipeline Platform API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

INTERNAL_SHARED_SECRET = os.environ["INTERNAL_SHARED_SECRET"]


@app.middleware("http")
async def bind_db_session_for_pipeline(request, call_next):
    """Every pipeline/* module reads the current DB session via a contextvar (see
    pipeline/config.py's module docstring) instead of an extra function parameter --
    this sets it once per request from the same session FastAPI's own Depends(get_db)
    would create, so route handlers that call into pipeline/* don't need to pass a
    session through manually."""
    db_gen = get_db()
    db: Session = next(db_gen)
    pipeline_config.set_session(db)
    try:
        response = await call_next(request)
    finally:
        pipeline_config.set_session(None)
        try:
            next(db_gen)
        except StopIteration:
            pass
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@app.post("/api/auth/signup", response_model=TokenResponse)
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(id=str(uuid.uuid4()), email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id))


@app.post("/api/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return TokenResponse(access_token=create_access_token(user.id))


@app.get("/api/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "email": user.email}


# ---------------------------------------------------------------------------
# Google OAuth connect (Sheets/Gmail/Drive scopes, separate from app login above)
# ---------------------------------------------------------------------------

# In-memory state->user_id map for the OAuth redirect round trip. Short-lived (a user
# completes consent within a couple minutes or restarts the flow) -- fine as in-process
# state even across Render's free-tier idle-sleep, since a sleep would drop an in-flight
# OAuth redirect anyway and the user just clicks "Connect Google" again.
_oauth_state: dict[str, str] = {}


@app.get("/api/oauth/google/start")
def google_oauth_start(user: User = Depends(get_current_user)):
    state = _secrets.token_urlsafe(24)
    _oauth_state[state] = user.id
    return {"authorization_url": pipeline_google_auth.build_authorization_url(state)}


@app.get("/api/oauth/google/callback")
def google_oauth_callback(code: str, state: str):
    user_id = _oauth_state.pop(state, None)
    if user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or expired OAuth state")
    credential = pipeline_google_auth.exchange_code_for_credential(user_id, code)
    return {"connected": True, "scopes": credential.scopes}


# ---------------------------------------------------------------------------
# Internal endpoints -- called by .github/workflows/daily.yml, not by real users.
# Shared-secret header auth (not JWT) since there's no logged-in user driving this.
# ---------------------------------------------------------------------------


def _require_internal_secret(x_internal_secret: str = Header(default="")):
    if not _secrets.compare_digest(x_internal_secret, INTERNAL_SHARED_SECRET):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad internal secret")


@app.get("/api/internal/active-users", dependencies=[Depends(_require_internal_secret)])
def active_users(db: Session = Depends(get_db)):
    users = db.query(User).filter(User.active.is_(True)).all()
    return {"user_ids": [u.id for u in users]}


@app.post("/api/internal/run/{user_id}", dependencies=[Depends(_require_internal_secret)])
def run_pipeline_for_user(user_id: str):
    """Wraps the old run_pipeline.py orchestrator for exactly one user. Deliberately not
    ported in this pass -- run_pipeline.run(user) needs the same treatment tailor_resume/
    cover_letter/etc. already got (copy as-is, since it only calls load_profile/load_secrets/
    search/filter/sheet_log, all of which already work against the DB-backed config via the
    contextvar). Left as a TODO marker rather than silently stubbed to succeed, so a cron
    call against this doesn't look like a real run before it is one."""
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, f"run_pipeline port pending for {user_id}")
