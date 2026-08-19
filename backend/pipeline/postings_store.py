"""Source of truth for a user's job-search results (postings/cold emails/daily summaries),
replacing sheet_log.py's read+write role. Postgres is authoritative; every write here also
fires a best-effort, non-blocking mirror write to the user's Google Sheet afterward (see
_mirror_to_sheet) so the "your data lives in your own Sheet" story still holds, but the app
itself never blocks on or depends on the Sheets API for correctness.

Call sites all follow the same session-threading convention as pipeline/config.py: read the
DB session via pipeline.config._require_session(), set once per request/background job by
whoever's already calling load_profile()/load_secrets() in the same call path -- no new
db: Session parameter needed anywhere.

Returns are plain dicts (not ORM objects) so existing call-site `row.get("posting_key")`-style
access, carried over from the Sheets-tab era, doesn't need to change."""

from __future__ import annotations

from decimal import Decimal

from app.models import ColdEmail as ColdEmailRow
from app.models import DailySummary as DailySummaryRow
from app.models import Posting as PostingRow
from app.time_utils import utcnow
from pipeline.config import _require_session, load_profile
from pipeline.filter import posting_fingerprint
from pipeline.google_auth import submit_for_user

# status -> the Sheet tab that status's rows mirror to, matching setup_sheet.py's tab names.
TAB_BY_STATUS = {
    "queued": "swipe_queue",
    "pending": "pending_approval",
    "applied": "applied_jobs",
    "dismissed": "dismissed_jobs",
}

# Per-tab column lists, matching setup_sheet.py's headers exactly -- sheet_log.append_row
# raises on any key not in a tab's header, so the mirror must filter to just these per tab.
_TAB_COLUMNS = {
    "swipe_queue": [
        "posting_key", "date", "lane", "company", "role", "source", "job_id", "location",
        "posted_date", "application_url", "description_text", "matched_terms", "remote_type",
        "employment_type", "salary_min", "salary_max", "required_years",
    ],
    "pending_approval": [
        "posting_key", "date", "lane", "company", "role", "source", "location", "reason_held",
        "resume_version", "application_url", "notes", "resume_link", "cover_letter",
        "posted_date", "content_flags", "required_years",
    ],
    "applied_jobs": [
        "posting_key", "date", "lane", "company", "role", "source", "location",
        "application_status", "resume_version", "contact_emailed", "email_sent_at", "notes",
        "posted_date", "content_flags",
    ],
    "dismissed_jobs": [
        "posting_key", "date", "lane", "company", "role", "source", "location", "reason_held",
        "dismissed_at", "notes",
    ],
    "cold_emails": [
        "posting_key", "date", "lane", "company", "location", "contact_name", "contact_email",
        "sent_at", "thread_id", "bounced", "replied", "notes",
    ],
    "daily_summary": [
        "date", "applied_count", "pending_approval_count", "emails_sent", "errors", "notes",
        "queued_count", "awaiting_apply_count", "cold_email_scanned", "cold_email_eligible",
        "cold_email_matched", "cold_email_contacts_found", "total_postings_found", "total_matched",
    ],
}

_POSTING_COLUMNS = [
    "posting_key", "status", "date", "lane", "company", "role", "source", "location", "job_id",
    "application_url", "description_text", "matched_terms", "match_score", "posted_date", "remote_type",
    "employment_type", "salary_min", "salary_max", "required_years", "reason_held",
    "resume_version", "resume_link", "cover_letter", "content_flags", "application_status",
    "contact_emailed", "email_sent_at", "dismissed_at", "notes", "outcome", "outcome_updated_at",
]

OUTCOME_VALUES = {"", "responded", "interview", "offer", "rejected"}


def _posting_to_dict(row: PostingRow) -> dict:
    return {col: getattr(row, col) for col in _POSTING_COLUMNS}


def _cold_email_to_dict(row: ColdEmailRow) -> dict:
    cols = [
        "posting_key", "date", "lane", "company", "location", "contact_name", "contact_email",
        "sent_at", "thread_id", "bounced", "replied", "notes",
    ]
    return {col: getattr(row, col) for col in cols}


def _sheet_row_for_tab(tab: str, fields: dict) -> dict:
    """Filters+blanks a full row dict down to just the columns a given Sheet tab actually
    has, converting None to "" (Sheets has no null, only blank cells). salary_min/salary_max
    come back from the Numeric DB columns as Decimal (see PostingRow in app/models.py) --
    the Sheets API request body is JSON-encoded and json.dumps can't serialize Decimal,
    so it's converted to float here specifically for the mirror write (Postgres keeps the
    original Decimal, this only affects the Sheet copy)."""
    def _value(col: str):
        v = fields.get(col)
        if v is None:
            return ""
        if isinstance(v, Decimal):
            return float(v)
        return v

    return {col: _value(col) for col in _TAB_COLUMNS[tab]}


def _mirror_worker(user: str, fn) -> None:
    """Runs fn() with its own DB session bound via the same contextvar convention as every
    other background thread in this codebase (see dashboard.py's _regenerate_in_background).
    Never raises -- a mirror failure is logged and dropped, the DB write already succeeded
    and remains authoritative."""
    from app.db import SessionLocal
    from pipeline import config as pipeline_config

    db = SessionLocal()
    pipeline_config.set_session(db)
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 -- best-effort mirror, never blocks/fails the caller
        print(f"[postings_store] Sheet mirror failed for user={user}: {exc}")
    finally:
        pipeline_config.set_session(None)
        db.close()


# A run can queue 15+ postings in a tight loop, each firing its own mirror write. Confirmed
# live 2026-08-16: spawning one raw thread per write crashed the whole interpreter with
# STATUS_HEAP_CORRUPTION (0xc0000374, Windows Error Reporting). Cutting concurrency to 2
# workers still crashed (STATUS_ACCESS_VIOLATION, 0xc0000005) -- root cause is
# google_auth.py's _service_cache: it caches and shares ONE googleapiclient service object
# (wrapping an httplib2.Http connection) per user across every caller, and httplib2 is not
# thread-safe. Any two threads doing concurrent I/O through that same cached service can
# corrupt the interpreter's native heap. Routed through google_auth.submit_for_user (this
# user's own single-worker pool, shared with every other background Google-API call for the
# same user -- see that module's own docstring) after a second SIGSEGV in production on
# 2026-08-16 -- swipe.py's /like and dashboard.py's /retry each spawned their own raw thread
# into generate_liked_materials/retry_generation, which also hit this same cache, so a
# private mirror-only executor wasn't enough: two different single-worker pools for the SAME
# user can still race each other on that user's cached service.


def _fire_mirror(user: str, fn) -> None:
    submit_for_user(user, _mirror_worker, user, fn)


def _mirror_create(user: str, tab: str, fields: dict) -> None:
    from pipeline.sheet_log import append_row

    def _do():
        append_row(user, tab, _sheet_row_for_tab(tab, fields))

    _fire_mirror(user, _do)


def _mirror_transition(user: str, old_tab: str, new_tab: str, posting_key: str, fields: dict) -> None:
    from pipeline.sheet_log import append_row, delete_row

    def _do():
        append_row(user, new_tab, _sheet_row_for_tab(new_tab, fields))
        if not delete_row(user, old_tab, "posting_key", posting_key):
            print(
                f"[postings_store] mirror: appended to {new_tab} but couldn't find "
                f"the {old_tab} row for {posting_key} to remove — check the sheet."
            )

    _fire_mirror(user, _do)


def _mirror_update(user: str, tab: str, posting_key: str, updates: dict) -> None:
    from pipeline.sheet_log import update_row

    def _do():
        update_row(user, tab, "posting_key", posting_key, updates)

    _fire_mirror(user, _do)


def _mirror_bulk_dismiss(user: str, posting_keys: list[str], fields_by_key: dict[str, dict]) -> None:
    from pipeline.sheet_log import append_row, delete_rows

    def _do():
        for key in posting_keys:
            append_row(user, "dismissed_jobs", _sheet_row_for_tab("dismissed_jobs", fields_by_key[key]))
        delete_rows(user, "pending_approval", "posting_key", set(posting_keys))

    _fire_mirror(user, _do)


# ---------------------------------------------------------------------------
# Postings
# ---------------------------------------------------------------------------


def get_posting(user: str, posting_key: str) -> dict | None:
    db = _require_session()
    row = db.query(PostingRow).filter(PostingRow.user_id == user, PostingRow.posting_key == posting_key).one_or_none()
    return _posting_to_dict(row) if row else None


def get_postings(user: str, status: str | None = None) -> list[dict]:
    db = _require_session()
    q = db.query(PostingRow).filter(PostingRow.user_id == user)
    if status is not None:
        q = q.filter(PostingRow.status == status)
    return [_posting_to_dict(r) for r in q.all()]


def get_postings_multi(user: str, statuses: list[str]) -> dict[str, list[dict]]:
    return {status: get_postings(user, status=status) for status in statuses}


def create_posting(user: str, status: str, fields: dict) -> dict:
    db = _require_session()
    row = PostingRow(
        user_id=user, status=status,
        status_history=[{"status": status, "at": utcnow().isoformat()}],
        **{k: v for k, v in fields.items() if k in _POSTING_COLUMNS and k not in ("status", "posting_key")},
        posting_key=fields["posting_key"],
    )
    db.add(row)
    db.commit()
    result = _posting_to_dict(row)

    _mirror_create(user, TAB_BY_STATUS[status], result)
    return result


def transition_posting(user: str, posting_key: str, new_status: str, updates: dict | None = None) -> dict | None:
    """Single-transaction status change, replacing the old append-to-new-tab +
    delete-from-old-tab two-step (non-atomic against the Sheets API -- a crash between the
    two calls could duplicate or lose the row)."""
    db = _require_session()
    row = db.query(PostingRow).filter(PostingRow.user_id == user, PostingRow.posting_key == posting_key).one_or_none()
    if row is None:
        return None

    old_status = row.status
    old_tab = TAB_BY_STATUS[old_status]
    new_tab = TAB_BY_STATUS[new_status]

    row.status = new_status
    row.status_history = [*(row.status_history or []), {"status": new_status, "at": utcnow().isoformat()}]
    for key, value in (updates or {}).items():
        if key in _POSTING_COLUMNS and key not in ("status", "posting_key"):
            setattr(row, key, value)
    db.commit()
    result = _posting_to_dict(row)

    _mirror_transition(user, old_tab, new_tab, posting_key, result)
    return result


def update_posting(user: str, posting_key: str, updates: dict) -> dict | None:
    """In-place field update with no status change (e.g. filling in resume_link/cover_letter
    after generation, or resetting reason_held on retry)."""
    db = _require_session()
    row = db.query(PostingRow).filter(PostingRow.user_id == user, PostingRow.posting_key == posting_key).one_or_none()
    if row is None:
        return None

    for key, value in updates.items():
        if key in _POSTING_COLUMNS and key not in ("status", "posting_key"):
            setattr(row, key, value)
    db.commit()
    result = _posting_to_dict(row)

    _mirror_update(user, TAB_BY_STATUS[row.status], posting_key, updates)
    return result


def set_posting_outcome(user: str, posting_key: str, outcome: str) -> dict | None:
    """outcome must be one of OUTCOME_VALUES -- validated by the caller (the route), not
    here, so this stays a plain data-layer write like every other function in this file."""
    return update_posting(user, posting_key, {"outcome": outcome, "outcome_updated_at": utcnow().isoformat(timespec="seconds")})


def get_outcome_stats(user: str) -> dict:
    """Interviews/responses per application, grouped by lane and by source -- the
    foundational metric behind any "quality over quantity" claim (see Posting.outcome's own
    docstring). Only counts postings that ever reached "applied" or later (queued/pending
    postings haven't been decided on yet, dismissed ones were never applied to) --
    PostingRow.status alone isn't enough since a posting can be dismissed AFTER being
    applied to in principle, so this counts anything with a non-empty application_status
    (only ever set once a posting is promoted to applied) rather than filtering on
    status == "applied", which would undercount."""
    db = _require_session()
    rows = (
        db.query(PostingRow.lane, PostingRow.source, PostingRow.outcome)
        .filter(PostingRow.user_id == user, PostingRow.application_status != "")
        .all()
    )

    def _bucket(rows_subset) -> dict:
        total = len(rows_subset)
        counts = {"responded": 0, "interview": 0, "offer": 0, "rejected": 0}
        for _, _, outcome in rows_subset:
            if outcome in counts:
                counts[outcome] += 1
        return {"applied": total, **counts}

    by_lane: dict[str, list] = {}
    by_source: dict[str, list] = {}
    for lane, source, outcome in rows:
        by_lane.setdefault(lane or "unknown", []).append((lane, source, outcome))
        by_source.setdefault(source or "unknown", []).append((lane, source, outcome))

    return {
        "overall": _bucket(rows),
        "by_lane": {lane: _bucket(subset) for lane, subset in by_lane.items()},
        "by_source": {source: _bucket(subset) for source, subset in by_source.items()},
    }


def dismiss_postings_bulk(user: str, posting_keys: list[str]) -> int:
    db = _require_session()
    rows = (
        db.query(PostingRow)
        .filter(PostingRow.user_id == user, PostingRow.posting_key.in_(posting_keys), PostingRow.status == "pending")
        .all()
    )
    if not rows:
        return 0

    now = utcnow().isoformat(timespec="seconds")
    fields_by_key = {}
    for row in rows:
        row.status = "dismissed"
        row.dismissed_at = now
        row.status_history = [*(row.status_history or []), {"status": "dismissed", "at": now}]
        fields_by_key[row.posting_key] = _posting_to_dict(row)
    db.commit()

    _mirror_bulk_dismiss(user, list(fields_by_key), fields_by_key)
    return len(rows)


def get_existing_dedupe_keys(user: str, status: str | None = None) -> set[str]:
    db = _require_session()
    q = db.query(PostingRow.posting_key).filter(PostingRow.user_id == user)
    if status is not None:
        q = q.filter(PostingRow.status == status)
    return {row[0] for row in q.all()}


def get_existing_fingerprints(user: str, status: str | None = None) -> set[str]:
    db = _require_session()
    q = db.query(PostingRow.source, PostingRow.company, PostingRow.role, PostingRow.location).filter(
        PostingRow.user_id == user
    )
    if status is not None:
        q = q.filter(PostingRow.status == status)
    return {posting_fingerprint(source, company, role, location) for source, company, role, location in q.all()}


# ---------------------------------------------------------------------------
# Cold emails
# ---------------------------------------------------------------------------


def get_cold_emails(user: str) -> list[dict]:
    db = _require_session()
    rows = db.query(ColdEmailRow).filter(ColdEmailRow.user_id == user).all()
    return [_cold_email_to_dict(r) for r in rows]


def get_cold_email_dedupe_keys(user: str) -> set[str]:
    """Unioned with the local dedupe backup file, same as the old
    sheet_log.get_existing_dedupe_keys(tab="cold_emails") -- a cleared/rolled-back table
    shouldn't reopen the door to a duplicate real send."""
    from pipeline.sheet_log import _load_dedupe_backup, COLD_EMAIL_DEDUPE_BACKUP_PATH

    db = _require_session()
    keys = {row[0] for row in db.query(ColdEmailRow.posting_key).filter(ColdEmailRow.user_id == user).all()}
    return keys | _load_dedupe_backup(COLD_EMAIL_DEDUPE_BACKUP_PATH)


def record_cold_email(user: str, fields: dict) -> dict:
    db = _require_session()
    cols = [
        "posting_key", "date", "lane", "company", "location", "contact_name", "contact_email",
        "sent_at", "thread_id", "bounced", "replied", "notes",
    ]
    row = ColdEmailRow(user_id=user, **{k: v for k, v in fields.items() if k in cols})
    db.add(row)
    db.commit()
    result = _cold_email_to_dict(row)

    _mirror_create(user, "cold_emails", result)
    return result


def update_cold_email(user: str, posting_key: str, updates: dict) -> dict | None:
    db = _require_session()
    row = db.query(ColdEmailRow).filter(ColdEmailRow.user_id == user, ColdEmailRow.posting_key == posting_key).one_or_none()
    if row is None:
        return None
    for key, value in updates.items():
        setattr(row, key, value)
    db.commit()
    result = _cold_email_to_dict(row)

    _mirror_update(user, "cold_emails", posting_key, updates)
    return result


# ---------------------------------------------------------------------------
# Daily summaries
# ---------------------------------------------------------------------------

_SUMMARY_COLUMNS = [
    "date", "applied_count", "pending_approval_count", "emails_sent", "queued_count",
    "awaiting_apply_count", "cold_email_scanned", "cold_email_eligible", "cold_email_matched",
    "cold_email_contacts_found", "total_postings_found", "total_matched", "errors", "notes",
]


def _summary_to_dict(row: DailySummaryRow) -> dict:
    return {col: getattr(row, col) for col in _SUMMARY_COLUMNS}


def get_daily_summaries(user: str) -> list[dict]:
    db = _require_session()
    rows = db.query(DailySummaryRow).filter(DailySummaryRow.user_id == user).order_by(DailySummaryRow.date).all()
    return [_summary_to_dict(r) for r in rows]


def record_daily_summary(user: str, summary: dict) -> dict:
    db = _require_session()
    row = DailySummaryRow(user_id=user, **{k: v for k, v in summary.items() if k in _SUMMARY_COLUMNS})
    db.add(row)
    db.commit()
    result = _summary_to_dict(row)

    load_profile(user)  # fail fast if profile is somehow gone before firing the mirror thread
    _mirror_create(user, "daily_summary", result)
    return result
