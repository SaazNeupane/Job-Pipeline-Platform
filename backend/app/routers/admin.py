"""Admin-only routes, gated by User.is_admin (see app/auth.py's get_current_admin) rather
than the shared-secret X-Internal-Secret used by /api/internal/* -- those are for the
scheduler/CI, these are for a logged-in admin driving the UI. Invite minting logic mirrors
main.py's /api/internal/invites (kept there too for the ops curl/CI use case)."""

from __future__ import annotations

import secrets as _secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_admin
from app.db import get_db
from app.models import ColdEmail, DailySummary, Invite, OAuthCredential, Posting, Profile, User
from sqlalchemy import func

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _invite_dict(invite: Invite, used_by_email: str | None) -> dict:
    return {
        "id": invite.id,
        "code": invite.code,
        "created_at": invite.created_at.isoformat(),
        "used_at": invite.used_at.isoformat() if invite.used_at else None,
        "used_by_email": used_by_email,
    }


@router.get("/invites")
def list_invites(_admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    invites = db.query(Invite).order_by(Invite.created_at.desc()).all()
    user_ids = [i.used_by_user_id for i in invites if i.used_by_user_id]
    emails_by_id = {}
    if user_ids:
        emails_by_id = {u.id: u.email for u in db.query(User).filter(User.id.in_(user_ids)).all()}
    return [_invite_dict(i, emails_by_id.get(i.used_by_user_id)) for i in invites]


@router.post("/invites", status_code=status.HTTP_201_CREATED)
def mint_invite(_admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    invite = Invite(code=_secrets.token_urlsafe(9))
    db.add(invite)
    db.commit()
    return _invite_dict(invite, None)


@router.delete("/invites/{invite_id}")
def revoke_invite(invite_id: str, _admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    invite = db.get(Invite, invite_id)
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such invite.")
    if invite.used_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already used -- nothing to revoke.")
    db.delete(invite)
    db.commit()
    return {"ok": True}


@router.get("/users")
def list_users(_admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    rows = db.query(User).order_by(User.created_at.desc()).all()
    profiles_by_user = {p.user_id: p for p in db.query(Profile).all()}
    result = []
    for u in rows:
        profile = profiles_by_user.get(u.id)
        result.append({
            "id": u.id,
            "email": u.email,
            "created_at": u.created_at.isoformat(),
            "active": u.active,
            "email_verified": u.email_verified,
            "is_admin": u.is_admin,
            "has_profile": profile is not None,
            "lane_count": len(profile.lanes_json) if profile else 0,
        })
    return result


@router.get("/users/{user_id}")
def user_detail(user_id: str, _admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """A read-only drill-down into one user: their setup (lanes/location targeting/run
    schedule/Google connection), and their actual usage (posting funnel, cold email
    funnel, recent runs) -- everything an admin would need to answer "is this account
    actually working," without exposing anything sensitive. Deliberately never returns
    resume content, cover letters, or the encrypted API keys/OAuth token themselves --
    Secret/OAuthCredential rows are checked for presence only, never decrypted here."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user.")

    profile = db.query(Profile).filter(Profile.user_id == user_id).one_or_none()
    google = db.query(OAuthCredential).filter(
        OAuthCredential.user_id == user_id, OAuthCredential.provider == "google"
    ).one_or_none()

    status_counts = dict(
        db.query(Posting.status, func.count(Posting.id))
        .filter(Posting.user_id == user_id)
        .group_by(Posting.status)
        .all()
    )
    cold_emails_sent = db.query(func.count(ColdEmail.id)).filter(ColdEmail.user_id == user_id).scalar() or 0
    recent_runs = (
        db.query(DailySummary)
        .filter(DailySummary.user_id == user_id)
        .order_by(DailySummary.date.desc())
        .limit(14)
        .all()
    )

    return {
        "id": user.id,
        "email": user.email,
        "created_at": user.created_at.isoformat(),
        "active": user.active,
        "email_verified": user.email_verified,
        "is_admin": user.is_admin,
        "plan": user.plan,
        "profile": None if profile is None else {
            "lanes": [{"name": l.get("name"), "keywords": l.get("keywords", [])} for l in (profile.lanes_json or [])],
            "target_countries": profile.target_countries_json or [],
            "target_regions": profile.target_regions_json or [],
            "adzuna_country": profile.adzuna_country,
            "apply_daily_cap": profile.apply_daily_cap,
            "run_hour_utc": profile.run_hour_utc,
            "sheet_id": profile.sheet_id or None,
            "updated_at": profile.updated_at.isoformat(),
        },
        "google_connected": google is not None,
        "google_email": google.granted_email if google else None,
        "postings_by_status": status_counts,
        "cold_emails_sent": cold_emails_sent,
        "recent_runs": [
            {
                "date": r.date,
                "queued": r.queued_count,
                "applied": r.applied_count,
                "emails_sent": r.emails_sent,
                "errors": r.errors,
                "notes": r.notes,
            }
            for r in recent_runs
        ],
    }


@router.post("/users/{user_id}/active")
def set_user_active(
    user_id: str, body: dict, admin: User = Depends(get_current_admin), db: Session = Depends(get_db),
):
    """Deactivate/reactivate a user -- flips User.active, which get_current_user already
    checks on every request (see app/auth.py), so a deactivated user's existing JWT stops
    working immediately rather than waiting for it to expire. Reversible, unlike deleting
    the account outright."""
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Can't deactivate your own account.")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user.")
    user.active = bool(body.get("active", True))
    db.commit()
    return {"id": user.id, "active": user.active}


@router.post("/users/{user_id}/plan")
def set_user_plan(
    user_id: str, body: dict, _admin: User = Depends(get_current_admin), db: Session = Depends(get_db),
):
    """Flip a user between free/paid -- manual admin override, no payment processor wired
    up yet (see PLAN_MANUAL_RUN_LIMITS/PLAN_ALLOWED_SOURCES in app/main.py and
    pipeline/run_pipeline.py for what plan actually gates)."""
    plan = body.get("plan")
    if plan not in ("free", "paid"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "plan must be 'free' or 'paid'.")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user.")
    user.plan = plan
    db.commit()
    return {"id": user.id, "plan": user.plan}
