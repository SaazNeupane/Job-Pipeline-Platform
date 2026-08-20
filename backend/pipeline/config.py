"""DB-backed replacement for the old file-based pipeline/config.py. Dataclasses are kept
byte-for-byte identical to the original (see job-pipeline/pipeline/config.py), and
load_profile(user)/load_secrets(user) keep the exact same one-argument signature the
original file-based version had -- every reused pipeline module (search.py, filter.py,
sheet_log.py, cold_email.py, cover_letter.py, tailor_resume.py, daily_report.py,
swipe_actions.py, ...) calls load_profile(user)/load_secrets(user) with just the user id and
was copied over completely unmodified. The DB session itself is threaded in via a
contextvar (set_session/db_session, below) rather than an extra function parameter --
app/main.py sets it once per request or per background job, before any pipeline module
runs, and clears it after. This is the one deliberate deviation from "just swap the storage
backend": a contextvar over a required parameter, specifically so the copied pipeline files
didn't need touching at all."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field, fields

from sqlalchemy.orm import Session

from app.crypto import decrypt
from app.models import Profile as ProfileRow
from app.models import Secret as SecretRow
from app.models import User as UserRow

_session_var: ContextVar[Session | None] = ContextVar("_session_var", default=None)


def set_session(db: Session | None) -> None:
    _session_var.set(db)


def get_session() -> Session | None:
    return _session_var.get()


def _require_session() -> Session:
    db = _session_var.get()
    if db is None:
        raise RuntimeError(
            "No DB session set -- call pipeline.config.set_session(db) before running "
            "any pipeline module that loads a profile/secrets."
        )
    return db

SECRET_KEYS = [
    "GMAIL_OAUTH_CLIENT_ID",
    "GMAIL_OAUTH_CLIENT_SECRET",
    "GMAIL_OAUTH_REFRESH_TOKEN",
    "GEMINI_API_KEY",
    "ADZUNA_APP_ID",
    "ADZUNA_APP_KEY",
]


@dataclass
class Lane:
    name: str
    resume: str
    keywords: list[str]
    sources: list[str]
    seniority_max: str | None = None
    industries: list[str] = field(default_factory=list)
    synonym_groups: list[list[str]] = field(default_factory=list)
    relabel_titles_to_posting: bool = False
    required_keywords: list[str] | None = None
    max_years_experience: int | None = None
    radius_km: float | None = None
    remote_types: list[str] = field(default_factory=list)
    employment_types: list[str] = field(default_factory=list)
    salary_min: float | None = None
    salary_max: float | None = None
    min_match_score: float | None = None


@dataclass
class ColdEmailConfig:
    daily_cap_week1: int
    daily_cap_week3plus: int
    ramp_start_date: str
    search_keywords: list[str] = field(default_factory=list)


@dataclass
class Applicant:
    first_name: str
    last_name: str
    country: str
    latitude: float | None = None
    longitude: float | None = None
    address: str = ""


@dataclass
class Profile:
    user: str
    sheet_id: str
    gmail_address: str
    report_email: str
    lanes: list[Lane]
    cold_email: ColdEmailConfig
    applicant: Applicant
    greenhouse_boards: list[str] = field(default_factory=list)
    lever_companies: list[str] = field(default_factory=list)
    ashby_boards: list[str] = field(default_factory=list)
    # Promoted from env-var spikes (WORKDAY_BOARDS/SMARTRECRUITERS_COMPANIES/etc in
    # run_pipeline.py, pre-promotion) -- same string shapes their search_* functions
    # in search.py already expect.
    workday_boards: list[str] = field(default_factory=list)
    smartrecruiters_companies: list[str] = field(default_factory=list)
    workable_accounts: list[str] = field(default_factory=list)
    recruitee_companies: list[str] = field(default_factory=list)
    breezy_companies: list[str] = field(default_factory=list)
    company_site_trackers: list[str] = field(default_factory=list)
    adzuna_country: str = "us"
    target_countries: list[str] = field(default_factory=lambda: ["ca"])
    # Optional finer filter within target_countries -- province/state codes or names
    # (see pipeline/filter.py's _matches_target_regions). Empty means no region
    # restriction, same "no filter" default as every other optional setting here.
    target_regions: list[str] = field(default_factory=list)
    apply_daily_cap: int = 15
    # "free" | "paid" -- read off the owning User row (see app/models.py's User.plan), not
    # stored on ProfileRow itself. Used by run_pipeline.py to enforce PLAN_ALLOWED_SOURCES/
    # PLAN_APPLY_DAILY_CAP_LIMITS at the one place every caller (daily cron, manual run-now)
    # funnels through, so a stale wizard-saved source list or apply_daily_cap can't bypass
    # a plan's real limit just because it was set before a downgrade.
    plan: str = "free"
    github_repo: str = ""
    # Lane name -> parsed resume JSON dict (the old build_resume_json() output). The
    # original file-based Profile had a resume_path(lane_name) -> Path method that
    # swipe_actions.py/cold_email.py read+json.loads() themselves; there's no per-user
    # filesystem here, so those two call sites were changed to `profile.resumes[name]`
    # directly instead, and this dict is populated from ProfileRow.resumes_json.
    resumes: dict[str, dict] = field(default_factory=dict)


def load_profile(user: str) -> Profile:
    """user is the app's internal user id (users.id), not a filesystem slug. Requires
    set_session(db) to have been called first (see module docstring)."""
    db = _require_session()
    user_id = user
    row = db.query(ProfileRow).filter(ProfileRow.user_id == user_id).one_or_none()
    if row is None:
        raise LookupError(f"No profile row for user_id {user_id!r}")

    applicant_fields = {f.name for f in fields(Applicant)}
    applicant = Applicant(**{k: v for k, v in (row.applicant_json or {}).items() if k in applicant_fields})

    user_row = db.query(UserRow).filter(UserRow.id == user_id).one_or_none()
    plan = user_row.plan if user_row is not None else "free"

    return Profile(
        user=user_id,
        plan=plan,
        sheet_id=row.sheet_id,
        gmail_address=row.gmail_address,
        report_email=row.report_email,
        lanes=[Lane(**lane_raw) for lane_raw in (row.lanes_json or [])],
        cold_email=ColdEmailConfig(**(row.cold_email_json or {})),
        applicant=applicant,
        greenhouse_boards=list(row.greenhouse_boards_json or []),
        lever_companies=list(row.lever_companies_json or []),
        ashby_boards=list(row.ashby_boards_json or []),
        workday_boards=list(row.workday_boards_json or []),
        smartrecruiters_companies=list(row.smartrecruiters_companies_json or []),
        workable_accounts=list(row.workable_accounts_json or []),
        recruitee_companies=list(row.recruitee_companies_json or []),
        breezy_companies=list(row.breezy_companies_json or []),
        company_site_trackers=list(row.company_site_trackers_json or []),
        adzuna_country=row.adzuna_country or "us",
        target_countries=list(row.target_countries_json or ["ca"]),
        target_regions=list(row.target_regions_json or []),
        apply_daily_cap=row.apply_daily_cap,
        github_repo=row.github_repo or "",
        resumes=dict(row.resumes_json or {}),
    )


def load_secrets(user: str) -> dict[str, str]:
    """Decrypts every stored Secret row for this user. Unlike the old file-based version,
    there's no os.environ fallback here -- each user's own Gemini/Adzuna keys are theirs,
    not a shared CI secret, so there's nothing meaningful to fall back to. Requires
    set_session(db) to have been called first (see module docstring)."""
    db = _require_session()
    rows = db.query(SecretRow).filter(SecretRow.user_id == user).all()
    return {row.key_name: decrypt(row.value_encrypted) for row in rows if row.key_name in SECRET_KEYS}
