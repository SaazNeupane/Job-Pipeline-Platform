"""Setup-wizard routes. Ported from the old webapp/app.py's /api/wizard/* handlers --
same underlying logic (pipeline/wizard.py), but keyed off the authenticated user (JWT) and
writing to Postgres instead of a per-user profile.yaml/resume_<lane>.json/secrets.env on
disk. Google OAuth connect itself lives in app/main.py's /api/oauth/google/* -- the wizard
here just checks whether that step has been completed (an oauth_credentials row exists)
before allowing finalize.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.crypto import encrypt
from app.db import SessionLocal, get_db
from app.models import OAuthCredential, Profile as ProfileRow, Secret, User, WizardDraft
from pipeline import config as pipeline_config
from pipeline import setup_sheet
from pipeline import wizard as wizard_logic
from pipeline.filter import SENIORITY_LEVELS
from pipeline.geocode import geocode_address
from pipeline.google_auth import submit_for_user
from app.rate_limit import rate_limit
from pipeline.tailor_resume import render_resume_pdf

router = APIRouter(prefix="/api/wizard", tags=["wizard"])
logger = logging.getLogger(__name__)

_EMPTY_DRAFT = {"lanes": [], "lane_names": [], "lane_labels": {}}

# Nominatim's usage policy caps at ~1 request/second and will ban an abusive endpoint --
# this is a shared, unauthenticated-beyond-JWT relay to it, so a looping client could get
# the whole app's geocoding blocked for everyone, not just themselves.
_rate_limit_geocode = rate_limit(20, 60)


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


@router.post("/geocode", dependencies=[Depends(_rate_limit_geocode)])
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

    def _preset_overrides(p: dict) -> dict | None:
        overrides = {}
        if p.get("keywords"):
            overrides["keywords"] = p["keywords"]
        # "seniority_max" only present in the payload when the user actually touched
        # that preset's override select on the Lanes step -- absent means "keep the
        # preset's own default", present (even as null, for "no limit") means override.
        if "seniority_max" in p:
            overrides["seniority_max"] = p["seniority_max"]
        if "max_years_experience" in p:
            overrides["max_years_experience"] = p["max_years_experience"]
        return overrides or None

    try:
        lanes = [wizard_logic.resolve_preset_lane(p["name"], _preset_overrides(p)) for p in presets]
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
                max_years_experience=c.get("max_years_experience"),
                industries=c.get("industries"),
                min_match_score=c.get("min_match_score"),
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
    draft["workday_boards"] = [str(b).strip() for b in (body.get("workday_boards") or []) if str(b).strip()]
    draft["smartrecruiters_companies"] = [str(b).strip() for b in (body.get("smartrecruiters_companies") or []) if str(b).strip()]
    draft["workable_accounts"] = [str(b).strip() for b in (body.get("workable_accounts") or []) if str(b).strip()]
    draft["recruitee_companies"] = [str(b).strip() for b in (body.get("recruitee_companies") or []) if str(b).strip()]
    draft["breezy_companies"] = [str(b).strip() for b in (body.get("breezy_companies") or []) if str(b).strip()]
    draft["company_site_trackers"] = [str(b).strip() for b in (body.get("company_site_trackers") or []) if str(b).strip()]
    draft["adzuna_country"] = str(body.get("adzuna_country", "ca")).strip().lower()
    draft["target_countries"] = [str(c).strip().lower() for c in (body.get("target_countries") or []) if str(c).strip()]
    draft["target_regions"] = [str(r).strip().lower() for r in (body.get("target_regions") or []) if str(r).strip()]
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
        workday_boards=draft.get("workday_boards"),
        smartrecruiters_companies=draft.get("smartrecruiters_companies"),
        workable_accounts=draft.get("workable_accounts"),
        recruitee_companies=draft.get("recruitee_companies"),
        breezy_companies=draft.get("breezy_companies"),
        company_site_trackers=draft.get("company_site_trackers"),
        adzuna_country=draft.get("adzuna_country", "ca"),
        target_countries=draft.get("target_countries"),
        target_regions=draft.get("target_regions"),
        sheet_id=draft.get("sheet_id", ""),
        gmail_address=granted_email,
        report_email=granted_email,
    )
    resumes = {name: wizard_logic.build_resume_json(draft["shared_resume"], name, lane_names) for name in lane_names}
    # Not part of pipeline.config.Profile's shape (the scheduler is the only reader, see
    # main.py's active_users()) -- attached here only so Review.jsx has something to show.
    profile_dict["run_hour_utc"] = draft.get("run_hour_utc", 14)
    return profile_dict, resumes


@router.get("/resume/preview")
def preview_resume(lane: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Renders the user's current wizard-draft resume (untailored -- no posting exists yet
    to tailor against) as a real PDF via the same render_resume_pdf tailor_resume.py uses for
    the daily pipeline, so the Review step can show exactly what a base resume will look
    like before finalize."""
    draft = _get_or_create_draft(db, user.id).draft_json
    lane_names = draft.get("lane_names") or []
    if not draft.get("shared_resume") or not lane_names:
        raise HTTPException(status.HTTP_409_CONFLICT, "Finish the resume and job-types steps first.")
    lane_name = lane if lane in lane_names else lane_names[0]

    resume = wizard_logic.build_resume_json(draft["shared_resume"], lane_name, lane_names)
    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = Path(tmp_dir) / "preview.pdf"
        render_resume_pdf(resume, pdf_path)
        pdf_bytes = pdf_path.read_bytes()
    return Response(content=pdf_bytes, media_type="application/pdf")


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


def _create_sheet_worker(user_id: str) -> str:
    """Runs on this user's own single-worker executor (see google_auth.submit_for_user),
    not the request thread -- create_sheet()'s get_sheets_service() can hit the same shared
    per-user credentials/service cache a concurrent mirror write or swipe-like for this same
    user is using, and that cache isn't thread-safe. Own DB session since get_credentials()
    needs one on a cache miss and this doesn't run on the request thread that already has
    one bound."""
    db = SessionLocal()
    pipeline_config.set_session(db)
    try:
        return setup_sheet.create_sheet(user_id)
    finally:
        pipeline_config.set_session(None)
        db.close()


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
        sheet_id = profile_row.sheet_id or submit_for_user(user.id, _create_sheet_worker, user.id).result()
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
    profile_row.workday_boards_json = profile_dict["workday_boards"]
    profile_row.smartrecruiters_companies_json = profile_dict["smartrecruiters_companies"]
    profile_row.workable_accounts_json = profile_dict["workable_accounts"]
    profile_row.recruitee_companies_json = profile_dict["recruitee_companies"]
    profile_row.breezy_companies_json = profile_dict["breezy_companies"]
    profile_row.company_site_trackers_json = profile_dict["company_site_trackers"]
    profile_row.target_countries_json = profile_dict["target_countries"]
    profile_row.target_regions_json = profile_dict["target_regions"]
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
        "seniority_levels": SENIORITY_LEVELS,
    }
