"""Swipe-queue routes, ported from webapp/app.py's /api/swipe/* handlers."""

from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.auth import get_current_user
from app.models import User
from app.routers._dashboard_helpers import group_by_lane, lane_label, newest_first
from pipeline.config import load_profile
from pipeline.postings_store import get_postings
from pipeline.swipe_actions import generate_liked_materials, queue_like, reject_posting

router = APIRouter(prefix="/api/swipe", tags=["swipe"])


@router.get("/queue")
def queue(user: User = Depends(get_current_user)):
    try:
        profile = load_profile(user.id)
    except LookupError:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "No profile found -- finish the setup wizard first.", "code": "profile_missing"},
        )

    rows = get_postings(user.id, status="queued")
    lane_names = [lane.name for lane in profile.lanes]
    return {
        "queue": newest_first(rows),
        "queue_by_lane": group_by_lane(rows, lane_names),
        "lane_names": lane_names,
        "lane_labels": {name: lane_label(name) for name in lane_names},
    }


def _generate_in_background(user_id: str, match: dict) -> None:
    from app.db import SessionLocal
    from pipeline import config as pipeline_config

    db = SessionLocal()
    pipeline_config.set_session(db)
    try:
        generate_liked_materials(user_id, match)
    finally:
        pipeline_config.set_session(None)
        db.close()


@router.post("/{posting_key:path}/like")
def like(posting_key: str, user: User = Depends(get_current_user)):
    try:
        match = queue_like(user.id, posting_key)
    except SystemExit as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    threading.Thread(target=_generate_in_background, args=(user.id, match), daemon=True).start()
    return {"ok": True, "row": {"company": match.get("company", ""), "role": match.get("role", "")}}


@router.post("/{posting_key:path}/reject")
def reject(posting_key: str, user: User = Depends(get_current_user)):
    try:
        reject_posting(user.id, posting_key)
    except SystemExit as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return {"ok": True}
