# Job Pipeline Platform

Hosted, multi-tenant rebuild of [job-pipeline](../job-pipeline) — same job-search/tailoring
logic, rebuilt around real accounts, a real database, and free-tier hosting instead of one
local profile directory + single-tenant GitHub Actions cron.

Full architecture plan: `C:\Users\saazn\.claude\plans\jolly-churning-cookie.md`.

## Stack

- **Backend**: FastAPI (`backend/app/`), reused pipeline logic (`backend/pipeline/`)
- **Database**: Postgres (Supabase free tier)
- **Frontend**: React/Vite (`frontend/`, copied from the old project's `frontend/` tree)
- **Scheduling**: GitHub Actions cron (`.github/workflows/daily.yml`) — triggers the hosted
  backend per active user rather than running the pipeline itself
- **Secrets at rest**: Fernet-encrypted Postgres columns (`backend/app/crypto.py`)

## What's carried over vs. rebuilt

`backend/pipeline/` — `search.py`, `filter.py`, `text_match.py`, `tailor_resume.py`,
`cover_letter.py`, `cold_email.py`, `writing_style.py`, `sheet_log.py`, `json_cache.py`,
`daily_report.py`, `swipe_actions.py`, `promote_application.py`, `dismiss_application.py`,
`drive_storage.py`, `setup_sheet.py`, `run_pipeline.py` are copied from the old repo
**unmodified** (two exceptions: `swipe_actions.py`/`cold_email.py` each had one line changed
from `profile.resume_path(lane.name)` to `profile.resumes[lane.name]` — see below). They all
call `load_profile(user)` / `load_secrets(user)` / `get_sheets_service(user)` / etc. with just
a user id — same signatures as before. What changed is only where those functions get their
data: `config.py` and `google_auth.py` are rewritten to read/write Postgres instead of
`profiles/<user>/*.yaml` and `secrets.env`, using a contextvar (`pipeline.config.set_session`)
so the DB session doesn't need to be threaded through every call site by hand.
`app/main.py`'s middleware sets that contextvar once per request; background tasks (swipe-like
generation, the internal run endpoint) open and bind their own session instead, since the
request's session is gone by the time a background task runs.

`pipeline/wizard.py` is `webapp/wizard.py` trimmed to pure logic only (lane presets, lane/profile/
resume-dict assembly, PDF import) — every filesystem-touching function from the original
(`profile_dir_for`, `write_profile_files`, `save_github_repo`, ...) was dropped, since there's
no per-user directory here; `app/routers/wizard.py` does the equivalent DB writes instead.

`app/routers/{wizard,dashboard,swipe}.py` are the ported `webapp/app.py` route handlers,
keyed off the JWT-authenticated user instead of a `<user>` URL segment + filesystem checks.

One real gap found while porting: the old `Profile.resume_path(lane_name)` method read
`resume_<lane>.json` off disk — no DB equivalent existed, since there's no per-user resume
file anymore. Fixed by adding `Profile.resumes: dict[str, dict]` (lane name → resume JSON,
backed by a new `profiles.resumes_json` column, populated at wizard finalize time) and
switching the two call sites (`swipe_actions.py`, `cold_email.py`) to read `profile.resumes[...]`
directly.

## Status / not yet done

- [x] Repo structure, reused pipeline modules, DB models, encrypted secrets/OAuth storage
- [x] Auth (signup/login), Google OAuth web flow (connect/callback), granted-email capture
- [x] Wizard routes (draft, lanes, resume import, review, finalize — creates the Profile row
      + Google Sheet), dashboard routes (list/promote/dismiss/retry), swipe routes (queue/like/reject)
- [x] `/api/internal/run/{user_id}` actually runs `run_pipeline.run()` (background task), not stubbed
- [x] Frontend rewired for real auth: login/signup pages, JWT via `AuthContext`, `api.js`
      talks to the hosted backend (`VITE_API_BASE` + CORS, not same-origin), every route
      dropped its old `<user>` URL segment, wizard's Google step rewritten for the real
      browser-redirect OAuth flow. `npm run build` clean; CORS confirmed for real (preflight
      from a running `localhost:5173` dev server against the live backend). **Not yet
      verified in an actual browser** — no Chrome extension connection in this environment,
      so clicking through signup → wizard → dashboard hasn't been visually confirmed.
- [ ] Deploy: Render (backend) + Vercel (frontend), wire real env vars including a real
      `GOOGLE_OAUTH_CLIENT_ID/SECRET` (still `dummy` placeholders everywhere so far)
- [ ] Submit for Google OAuth app verification (external, manual, required before open
      signup can request Gmail/Drive scopes from arbitrary accounts — see plan doc)
- [x] Backend actually runs, against a real hosted Postgres: a real Supabase project (free
      tier), `scripts/init_db.py` against it, and a live `uvicorn` process exercised end to
      end (signup → login → JWT-authenticated `/api/me` → wizard draft/lanes → dashboard
      404-before-finalize → draft persists across a fresh fetch). Smoke-test rows cleaned up
      after. Along the way: caught and fixed three real bugs `py_compile` couldn't (missing
      `python-multipart`, missing `email-validator`, passlib incompatible with modern bcrypt
      — now calls `bcrypt` directly); confirmed the fixed `requirements.txt` alone produces a
      working install from a clean venv; and found Supabase's **direct** connection host
      (`db.<ref>.supabase.co`) is IPv6-only and didn't resolve on this network — switched to
      Supabase's **Session Pooler** host instead (IPv4-compatible), which worked. `app/db.py`
      now calls `load_dotenv()` so a local `backend/.env` (gitignored, holds the real
      Supabase connection string + generated secrets) loads automatically.
      **Still not tested**: the wizard `finalize` → `create_sheet` path (needs a real Google
      OAuth app, not the placeholder `GOOGLE_OAUTH_CLIENT_ID=dummy` used so far — building a
      real one needs a Google Cloud Console project, an external step), `/api/internal/run`
      actually running a pipeline (needs a real profile + real secrets end to end).

## Local dev

```
cd backend
pip install -r requirements.txt
# set DATABASE_URL, JWT_SECRET, ENCRYPTION_KEY, INTERNAL_SHARED_SECRET,
# GOOGLE_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI, FRONTEND_ORIGIN in your env
python -m scripts.init_db
uvicorn app.main:app --reload
```

```
cd frontend
npm install
npm run dev
```
