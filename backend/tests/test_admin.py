"""Coverage for app/routers/admin.py -- previously untested despite gating real destructive/
sensitive actions (deactivate any account, flip anyone's plan, view a user's full detail).
Calls the route functions directly against the db_session fixture, same pattern as
test_manual_run_quota.py -- exercises real HTTPExceptions without the TestClient/engine layer."""

from fastapi import HTTPException
import pytest

from app.auth import get_current_admin
from app.models import DailySummary, Invite, Profile, User
from app.routers.admin import (
    list_invites,
    list_users,
    mint_invite,
    revoke_invite,
    set_user_active,
    set_user_plan,
    user_detail,
)


def _make_user(db_session, *, is_admin=False, plan="free", active=True, email=None):
    user = User(
        email=email or f"{'admin' if is_admin else 'user'}-{plan}@example.com",
        password_hash="x", is_admin=is_admin, plan=plan, active=active,
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_get_current_admin_rejects_non_admin(db_session):
    user = _make_user(db_session, is_admin=False)
    with pytest.raises(HTTPException) as exc_info:
        get_current_admin(user)
    assert exc_info.value.status_code == 403


def test_get_current_admin_allows_admin(db_session):
    admin = _make_user(db_session, is_admin=True)
    assert get_current_admin(admin) is admin


def test_mint_list_revoke_invite(db_session):
    admin = _make_user(db_session, is_admin=True)

    minted = mint_invite(admin, db_session)
    assert minted["used_at"] is None

    invites = list_invites(admin, db_session)
    assert len(invites) == 1
    assert invites[0]["code"] == minted["code"]

    revoke_invite(minted["id"], admin, db_session)
    assert list_invites(admin, db_session) == []


def test_revoke_used_invite_conflicts(db_session):
    admin = _make_user(db_session, is_admin=True)
    invite = Invite(code="usedcode123", used_at=__import__("app.time_utils", fromlist=["utcnow"]).utcnow())
    db_session.add(invite)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        revoke_invite(invite.id, admin, db_session)
    assert exc_info.value.status_code == 409


def test_revoke_nonexistent_invite_404s(db_session):
    admin = _make_user(db_session, is_admin=True)
    with pytest.raises(HTTPException) as exc_info:
        revoke_invite("no-such-id", admin, db_session)
    assert exc_info.value.status_code == 404


def test_list_users_includes_profile_derived_fields(db_session):
    admin = _make_user(db_session, is_admin=True)
    plain = _make_user(db_session, email="plain@example.com")
    db_session.add(Profile(user_id=plain.id, lanes_json=[{"name": "it_tech"}, {"name": "ops"}]))
    db_session.commit()

    rows = {r["id"]: r for r in list_users(admin, db_session)}
    assert rows[plain.id]["has_profile"] is True
    assert rows[plain.id]["lane_count"] == 2
    assert rows[admin.id]["has_profile"] is False
    assert rows[admin.id]["lane_count"] == 0


def test_user_detail_404s_for_missing_user(db_session):
    admin = _make_user(db_session, is_admin=True)
    with pytest.raises(HTTPException) as exc_info:
        user_detail("no-such-id", admin, db_session)
    assert exc_info.value.status_code == 404


def test_user_detail_surfaces_plan_and_run_notes(db_session):
    """Regression check for the real gap fixed this session: DailySummary.errors was only
    ever a count, the actual error text lived in .notes and was never returned anywhere."""
    admin = _make_user(db_session, is_admin=True)
    target = _make_user(db_session, email="target@example.com", plan="paid")
    db_session.add(DailySummary(
        user_id=target.id, date="2026-08-22", errors="1", notes="cold_email: Gemini key expired",
    ))
    db_session.commit()

    detail = user_detail(target.id, admin, db_session)
    assert detail["plan"] == "paid"
    assert detail["profile"] is None
    assert detail["recent_runs"][0]["notes"] == "cold_email: Gemini key expired"


def test_set_user_active_toggles_and_blocks_self(db_session):
    admin = _make_user(db_session, is_admin=True)
    target = _make_user(db_session, email="target2@example.com")

    result = set_user_active(target.id, {"active": False}, admin, db_session)
    assert result["active"] is False
    db_session.refresh(target)
    assert target.active is False

    with pytest.raises(HTTPException) as exc_info:
        set_user_active(admin.id, {"active": False}, admin, db_session)
    assert exc_info.value.status_code == 400


def test_set_user_active_404s_for_missing_user(db_session):
    admin = _make_user(db_session, is_admin=True)
    with pytest.raises(HTTPException) as exc_info:
        set_user_active("no-such-id", {"active": False}, admin, db_session)
    assert exc_info.value.status_code == 404


def test_set_user_plan_toggles(db_session):
    admin = _make_user(db_session, is_admin=True)
    target = _make_user(db_session, email="target3@example.com", plan="free")

    result = set_user_plan(target.id, {"plan": "paid"}, admin, db_session)
    assert result["plan"] == "paid"
    db_session.refresh(target)
    assert target.plan == "paid"


def test_set_user_plan_rejects_invalid_value(db_session):
    admin = _make_user(db_session, is_admin=True)
    target = _make_user(db_session, email="target4@example.com")

    with pytest.raises(HTTPException) as exc_info:
        set_user_plan(target.id, {"plan": "gold"}, admin, db_session)
    assert exc_info.value.status_code == 400


def test_set_user_plan_404s_for_missing_user(db_session):
    admin = _make_user(db_session, is_admin=True)
    with pytest.raises(HTTPException) as exc_info:
        set_user_plan("no-such-id", {"plan": "paid"}, admin, db_session)
    assert exc_info.value.status_code == 404
