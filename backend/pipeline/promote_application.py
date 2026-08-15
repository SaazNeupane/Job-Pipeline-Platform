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

from pipeline.postings_store import get_posting, transition_posting


def promote_application(user: str, posting_key: str) -> None:
    """Moves a pending_approval row to applied_jobs as submitted_manually.
    Split out from main() so the dashboard (webapp.py) can call it directly
    instead of shelling out to this script."""
    match = get_posting(user, posting_key)
    if match is None or match.get("status") != "pending":
        raise SystemExit(f"No pending_approval row found for posting_key={posting_key!r}")

    transition_posting(user, posting_key, "applied", {
        "date": date.today().isoformat(),
        "application_status": "submitted_manually",
    })

    print(f"[promote_application] {posting_key} moved to applied_jobs (submitted_manually).")


def main(user: str, posting_key: str) -> None:
    promote_application(user, posting_key)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python promote_application.py <user> <posting_key>")
    main(sys.argv[1], sys.argv[2])
