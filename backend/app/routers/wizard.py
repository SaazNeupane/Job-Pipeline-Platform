"""Setup-wizard routes. Ported from the old webapp/app.py's /api/wizard/* handlers --
same underlying logic (pipeline/wizard.py), but keyed off the authenticated user (JWT) and
writing to Postgres instead of a per-user profile.yaml/resume_<lane>.json/secrets.env on
disk. Google OAuth connect itself lives in app/main.py's /api/oauth/google/* -- the wizard
here just checks whether that step has been completed (an oauth_credentials row exists)
before allowing finalize.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.crypto import encrypt
from app.db import get_db
from app.models import OAuthCredential, Profile as ProfileRow, Secret, User, WizardDraft
from pipeline import setup_sheet
from pipeline import wizard as wizard_logic
from pipeline.geocode import geocode_address

router = APIRouter(prefix="/api/wizard", tags=["wizard"])
logger = logging.getLogger(__name__)

_EMPTY_DRAFT = {"lanes": [], "lane_names": [], "lane_labels": {}}


def _get_or_create_draft(db: Session, user_id: str) -> WizardDraft:
    row = db.query(WizardDraft).filter(WizardDraft.user_id == user_id).one_or_none()
    if row is None:
        row = WizardDraft(user_id=user_id, draft_json=dict(_EMPTY_DRAFT))
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@router.get("/draft")
def get_draft(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _get_or_create_draft(db, user.id).draft_json


@router.patch("/draft")
def patch_draft(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _get_or_create_draft(db, user.id)
    draft = dict(row.draft_json)

    if "applicant" in body:
        applicant = body["applicant"] or {}
        if not applicant.get("first_name") or not applicant.get("last_name") or not applicant.get("country"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Name and country are required.")
        draft["applicant"] = applicant

    if "shared_resume" in body:
        shared_resume = body["shared_resume"] or {}
        if not shared_resume.get("name") or not shared_resume.get("experience"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add your name and at least one work experience entry.")
        draft["shared_resume"] = shared_resume

    if "secrets" in body:
        draft["secrets"] = {
            "ADZUNA_APP_ID": str(body["secrets"].get("adzuna_app_id", "")).strip(),
            "ADZUNA_APP_KEY": str(body["secrets"].get("adzuna_app_key", "")).strip(),
            "GEMINI_API_KEY": str(body["secrets"].get("gemini_api_key", "")).strip(),
        }

    row.draft_json = draft
    db.commit()
    return draft


@router.post("/geocode")
def geocode(body: dict, user: User = Depends(get_current_user)):
    address = str(body.get("address", "")).strip()
    if not address:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Address is required.")
    try:
        result = geocode_address(address)
    except Exception:  # noqa: BLE001 -- external service failure, surfaced not crashed
        logger.exception("geocode_address failed for address=%r", address)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Couldn't reach the address lookup service. Try again in a moment.")
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Couldn't find that address -- check the spelling, or enter coordinates directly.")
    latitude, longitude = result
    return {"latitude": latitude, "longitude": longitude}


@router.post("/resume/import")
async def import_resume(
    resume_pdf: UploadFile = File(...),
    gemini_api_key: str = Form(...),
    user: User = Depends(get_current_user),
):
    if not gemini_api_key.strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A Gemini API key is needed to read the PDF -- get a free one at aistudio.google.com/apikey.",
        )
    try:
        raw_text = wizard_logic.extract_pdf_text(await resume_pdf.read())
        resume = wizard_logic.structure_resume_with_llm(gemini_api_key.strip(), raw_text)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except Exception:  # noqa: BLE001 -- surfaced to the user, not a crash
        logger.exception("resume PDF import failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Couldn't import that resume. Try again, or fill it in by hand instead.")
    return resume


@router.post("/lanes")
def set_lanes(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _get_or_create_draft(db, user.id)
    draft = dict(row.draft_json)
    presets = body.get("presets") or []
    custom_lanes_in = body.get("custom_lanes") or []

    try:
        lanes = [
            wizard_logic.resolve_preset_lane(p["name"], {"keywords": p["keywords"]} if p.get("keywords") else None)
            for p in presets
        ]
        for c in custom_lanes_in:
            lanes.append(wizard_logic.build_custom_lane(
                c.get("label", ""),
                c.get("keywords") or [],
                radius_km=c.get("radius_km"),
                sources=c.get("sources"),
                remote_types=c.get("remote_types"),
                employment_types=c.get("employment_types"),
                salary_min=c.get("salary_min"),
                salary_max=c.get("salary_max"),
                required_keywords=c.get("required_keywords"),
                seniority_max=c.get("seniority_max"),
                industries=c.get("industries"),
            ))
    except wizard_logic.WizardError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    if not lanes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick at least one job type, built-in or your own.")

    preset_names = [p["name"] for p in presets]
    draft["lanes"] = lanes
    draft["lane_names"] = [lane["name"] for lane in lanes]
    draft["lane_labels"] = {
        **{name: wizard_logic.LANE_TEMPLATES[name]["label"] for name in preset_names if name in wizard_logic.LANE_TEMPLATES},
        **{lane["name"]: lane["name"].replace("_", " ").title() for lane in lanes if lane["name"] not in preset_names},
    }
    draft["greenhouse_boards"] = [str(b).strip() for b in (body.get("greenhouse_boards") or []) if str(b).strip()]
    draft["lever_companies"] = [str(b).strip() for b in (body.get("lever_companies") or []) if str(b).strip()]
    draft["ashby_boards"] = [str(b).strip() for b in (body.get("ashby_boards") or []) if str(b).strip()]
    draft["adzuna_country"] = str(body.get("adzuna_country", "ca")).strip().lower()
    draft["target_countries"] = [str(c).strip().lower() for c in (body.get("target_countries") or []) if str(c).strip()]
    draft["run_hour_utc"] = max(0, min(23, int(body.get("run_hour_utc", 14) or 14)))

    row.draft_json = draft
    db.commit()
    return draft


def _google_connection(db: Session, user_id: str) -> OAuthCredential | None:
    return db.query(OAuthCredential).filter(
        OAuthCredential.user_id == user_id, OAuthCredential.provider == "google"
    ).one_or_none()


def _build_profile_and_resumes(user_id: str, draft: dict, granted_email: str) -> tuple[dict, dict]:
    lane_names = draft["lane_names"]
    profile_dict = wizard_logic.build_profile_yaml_dict(
        user=user_id,
        applicant=draft["applicant"],
        lanes=draft["lanes"],
        greenhouse_boards=draft.get("greenhouse_boards", []),
        lever_companies=draft.get("lever_companies"),
        ashby_boards=draft.get("ashby_boards"),
        adzuna_country=draft.get("adzuna_country", "ca"),
        target_countries=draft.get("target_countries"),
        sheet_id=draft.get("sheet_id", ""),
        gmail_address=granted_email,
        report_email=granted_email,
    )
    resumes = {name: wizard_logic.build_resume_json(draft["shared_resume"], name, lane_names) for name in lane_names}
    # Not part of pipeline.config.Profile's shape (the scheduler is the only reader, see
    # main.py's active_users()) -- attached here only so Review.jsx has something to show.
    profile_dict["run_hour_utc"] = draft.get("run_hour_utc", 14)
    return profile_dict, resumes


@router.get("/review")
def review(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    draft = _get_or_create_draft(db, user.id).draft_json
    if not draft.get("applicant") or not draft.get("lane_names") or not draft.get("shared_resume"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Finish the earlier steps first.")
    google = _google_connection(db, user.id)
    if google is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Connect Google first.")

    profile_dict, resumes = _build_profile_and_resumes(user.id, draft, google.granted_email)
    return {"profile_yaml": profile_dict, "resumes": resumes}


def _upsert_secret(db: Session, user_id: str, key_name: str, value: str) -> None:
    if not value:
        return
    row = db.query(Secret).filter(Secret.user_id == user_id, Secret.key_name == key_name).one_or_none()
    if row is None:
        row = Secret(user_id=user_id, key_name=key_name, value_encrypted=encrypt(value))
        db.add(row)
    else:
        row.value_encrypted = encrypt(value)


@router.post("/finalize")
def finalize(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    draft_row = _get_or_create_draft(db, user.id)
    draft = draft_row.draft_json
    google = _google_connection(db, user.id)
    if google is None or not draft.get("lane_names") or not draft.get("shared_resume"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Finish the earlier steps first.")

    profile_dict, resumes = _build_profile_and_resumes(user.id, draft, google.granted_email)

    for key_name in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "GEMINI_API_KEY"):
        _upsert_secret(db, user.id, key_name, (draft.get("secrets") or {}).get(key_name, ""))
    db.commit()

    profile_row = db.query(ProfileRow).filter(ProfileRow.user_id == user.id).one_or_none()
    if profile_row is None:
        profile_row = ProfileRow(user_id=user.id)
        db.add(profile_row)

    try:
        sheet_id = profile_row.sheet_id or setup_sheet.create_sheet(user.id)
    except Exception:  # noqa: BLE001 -- shown to the user, not a crash
        logger.exception("create_sheet failed for user_id=%r", user.id)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Couldn't create your Google Sheet. Try reconnecting Google and try again.")

    profile_row.sheet_id = sheet_id
    profile_row.gmail_address = profile_dict["gmail_address"]
    profile_row.report_email = profile_dict["report_email"]
    profile_row.adzuna_country = profile_dict["adzuna_country"]
    profile_row.lanes_json = profile_dict["lanes"]
    profile_row.cold_email_json = profile_dict["cold_email"]
    profile_row.applicant_json = profile_dict["applicant"]
    profile_row.greenhouse_boards_json = profile_dict["greenhouse_boards"]
    profile_row.lever_companies_json = profile_dict["lever_companies"]
    profile_row.ashby_boards_json = profile_dict["ashby_boards"]
    profile_row.target_countries_json = profile_dict["target_countries"]
    profile_row.apply_daily_cap = profile_dict["apply_daily_cap"]
    profile_row.run_hour_utc = profile_dict["run_hour_utc"]
    profile_row.resumes_json = resumes
    db.commit()

    return {"ok": True}


@router.get("/lane-presets")
def lane_presets():
    return {
        "presets": wizard_logic.LANE_TEMPLATES,
        "preset_blurbs": wizard_logic.LANE_TEMPLATE_BLURBS,
        "source_options": wizard_logic.SOURCE_OPTIONS,
        "remote_type_options": wizard_logic.REMOTE_TYPE_OPTIONS,
        "employment_type_options": wizard_logic.EMPLOYMENT_TYPE_OPTIONS,
    }
