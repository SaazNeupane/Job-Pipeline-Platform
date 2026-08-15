"""Dashboard routes, ported from webapp/app.py's /api/dashboard/* handlers. Google
reauth (RefreshError) is handled globally by an exception handler registered in
app/main.py, not per-route here, same effective behavior as the old
_handle_google_reauth decorator."""

from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import User
from app.routers._dashboard_helpers import group_by_lane, lane_label, newest_first
from pipeline.config import load_profile
from pipeline.dismiss_application import dismiss_application, dismiss_applications
from pipeline.promote_application import promote_application
from pipeline.sheet_log import get_rows_multi
from pipeline.swipe_actions import generate_liked_materials, retry_generation

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(user: User = Depends(get_current_user)):
    try:
        profile = load_profile(user.id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No profile found -- finish the setup wizard first.")

    rows_by_tab = get_rows_multi(
        user.id, ["pending_approval", "applied_jobs", "daily_summary", "cold_emails", "swipe_queue"],
    )
    pending = rows_by_tab["pending_approval"]
    applied = rows_by_tab["applied_jobs"]
    summary = rows_by_tab["daily_summary"]
    cold_emails = rows_by_tab["cold_emails"]
    swipe_queue_count = len(rows_by_tab["swipe_queue"])
    lane_names = [lane.name for lane in profile.lanes]

    return {
        "user": user.id,
        "pending": pending,
        "applied": applied,
        "summary": summary,
        "cold_emails": cold_emails,
        "pending_by_lane": group_by_lane(pending, lane_names),
        "applied_by_lane": group_by_lane(applied, lane_names),
        "cold_emails_by_lane": group_by_lane(cold_emails, lane_names),
        "swipe_queue_count": swipe_queue_count,
        "lane_names": lane_names,
        "lane_labels": {name: lane_label(name) for name in lane_names},
    }


@router.post("/promote/{posting_key:path}")
def promote(posting_key: str, user: User = Depends(get_current_user)):
    promote_application(user.id, posting_key)
    return {"ok": True}


@router.post("/dismiss/{posting_key:path}")
def dismiss(posting_key: str, user: User = Depends(get_current_user)):
    dismiss_application(user.id, posting_key)
    return {"ok": True}


@router.post("/dismiss-bulk")
def dismiss_bulk(body: dict, user: User = Depends(get_current_user)):
    posting_keys = body.get("posting_keys") or []
    if posting_keys:
        dismiss_applications(user.id, posting_keys)
    return {"ok": True, "count": len(posting_keys)}


def _regenerate_in_background(user_id: str, row: dict) -> None:
    """generate_liked_materials() writes through pipeline modules that read the current DB
    session via pipeline.config's contextvar -- a background thread has no request-scoped
    session, so it opens and binds its own, same pattern as the internal run endpoint in
    app/main.py."""
    from app.db import SessionLocal
    from pipeline import config as pipeline_config

    db = SessionLocal()
    pipeline_config.set_session(db)
    try:
        generate_liked_materials(user_id, row)
    finally:
        pipeline_config.set_session(None)
        db.close()


@router.post("/retry/{posting_key:path}")
def retry(posting_key: str, user: User = Depends(get_current_user)):
    try:
        row = retry_generation(user.id, posting_key)
    except SystemExit as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    threading.Thread(target=_regenerate_in_background, args=(user.id, row), daemon=True).start()
    return {"ok": True}
