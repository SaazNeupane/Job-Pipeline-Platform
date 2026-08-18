"""FastAPI entrypoint. Route groups:
  - /api/auth/*      signup/login for the app account itself
  - /api/oauth/*      the per-user Google Sheets/Gmail/Drive connect flow
  - /api/wizard/*     setup wizard (app/routers/wizard.py)
  - /api/dashboard/*  dashboard (app/routers/dashboard.py)
  - /api/swipe/*      swipe queue (app/routers/swipe.py)
  - /api/internal/*   called only by the GitHub Actions scheduler workflow (shared-secret
                      header, not user auth) -- see .github/workflows/daily.yml
"""

from __future__ import annotations

import logging
import os
import secrets as _secrets
import uuid

from datetime import date, datetime
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from google.auth.exceptions import RefreshError
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse

from app.auth import create_access_token, get_current_user, hash_password, verify_password
from app.db import SessionLocal, get_db
from app.models import Invite, Profile, User
from app.routers import dashboard as dashboard_router
from app.routers import swipe as swipe_router
from app.routers import wizard as wizard_router
from pipeline import config as pipeline_config
from pipeline import google_auth as pipeline_google_auth

# No handler was configured before this -- logging.exception() calls (e.g. the daily-run
# background task, the OAuth callback) fell back to Python's default "last resort" stderr
# handler, so a traceback only existed in whatever terminal ran uvicorn. Gone the moment
# that terminal's scrolled past or closed. File handler here keeps it past that.
_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(_LOG_DIR / "app.log", encoding="utf-8")],
)

app = FastAPI(title="Job Pipeline Platform API")
app.include_router(wizard_router.router)
app.include_router(dashboard_router.router)
app.include_router(swipe_router.router)


@app.exception_handler(RefreshError)
def google_reauth_handler(request: Request, exc: RefreshError):
    """Any route that touches Sheets/Gmail/Drive can hit this if the stored refresh token
    expired or was revoked -- same distinct code the old webapp's _handle_google_reauth
    decorator returned, now handled globally instead of per-route."""
    return JSONResponse(
        status_code=401,
        content={"error": "Google connection expired. Reconnect from the dashboard.", "code": "google_reauth_required"},
    )


@app.exception_handler(Exception)
async def log_unhandled_exception(request: Request, exc: Exception):
    """Without this, an unhandled route exception only ever reaches uvicorn's own
    "uvicorn.error" logger, which is configured with propagate=False -- it prints to
    whatever terminal ran uvicorn and never reaches the file handler set up above. Log it
    through our own logger (not subject to that) before falling back to Starlette's
    default 500 response."""
    logging.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})

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
    this opens one session per request and sets it once, so route handlers that call into
    pipeline/* don't need to pass a session through manually. Stashed on request.state.db
    too, so get_db()'s own Depends(get_db) reuses this same session instead of opening a
    second Postgres connection for the same request (see app/db.py's get_db)."""
    db: Session = SessionLocal()
    request.state.db = db
    pipeline_config.set_session(db)
    try:
        response = await call_next(request)
    finally:
        pipeline_config.set_session(None)
        db.close()
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
    invite_code: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _send_verification_email(user_id: str, email: str) -> None:
    from app.auth import create_email_verification_token
    from pipeline.email_send import send_email

    backend_url = os.environ.get("BACKEND_PUBLIC_URL", "http://localhost:8000")
    token = create_email_verification_token(user_id)
    link = f"{backend_url}/api/auth/verify-email?token={token}"
    send_email(
        email,
        "Verify your email",
        f'<p>Confirm this is your email address to finish setting up your account.</p>'
        f'<p><a href="{link}">Verify your email</a></p>'
        f'<p>This link expires in 24 hours.</p>',
    )


@app.post("/api/auth/signup", response_model=TokenResponse)
def signup(body: SignupRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    invite = db.query(Invite).filter(Invite.code == body.invite_code).one_or_none()
    if invite is None or invite.used_at is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid or already-used invite code")
    if db.query(User).filter(User.email == body.email).one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(id=str(uuid.uuid4()), email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()  # user row must exist before invite's FK update below
    invite.used_at = datetime.utcnow()
    invite.used_by_user_id = user.id
    db.commit()
    # Best-effort, never blocks signup -- see pipeline/email_send.py's own no-op-if-
    # unconfigured behavior for the case where BREVO_API_KEY isn't set at all yet.
    background_tasks.add_task(_send_verification_email, user.id, user.email)
    return TokenResponse(access_token=create_access_token(user.id))


@app.get("/api/auth/verify-email")
def verify_email(token: str, db: Session = Depends(get_db)):
    from app.auth import decode_email_verification_token

    frontend_origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
    try:
        user_id = decode_email_verification_token(token)
    except HTTPException:
        return RedirectResponse(f"{frontend_origin}/dashboard?verify=expired")
    user = db.get(User, user_id)
    if user is None:
        return RedirectResponse(f"{frontend_origin}/dashboard?verify=expired")
    user.email_verified = True
    db.commit()
    return RedirectResponse(f"{frontend_origin}/dashboard?verify=success")


@app.post("/api/auth/resend-verification")
def resend_verification(background_tasks: BackgroundTasks, user: User = Depends(get_current_user)):
    if user.email_verified:
        return {"status": "already_verified"}
    background_tasks.add_task(_send_verification_email, user.id, user.email)
    return {"status": "sent"}


@app.post("/api/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return TokenResponse(access_token=create_access_token(user.id))


@app.get("/api/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "email_verified": user.email_verified}


# ---------------------------------------------------------------------------
# Google OAuth connect (Sheets/Gmail/Drive scopes, separate from app login above)
# ---------------------------------------------------------------------------

# In-memory state->(user_id, pkce code_verifier) map for the OAuth redirect round trip.
# Short-lived (a user completes consent within a couple minutes or restarts the flow) --
# fine as in-process state even across Render's free-tier idle-sleep, since a sleep would
# drop an in-flight OAuth redirect anyway and the user just clicks "Connect Google" again.
_oauth_state: dict[str, tuple[str, str]] = {}


@app.get("/api/oauth/google/start")
def google_oauth_start(user: User = Depends(get_current_user)):
    state = _secrets.token_urlsafe(24)
    auth_url, code_verifier = pipeline_google_auth.build_authorization_url(state)
    _oauth_state[state] = (user.id, code_verifier)
    return {"authorization_url": auth_url}


@app.get("/api/oauth/google/callback")
def google_oauth_callback(code: str = "", state: str = "", error: str = ""):
    """Google redirects the actual BROWSER here, not a JS fetch() call -- there's no
    Authorization header available and no useful way to hand back JSON, since the browser
    just lands on this URL directly. Redirects back into the frontend instead, which reads
    the outcome from the query string and then calls /api/oauth/google/status (below) to
    confirm rather than trusting the query string alone -- e.g. after a page refresh."""
    frontend_origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
    target = f"{frontend_origin}/setup/google"

    if error:
        return RedirectResponse(f"{target}?error={error}")

    entry = _oauth_state.pop(state, None)
    if entry is None:
        return RedirectResponse(f"{target}?error=expired_state")
    user_id, code_verifier = entry
    try:
        pipeline_google_auth.exchange_code_for_credential(user_id, code, code_verifier)
    except Exception:  # noqa: BLE001 -- surfaced to the user via the redirect, not a crash
        logging.exception("Google OAuth token exchange failed")
        return RedirectResponse(f"{target}?error=exchange_failed")
    return RedirectResponse(f"{target}?connected=1")


@app.get("/api/oauth/google/status")
def google_oauth_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import OAuthCredential

    row = db.query(OAuthCredential).filter(
        OAuthCredential.user_id == user.id, OAuthCredential.provider == "google"
    ).one_or_none()
    if row is None:
        return {"connected": False}
    return {"connected": True, "email": row.granted_email, "scopes": row.scopes}


# ---------------------------------------------------------------------------
# Internal endpoints -- called by .github/workflows/daily.yml, not by real users.
# Shared-secret header auth (not JWT) since there's no logged-in user driving this.
# ---------------------------------------------------------------------------


def _require_internal_secret(x_internal_secret: str = Header(default="")):
    if not _secrets.compare_digest(x_internal_secret, INTERNAL_SHARED_SECRET):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad internal secret")


@app.get("/api/internal/active-users", dependencies=[Depends(_require_internal_secret)])
def active_users(db: Session = Depends(get_db)):
    """Called hourly now (see .github/workflows/daily.yml), not once a day -- each user
    picks their own run_hour_utc in the wizard/settings (Profile.run_hour_utc, default 14
    to match the old single fixed daily time), and only whoever's hour matches the current
    UTC hour comes back. The join to Profile also means a user still mid-wizard (no
    Profile row yet) is naturally excluded here instead of getting attempted on every one
    of the 24 hourly calls a day for nothing -- _run_pipeline_in_background's own
    profile-row check stays too, as a second guard, not replaced by this one."""
    now_hour = datetime.utcnow().hour
    users = (
        db.query(User)
        .join(Profile, Profile.user_id == User.id)
        .filter(User.active.is_(True), Profile.run_hour_utc == now_hour)
        .all()
    )
    return {"user_ids": [u.id for u in users]}


@app.post("/api/internal/invites", dependencies=[Depends(_require_internal_secret)])
def mint_invite(db: Session = Depends(get_db)):
    """Generates one single-use signup code. Call with the same X-Internal-Secret header
    used by the scheduler, e.g.
    `curl -X POST -H "X-Internal-Secret: $INTERNAL_SHARED_SECRET" https://<host>/api/internal/invites`
    -- replaces manually handing out the one shared INVITE_CODE."""
    invite = Invite(code=_secrets.token_urlsafe(9))
    db.add(invite)
    db.commit()
    return {"code": invite.code}


def _run_pipeline_worker(
    user_id: str, lane_filter: str | None, max_age_days: int | None, cold_email_only: bool,
) -> None:
    """Runs on pipeline_google_auth.BACKGROUND_EXECUTOR's single worker thread, not
    Starlette's own background-task threadpool -- run() calls into cold_email.py's
    get_gmail_service/send_email, which touch the same shared per-user
    _credentials_cache/_service_cache that Sheet mirror writes, swipe likes, and retries
    all already serialize through this same executor. Running it on a separate thread
    (as this used to) let a daily run's Gmail calls race a concurrent mirror write against
    that cache -- the exact SIGSEGV/heap-corruption bug already fixed twice for other call
    sites (see postings_store.py's _fire_mirror and swipe.py/dashboard.py's like/retry).

    Own DB session since this doesn't run on a request thread with one already bound.
    active_users() includes every signed-up user regardless of wizard progress, so the
    daily cron will hit users mid-wizard (no Profile row yet) -- skip those cleanly instead
    of letting load_profile()'s LookupError blow up as an unhandled exception. Any other
    failure is logged with the user id so it's actually visible in server logs instead of
    an anonymous traceback."""
    from pipeline.run_pipeline import run

    db = SessionLocal()
    pipeline_config.set_session(db)
    try:
        if db.query(Profile).filter(Profile.user_id == user_id).first() is None:
            logging.info("Skipping daily run for %s: wizard not finished yet, no profile row", user_id)
            return
        run(user_id, lane_filter=lane_filter, max_age_days=max_age_days, cold_email_only=cold_email_only)
    except Exception:
        logging.exception("Daily run failed for user %s", user_id)
    finally:
        pipeline_config.set_session(None)
        db.close()


def _run_pipeline_in_background(
    user_id: str, lane_filter: str | None = None, max_age_days: int | None = None, cold_email_only: bool = False,
) -> None:
    """A full run (search + filter + several LLM calls per lane) can easily exceed what's
    safe to hold a single HTTP request open for on Render's free tier -- dispatched via
    BackgroundTasks so the request/scheduler call returns immediately, but the actual work
    is submitted onto pipeline_google_auth.BACKGROUND_EXECUTOR (see _run_pipeline_worker's
    docstring for why) and waited on here, so this call only returns once the run is done."""
    pipeline_google_auth.BACKGROUND_EXECUTOR.submit(
        _run_pipeline_worker, user_id, lane_filter, max_age_days, cold_email_only
    ).result()


@app.post("/api/internal/run/{user_id}", dependencies=[Depends(_require_internal_secret)], status_code=status.HTTP_202_ACCEPTED)
def run_pipeline_for_user(user_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_pipeline_in_background, user_id)
    return {"status": "started", "user_id": user_id}


class RunNowRequest(BaseModel):
    lane_filter: str | None = None
    max_age_days: int | None = None
    cold_email_only: bool = False


@app.post("/api/run-now", status_code=status.HTTP_202_ACCEPTED)
def run_now(
    background_tasks: BackgroundTasks,
    body: RunNowRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """User-facing manual trigger for their own daily run, same underlying job as the
    scheduler's /api/internal/run/{user_id} -- one run per calendar day, checked against
    DailySummary rather than any separate cooldown state, since a summary row is exactly
    what a completed run produces. Optional overrides (lane_filter/max_age_days/
    cold_email_only) mirror run_pipeline.run()'s own optional parameters -- e.g. a manual
    re-run of one lane after tweaking its keywords, or widening the recency window past
    the scheduled run's default cutoff."""
    body = body or RunNowRequest()
    from pipeline.postings_store import get_daily_summaries

    # The same-day guard only applies to a full default run -- a scoped re-run (one
    # lane, or cold-email-only) is a deliberate narrow action, not a duplicate of the
    # day's real run, so it's exempt (matches the docstring's "re-run one lane after
    # tweaking its keywords" use case, which would be pointless if blocked every time
    # the scheduled run already fired today).
    if not body.lane_filter and not body.cold_email_only:
        # Restore whatever the middleware had bound before this check, not None -- this
        # request's contextvar is shared with bind_db_session_for_pipeline's own session,
        # and nulling it out here would strand any pipeline call later in this handler
        # (or in a dependency ordered after this one) with no session to read.
        prev_session = pipeline_config.get_session()
        pipeline_config.set_session(db)
        today = date.today().isoformat()
        already_ran = any(s["date"] == today for s in get_daily_summaries(user.id))
        pipeline_config.set_session(prev_session)
        if already_ran:
            raise HTTPException(status.HTTP_409_CONFLICT, "Already ran today. Try again tomorrow.")

    background_tasks.add_task(
        _run_pipeline_in_background, user.id, body.lane_filter, body.max_age_days, body.cold_email_only
    )
    return {"status": "started"}


# ---------------------------------------------------------------------------
# Serve the built frontend (frontend/dist) from this same process -- single Render
# deploy instead of a separate Vercel deploy, one origin, no CORS between them. Must
# stay the LAST thing registered: every /api/* route above is matched first since
# Starlette tries routes in registration order, so this never shadows the API.
# ---------------------------------------------------------------------------

_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="frontend-assets")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(_FRONTEND_DIST / "favicon.ico")

    @app.get("/logo.png", include_in_schema=False)
    def logo():
        return FileResponse(_FRONTEND_DIST / "logo.png")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """Anything not matched above is a client-side route (React Router) -- always
        serve index.html and let the SPA's own router resolve it, same as any other
        single-page-app static host (Vercel/Netlify do this automatically; here it's
        explicit since FastAPI doesn't have a built-in SPA fallback)."""
        return FileResponse(_FRONTEND_DIST / "index.html")
