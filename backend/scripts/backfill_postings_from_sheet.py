"""One-time import of an existing user's Google Sheet result data into Postgres, run once
before cutting the app's reads/writes over from sheet_log.py to pipeline/postings_store.py
(see the storage-migration plan). Reads all 6 tabs via sheet_log.get_rows -- still present at
the time this runs -- and inserts Posting/ColdEmail/DailySummary rows. Never modifies the
Sheet; it stays a durable copy either way.

Usage (from backend/):
  python -m scripts.backfill_postings_from_sheet <user-email>
"""

from __future__ import annotations

import sys
from datetime import datetime

from app.db import SessionLocal
from app.models import ColdEmail, DailySummary, Posting, User
from pipeline import config as pipeline_config
from pipeline import sheet_log

_STATUS_BY_TAB = {
    "swipe_queue": "queued",
    "pending_approval": "pending",
    "applied_jobs": "applied",
    "dismissed_jobs": "dismissed",
}

_POSTING_FIELDS = [
    "posting_key", "date", "lane", "company", "role", "source", "location", "job_id",
    "application_url", "description_text", "matched_terms", "posted_date", "remote_type",
    "employment_type", "salary_min", "salary_max", "required_years", "reason_held",
    "resume_version", "resume_link", "cover_letter", "content_flags", "application_status",
    "contact_emailed", "email_sent_at", "dismissed_at", "notes",
]


def _to_number(value, cast):
    if value in (None, ""):
        return None
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def _backfill_postings(db, user_id: str) -> None:
    seen_keys: set[str] = set()
    for tab, status in _STATUS_BY_TAB.items():
        rows = sheet_log.get_rows(user_id, tab)
        inserted = 0
        for row in rows:
            posting_key = row.get("posting_key", "")
            if not posting_key:
                continue
            if posting_key in seen_keys:
                print(f"  [{tab}] skipping duplicate posting_key across tabs: {posting_key!r}")
                continue
            seen_keys.add(posting_key)

            fields = {k: row.get(k, "") for k in _POSTING_FIELDS}
            fields["salary_min"] = _to_number(row.get("salary_min"), float)
            fields["salary_max"] = _to_number(row.get("salary_max"), float)
            fields["required_years"] = _to_number(row.get("required_years"), int)

            db.add(Posting(
                user_id=user_id, status=status,
                status_history=[{"status": status, "at": datetime.utcnow().isoformat()}],
                **fields,
            ))
            inserted += 1
        db.commit()
        print(f"  [{tab}] -> status={status!r}: {inserted} row(s) imported (of {len(rows)} read)")


def _backfill_cold_emails(db, user_id: str) -> None:
    rows = sheet_log.get_rows(user_id, "cold_emails")
    cols = [
        "posting_key", "date", "lane", "company", "location", "contact_name", "contact_email",
        "sent_at", "thread_id", "bounced", "replied", "notes",
    ]
    for row in rows:
        db.add(ColdEmail(user_id=user_id, **{k: row.get(k, "") for k in cols}))
    db.commit()
    print(f"  [cold_emails]: {len(rows)} row(s) imported")


def _backfill_daily_summaries(db, user_id: str) -> None:
    rows = sheet_log.get_rows(user_id, "daily_summary")
    int_cols = [
        "applied_count", "pending_approval_count", "emails_sent", "queued_count",
        "awaiting_apply_count", "cold_email_scanned", "cold_email_eligible",
        "cold_email_matched", "cold_email_contacts_found",
    ]
    for row in rows:
        fields = {"date": row.get("date", ""), "errors": row.get("errors", ""), "notes": row.get("notes", "")}
        for col in int_cols:
            fields[col] = _to_number(row.get(col), int) or 0
        db.add(DailySummary(user_id=user_id, **fields))
    db.commit()
    print(f"  [daily_summary]: {len(rows)} row(s) imported")


def main(email: str) -> None:
    db = SessionLocal()
    pipeline_config.set_session(db)
    try:
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is None:
            raise SystemExit(f"No user found with email {email!r}")

        print(f"Backfilling postings/cold_emails/daily_summaries for {email!r} (user_id={user.id})")
        _backfill_postings(db, user.id)
        _backfill_cold_emails(db, user.id)
        _backfill_daily_summaries(db, user.id)
        print("Done. The Sheet was not modified.")
    finally:
        pipeline_config.set_session(None)
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m scripts.backfill_postings_from_sheet <user-email>")
    main(sys.argv[1])
