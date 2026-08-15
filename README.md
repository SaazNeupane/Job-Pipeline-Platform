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
`drive_storage.py` are copied from the old repo **unmodified**. They all call
`load_profile(user)` / `load_secrets(user)` / `get_sheets_service(user)` / etc. with just a
user id — same signatures as before. What changed is only where those functions get their
data: `config.py` and `google_auth.py` are rewritten to read/write Postgres instead of
`profiles/<user>/*.yaml` and `secrets.env`, using a contextvar (`pipeline.config.set_session`)
so the DB session doesn't need to be threaded through every call site by hand.
`app/main.py`'s middleware sets that contextvar once per request.

## Status / not yet done

This is the first scaffolding pass, not a working deploy yet:

- [x] Repo structure, reused pipeline modules, DB models, encrypted secrets/OAuth storage
- [x] Auth skeleton (signup/login), Google OAuth web-flow skeleton (connect/callback)
- [x] Internal scheduler endpoints (stubbed — `run_pipeline_for_user` returns 501)
- [ ] Port `run_pipeline.py`'s orchestrator into the internal run endpoint
- [ ] Port `webapp/wizard.py` + `webapp/app.py`'s profile-editing/dashboard/swipe routes —
      currently only auth + OAuth connect exist as real endpoints
- [ ] Frontend: swap `api.js`'s base URL and local-dashboard assumptions for real
      login/signup screens, repoint at the hosted backend
- [ ] Deploy: Render (backend) + Vercel (frontend) + Supabase (DB), wire real env vars
- [ ] Submit for Google OAuth app verification (external, manual, required before open
      signup can request Gmail/Drive scopes from arbitrary accounts — see plan doc)

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
