"""Postgres session setup. DATABASE_URL points at the Supabase (or any) Postgres instance.

load_dotenv() runs here, not in app/main.py, because app.db is the one module every other
env-var-reading module (app/auth.py's JWT_SECRET, pipeline/config.py's DB access, ...)
already imports before reading its own os.environ values -- see each entrypoint
(app/main.py, scripts/init_db.py)'s import order. Putting it here means a local backend/.env
gets picked up regardless of which entrypoint imports first, without needing every one of
them to remember to call load_dotenv() themselves. In hosted deploys (Render, GitHub Actions)
there's no .env file at all -- load_dotenv() is a silent no-op then, real env vars set by the
platform take over exactly as before."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from starlette.requests import Request

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db(request: Request):
    """bind_db_session_for_pipeline (app/main.py) already opens one session per request
    and stashes it on request.state.db -- reuse that instead of opening a second one, so
    a route handler that both takes Depends(get_db) and calls into pipeline/* (which reads
    the same session via a contextvar) doesn't hold two live Postgres connections for one
    request. The middleware owns closing it; this generator's own finally only runs for
    the (non-HTTP) fallback path below."""
    shared = getattr(request.state, "db", None)
    if shared is not None:
        yield shared
        return
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
