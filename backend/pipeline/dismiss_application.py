"""Permanently set aside a pending_approval row you don't want to pursue.

Unlike just deleting the pending_approval row, this copies it into
dismissed_jobs first -- run_pipeline.py's dedupe check reads that tab too, so
a dismissed posting won't get re-matched, re-tailored, and put back in front
of you on a later run just because its old row is gone.

Usage:
  python dismiss_application.py <user> <posting_key>
"""

from __future__ import annotations

import sys
from datetime import datetime

from pipeline.postings_store import dismiss_postings_bulk, get_posting, transition_posting


def dismiss_application(user: str, posting_key: str) -> None:
    """Moves a pending_approval row to dismissed_jobs. Split out from main()
    so the dashboard (webapp/app.py) can call it directly instead of
    shelling out to this script."""
    match = get_posting(user, posting_key)
    if match is None or match.get("status") != "pending":
        raise SystemExit(f"No pending_approval row found for posting_key={posting_key!r}")

    transition_posting(user, posting_key, "dismissed", {
        "dismissed_at": datetime.now().isoformat(timespec="seconds"),
    })

    print(f"[dismiss_application] {posting_key} moved to dismissed_jobs.")


def dismiss_applications(user: str, posting_keys: list[str]) -> int:
    """Bulk version -- one query, then a single batched UPDATE against
    pending_approval rows, instead of N full dismiss_application() round
    trips. Used by the dashboard's "Dismiss selected" bulk action. Returns
    how many rows were actually dismissed (posting_keys with no matching
    pending_approval row are silently skipped, same as a race in the
    single-dismiss path)."""
    return dismiss_postings_bulk(user, posting_keys)


def main(user: str, posting_key: str) -> None:
    dismiss_application(user, posting_key)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python dismiss_application.py <user> <posting_key>")
    main(sys.argv[1], sys.argv[2])
