"""SQLAlchemy models. Mirrors the old profile.yaml shape closely (lanes/applicant/cold_email
stored as JSONB) rather than fully normalizing lanes into their own table -- profile.yaml's
nested structure maps directly onto pipeline.config's dataclasses, and JSONB keeps that
mapping trivial instead of fighting an ORM join for something that's never queried by lane
field, only ever loaded whole per user."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

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

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

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


class WizardDraft(Base):
    """In-progress setup wizard state, replaces the old per-user .wizard_draft.json file."""

    __tablename__ = "wizard_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    draft_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="wizard_draft")
