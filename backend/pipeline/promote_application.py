"""Record an application you submitted yourself, manually, from a
pending_approval row's resume_link/cover_letter.

The pipeline only ever writes to applied_jobs on its own auto-submit path
(apply.py, when it fills AND submits the form itself) — a manual apply is
otherwise invisible to applied_jobs/daily_summary stats, and the
pending_approval row just sits there indefinitely looking unhandled. This
copies that row into applied_jobs (application_status="submitted_manually")
and removes it from pending_approval.

Usage:
  python promote_application.py <user> <posting_key>
"""

from __future__ import annotations

import sys
from datetime import date

from pipeline.sheet_log import append_row, delete_row, get_rows


def promote_application(user: str, posting_key: str) -> None:
    """Moves a pending_approval row to applied_jobs as submitted_manually.
    Split out from main() so the dashboard (webapp.py) can call it directly
    instead of shelling out to this script."""
    rows = get_rows(user, "pending_approval")
    match = next((r for r in rows if r.get("posting_key") == posting_key), None)
    if match is None:
        raise SystemExit(f"No pending_approval row found for posting_key={posting_key!r}")

    append_row(user, "applied_jobs", {
        "posting_key": match["posting_key"],
        "date": date.today().isoformat(),
        "lane": match.get("lane", ""),
        "company": match.get("company", ""),
        "role": match.get("role", ""),
        "source": match.get("source", ""),
        "location": match.get("location", ""),
        "application_status": "submitted_manually",
        "resume_version": match.get("resume_version", ""),
        "content_flags": match.get("content_flags", ""),
    })

    if not delete_row(user, "pending_approval", "posting_key", posting_key):
        print(
            f"[promote_application] Warning: appended to applied_jobs but couldn't "
            f"find the pending_approval row for {posting_key} to remove — check the sheet."
        )

    print(f"[promote_application] {posting_key} moved to applied_jobs (submitted_manually).")


def main(user: str, posting_key: str) -> None:
    promote_application(user, posting_key)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python promote_application.py <user> <posting_key>")
    main(sys.argv[1], sys.argv[2])
