"""SQLAlchemy models. Mirrors the old profile.yaml shape closely (lanes/applicant/cold_email
stored as JSONB) rather than fully normalizing lanes into their own table -- profile.yaml's
nested structure maps directly onto pipeline.config's dataclasses, and JSONB keeps that
mapping trivial instead of fighting an ORM join for something that's never queried by lane
field, only ever loaded whole per user."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy import Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.time_utils import utcnow


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    profile: Mapped["Profile | None"] = relationship(back_populates="user", uselist=False)
    oauth_credentials: Mapped[list["OAuthCredential"]] = relationship(back_populates="user")
    secrets: Mapped[list["Secret"]] = relationship(back_populates="user")
    wizard_draft: Mapped["WizardDraft | None"] = relationship(back_populates="user", uselist=False)


class Profile(Base):
    """One row per user, mirrors config.Profile/Lane/ColdEmailConfig/Applicant."""

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)

    sheet_id: Mapped[str] = mapped_column(String, default="")
    gmail_address: Mapped[str] = mapped_column(String, default="")
    report_email: Mapped[str] = mapped_column(String, default="")
    adzuna_country: Mapped[str] = mapped_column(String, default="us")
    apply_daily_cap: Mapped[int] = mapped_column(Integer, default=15)
    github_repo: Mapped[str] = mapped_column(String, default="")
    # UTC hour (0-23) the scheduler runs this user's daily pipeline in -- see
    # main.py's active_users(), called hourly by .github/workflows/daily.yml.
    run_hour_utc: Mapped[int] = mapped_column(Integer, default=14)

    # JSONB blobs matching the dataclass shapes in pipeline/config.py verbatim --
    # lanes: list[Lane]-shaped dicts, cold_email: ColdEmailConfig-shaped dict,
    # applicant: Applicant-shaped dict, target_countries/greenhouse_boards/etc: lists.
    lanes_json: Mapped[list] = mapped_column(JSON, default=list)
    cold_email_json: Mapped[dict] = mapped_column(JSON, default=dict)
    applicant_json: Mapped[dict] = mapped_column(JSON, default=dict)
    greenhouse_boards_json: Mapped[list] = mapped_column(JSON, default=list)
    lever_companies_json: Mapped[list] = mapped_column(JSON, default=list)
    ashby_boards_json: Mapped[list] = mapped_column(JSON, default=list)
    target_countries_json: Mapped[list] = mapped_column(JSON, default=lambda: ["ca"])
    # lane name -> parsed resume JSON dict (build_resume_json()'s output), replaces the old
    # per-user resume_<lane>.json files -- see pipeline/config.py's Profile.resumes docstring.
    resumes_json: Mapped[dict] = mapped_column(JSON, default=dict)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship(back_populates="profile")


class OAuthCredential(Base):
    """Per-user, per-provider OAuth refresh token. refresh_token_encrypted is Fernet-encrypted
    (see app/crypto.py) -- never store the raw token."""

    __tablename__ = "oauth_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String, default="google")  # only "google" for now
    scopes: Mapped[str] = mapped_column(String, default="")  # space-joined, as Google returns
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    granted_email: Mapped[str] = mapped_column(String, default="")  # which Google account granted this
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User"] = relationship(back_populates="oauth_credentials")


class Secret(Base):
    """User-supplied API keys (Gemini, Adzuna), Fernet-encrypted at rest. One row per key
    name, mirrors config.SECRET_KEYS."""

    __tablename__ = "secrets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    key_name: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "GEMINI_API_KEY"
    value_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped["User"] = relationship(back_populates="secrets")


class Posting(Base):
    """Source of truth for a user's job-search results, replacing the old
    swipe_queue/pending_approval/applied_jobs/dismissed_jobs Google Sheet tabs. One row per
    (user, posting_key), status transitions in place (queued -> pending -> applied, or
    queued/pending -> dismissed) instead of the old copy-to-new-tab + delete-from-old-tab
    dance, which was two non-atomic Sheets API calls. status_history keeps a lightweight
    audit trail of past transitions since collapsing to one row loses the old per-tab
    history. Mirrored (best-effort, non-blocking) to the user's Google Sheet by
    pipeline/postings_store.py -- this table is authoritative, the Sheet is a read-only copy."""

    __tablename__ = "postings"
    __table_args__ = (
        UniqueConstraint("user_id", "posting_key", name="uq_postings_user_posting_key"),
        Index("ix_postings_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    posting_key: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # queued | pending | applied | dismissed

    date: Mapped[str] = mapped_column(String, default="")
    lane: Mapped[str] = mapped_column(String, default="")
    company: Mapped[str] = mapped_column(String, default="")
    role: Mapped[str] = mapped_column(String, default="")
    source: Mapped[str] = mapped_column(String, default="")
    location: Mapped[str] = mapped_column(String, default="")

    # swipe_queue-origin fields
    job_id: Mapped[str] = mapped_column(String, default="")
    application_url: Mapped[str] = mapped_column(String, default="")
    description_text: Mapped[str] = mapped_column(Text, default="")
    matched_terms: Mapped[str] = mapped_column(String, default="")
    match_score: Mapped[float] = mapped_column(Numeric, default=0)
    posted_date: Mapped[str] = mapped_column(String, default="")
    remote_type: Mapped[str] = mapped_column(String, default="")
    employment_type: Mapped[str] = mapped_column(String, default="")
    salary_min: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    required_years: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # pending-stage fields
    reason_held: Mapped[str] = mapped_column(String, default="")
    resume_version: Mapped[str] = mapped_column(String, default="")
    resume_link: Mapped[str] = mapped_column(String, default="")
    cover_letter: Mapped[str] = mapped_column(Text, default="")
    content_flags: Mapped[str] = mapped_column(String, default="")

    # applied-stage fields
    application_status: Mapped[str] = mapped_column(String, default="")
    contact_emailed: Mapped[str] = mapped_column(String, default="")
    email_sent_at: Mapped[str] = mapped_column(String, default="")

    dismissed_at: Mapped[str] = mapped_column(String, default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    status_history: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ColdEmail(Base):
    """Per-user cold-email send log, replacing the old cold_emails Google Sheet tab. A
    posting can be both a normal lane match (Posting row) and independently cold-emailed --
    two separate tracks against the same posting_key, not one lifecycle, hence its own table
    rather than folding into Posting."""

    __tablename__ = "cold_emails"
    __table_args__ = (
        Index("ix_cold_emails_user_posting_key", "user_id", "posting_key"),
        Index("ix_cold_emails_user_date", "user_id", "date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    posting_key: Mapped[str] = mapped_column(String, default="")
    date: Mapped[str] = mapped_column(String, default="")
    lane: Mapped[str] = mapped_column(String, default="")
    company: Mapped[str] = mapped_column(String, default="")
    location: Mapped[str] = mapped_column(String, default="")
    contact_name: Mapped[str] = mapped_column(String, default="")
    contact_email: Mapped[str] = mapped_column(String, default="")
    sent_at: Mapped[str] = mapped_column(String, default="")
    thread_id: Mapped[str] = mapped_column(String, default="")
    # "Y" / "N" / "" (unknown), not a real boolean -- matches cold_email.py's own sentinel
    # values (e.g. `row.get("bounced") in ("Y", "N")` to mean "checked at all"), carried
    # over unchanged from the Sheets-tab era so that call site never needed to change.
    bounced: Mapped[str] = mapped_column(String, default="")
    replied: Mapped[str] = mapped_column(String, default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class DailySummary(Base):
    """One row per user per day, replacing the old daily_summary Google Sheet tab."""

    __tablename__ = "daily_summaries"
    __table_args__ = (Index("ix_daily_summaries_user_date", "user_id", "date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    date: Mapped[str] = mapped_column(String, default="")
    applied_count: Mapped[int] = mapped_column(Integer, default=0)
    pending_approval_count: Mapped[int] = mapped_column(Integer, default=0)
    emails_sent: Mapped[int] = mapped_column(Integer, default=0)
    queued_count: Mapped[int] = mapped_column(Integer, default=0)
    awaiting_apply_count: Mapped[int] = mapped_column(Integer, default=0)
    cold_email_scanned: Mapped[int] = mapped_column(Integer, default=0)
    cold_email_eligible: Mapped[int] = mapped_column(Integer, default=0)
    cold_email_matched: Mapped[int] = mapped_column(Integer, default=0)
    cold_email_contacts_found: Mapped[int] = mapped_column(Integer, default=0)
    total_postings_found: Mapped[int] = mapped_column(Integer, default=0)
    total_matched: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class Invite(Base):
    """Single-use signup invite codes, replacing the old single shared INVITE_CODE env var --
    that gave every invitee the same code with no way to revoke or track just one, which was
    fine for a friends-and-family batch but not a real invite system. Minted via the
    internal-only /api/internal/invites route (same shared-secret auth as the rest of
    /api/internal/*), consumed atomically by signup()."""

    __tablename__ = "invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class WizardDraft(Base):
    """In-progress setup wizard state, replaces the old per-user .wizard_draft.json file."""

    __tablename__ = "wizard_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    draft_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship(back_populates="wizard_draft")
