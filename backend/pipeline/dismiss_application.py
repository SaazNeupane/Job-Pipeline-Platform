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

from pipeline.sheet_log import append_row, delete_row, delete_rows, get_rows


def dismiss_application(user: str, posting_key: str) -> None:
    """Moves a pending_approval row to dismissed_jobs. Split out from main()
    so the dashboard (webapp/app.py) can call it directly instead of
    shelling out to this script."""
    rows = get_rows(user, "pending_approval")
    match = next((r for r in rows if r.get("posting_key") == posting_key), None)
    if match is None:
        raise SystemExit(f"No pending_approval row found for posting_key={posting_key!r}")

    append_row(user, "dismissed_jobs", {
        "posting_key": match["posting_key"],
        "date": match.get("date", ""),
        "lane": match.get("lane", ""),
        "company": match.get("company", ""),
        "role": match.get("role", ""),
        "source": match.get("source", ""),
        "location": match.get("location", ""),
        "reason_held": match.get("reason_held", ""),
        "dismissed_at": datetime.now().isoformat(timespec="seconds"),
    })

    if not delete_row(user, "pending_approval", "posting_key", posting_key):
        print(
            f"[dismiss_application] Warning: appended to dismissed_jobs but couldn't "
            f"find the pending_approval row for {posting_key} to remove — check the sheet."
        )

    print(f"[dismiss_application] {posting_key} moved to dismissed_jobs.")


def dismiss_applications(user: str, posting_keys: list[str]) -> int:
    """Bulk version -- one get_rows() read, then one append per matched row
    (dismissed_jobs) and a single batched delete_rows() call against
    pending_approval, instead of N full dismiss_application() round trips.
    Used by the dashboard's "Dismiss selected" bulk action. Returns how
    many rows were actually dismissed (posting_keys with no matching
    pending_approval row are silently skipped, same as a race in the
    single-dismiss path)."""
    wanted = set(posting_keys)
    rows = get_rows(user, "pending_approval")
    matches = [r for r in rows if r.get("posting_key") in wanted]
    if not matches:
        return 0

    now = datetime.now().isoformat(timespec="seconds")
    for match in matches:
        append_row(user, "dismissed_jobs", {
            "posting_key": match["posting_key"],
            "date": match.get("date", ""),
            "lane": match.get("lane", ""),
            "company": match.get("company", ""),
            "role": match.get("role", ""),
            "source": match.get("source", ""),
            "location": match.get("location", ""),
            "reason_held": match.get("reason_held", ""),
            "dismissed_at": now,
        })

    delete_rows(user, "pending_approval", "posting_key", {m["posting_key"] for m in matches})
    return len(matches)


def main(user: str, posting_key: str) -> None:
    dismiss_application(user, posting_key)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python dismiss_application.py <user> <posting_key>")
    main(sys.argv[1], sys.argv[2])
