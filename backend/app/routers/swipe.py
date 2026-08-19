"""Swipe-queue routes, ported from webapp/app.py's /api/swipe/* handlers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import get_current_user
from app.models import User
from app.routers._dashboard_helpers import group_by_lane, lane_label, newest_first
from pipeline.config import load_profile
from pipeline.google_auth import submit_for_user
from pipeline.postings_store import get_postings
from pipeline.swipe_actions import add_manual_posting, generate_liked_materials, queue_like, reject_posting

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
    import logging

    from app.db import SessionLocal
    from pipeline import config as pipeline_config
    from pipeline.postings_store import update_posting

    try:
        db = SessionLocal()
        pipeline_config.set_session(db)
        try:
            generate_liked_materials(user_id, match)
        finally:
            pipeline_config.set_session(None)
            db.close()
    except Exception as exc:  # noqa: BLE001 — background thread has no caller to raise to; a
        # session-setup/teardown failure here (e.g. a dropped DB connection) previously
        # escaped generate_liked_materials()'s own try/except entirely and left the row
        # stuck on reason_held="generating" forever, since nothing ever called .result()
        # on the submitted future to surface it. Must still mark the row failed so a user
        # sees "generation_failed" (and can retry) instead of a silent stall.
        logging.exception("generate_liked_materials background task failed for %s", match.get("posting_key"))
        try:
            update_posting(user_id, match["posting_key"], {"reason_held": f"generation_failed: {exc}"})
        except Exception:
            logging.exception("failed to record generation_failed for %s", match.get("posting_key"))


class ManualPostingRequest(BaseModel):
    lane: str
    text: str
    url: str = ""


@router.post("/manual")
def add_manual(body: ManualPostingRequest, user: User = Depends(get_current_user)):
    try:
        match = add_manual_posting(user.id, body.lane, body.text, body.url)
    except SystemExit as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    submit_for_user(user.id, _generate_in_background, user.id, match)
    return {"ok": True, "row": {"company": match.get("company", ""), "role": match.get("role", "")}}


@router.post("/{posting_key:path}/like")
def like(posting_key: str, user: User = Depends(get_current_user)):
    try:
        match = queue_like(user.id, posting_key)
    except SystemExit as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    submit_for_user(user.id, _generate_in_background, user.id, match)
    return {"ok": True, "row": {"company": match.get("company", ""), "role": match.get("role", "")}}


@router.post("/{posting_key:path}/reject")
def reject(posting_key: str, user: User = Depends(get_current_user)):
    try:
        reject_posting(user.id, posting_key)
    except SystemExit as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return {"ok": True}
