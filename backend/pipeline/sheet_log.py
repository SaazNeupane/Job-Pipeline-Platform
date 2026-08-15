"""Google Sheet write/mirror primitives. Postgres (pipeline/postings_store.py) is now the
source of truth for postings/cold_emails/daily_summary -- this module no longer owns reads;
it's called only by postings_store.py's best-effort mirror writes (append_row/update_row/
delete_row/delete_rows) and by scripts/backfill_postings_from_sheet.py (get_rows, kept around
specifically for that one-time-per-new-user import script)."""

from __future__ import annotations

import ssl
import time
from http.client import IncompleteRead
from pathlib import Path

from pipeline.config import load_profile
from pipeline.google_auth import get_sheets_service
from pipeline.json_cache import read_json_file, write_json_file

# Confirmed live 2026-08-13/14: httplib2 (used under the hood by the Google
# API client) dropped its connection mid-read multiple times in one real
# session -- SSLError/IncompleteRead, not an actual error response from
# Google -- surfacing as a raw 500 to the webapp on dashboard loads and
# button clicks. Every case self-resolved on the very next manual retry
# (click the button again / reload the page), so this automates exactly
# that: retry the connection-level failure a few times with backoff before
# giving up. Deliberately narrow -- only network/transport-level
# exceptions, never googleapiclient.errors.HttpError (a real response from
# Google, e.g. a genuine 4xx/5xx or an actual auth/permission problem) --
# retrying a real API error blindly could mask a genuine bug or, for a
# write, risk double-applying it.
_TRANSIENT_NETWORK_ERRORS = (ssl.SSLError, IncompleteRead, ConnectionError, TimeoutError)
_RETRY_DELAYS_SECONDS = (0.5, 1.5, 3.0)


def _execute_with_retry(request):
    """Same known small risk as a manual retry already carried before this
    existed: if a write's response is lost after Google actually applied
    it server-side, retrying re-sends the same write. Not new risk, just
    automated -- clicking a failed button again today has the identical
    characteristic."""
    last_error: Exception | None = None
    for delay in (0.0,) + _RETRY_DELAYS_SECONDS:
        if delay:
            time.sleep(delay)
        try:
            return request.execute()
        except _TRANSIENT_NETWORK_ERRORS as exc:
            last_error = exc
    raise last_error

# cold_emails is the only tab with no other safety margin against a
# duplicate real send if the sheet's history is ever lost — there's no
# auto-submit path anymore to independently bound a duplicate real
# application the way there used to be, so applied_jobs doesn't need this
# same treatment (a manually re-applied job is on the user, not the
# pipeline). This local file is a backup of every posting_key ever cold-emailed,
# independent of the Sheet — a cleared/corrupted cold_emails tab no longer
# means dedup forgets everything, same cache-file pattern already used by
# cover_letter.py/tailor_resume.py's LLM caches.
COLD_EMAIL_DEDUPE_BACKUP_PATH = Path("output/cold_email_dedupe_backup.json")


def _load_dedupe_backup(path: Path) -> set[str]:
    return set(read_json_file(path, []))


def record_cold_email_dedupe_backup(posting_key: str, backup_path: Path = COLD_EMAIL_DEDUPE_BACKUP_PATH) -> None:
    """Call right after a real cold_emails row is appended — the backup only
    needs to know about sends that actually happened."""
    keys = _load_dedupe_backup(backup_path)
    keys.add(posting_key)
    write_json_file(backup_path, sorted(keys))


def append_row(user: str, tab: str, row: dict) -> None:
    """Append one row, mapping row's keys to the tab's actual header order
    so callers never need to know column positions. Unknown keys in `row`
    are an error (likely a typo); missing headers are written as blanks."""
    profile = load_profile(user)
    service = get_sheets_service(user)

    header_result = _execute_with_retry(service.spreadsheets().values().get(
        spreadsheetId=profile.sheet_id, range=f"{tab}!1:1"
    ))
    header = header_result.get("values", [[]])[0]

    unknown = set(row) - set(header)
    if unknown:
        raise ValueError(f"'{tab}' tab has no column(s) {unknown} — check setup_sheet.py headers")

    values = [row.get(col, "") for col in header]
    # OVERWRITE, not INSERT_ROWS — real root-cause fix for the white-on-
    # white bug (confirmed live 2026-08-06, after patching it after every
    # clear+run cycle got old): INSERT_ROWS creates a genuinely NEW row,
    # which copies formatting from the row above it (the header,
    # white-on-dark) rather than reusing setup_sheet.format_sheet's
    # pre-set dark-text formatting on that row position. OVERWRITE instead
    # finds the next empty row within the existing table and writes into
    # it — since format_sheet() pre-formats rows 2 through
    # MAX_FORMATTED_ROWS (2000) with dark text regardless of whether they
    # have a value yet, that pre-set formatting is what actually gets
    # used, no matter how many times the tab is cleared to zero rows in
    # between. Confirmed live: cleared a tab, re-ran format_sheet once,
    # then appended via OVERWRITE — the new row picked up the correct
    # dark text immediately, no manual re-formatting needed afterward.
    _execute_with_retry(service.spreadsheets().values().append(
        spreadsheetId=profile.sheet_id,
        range=tab,
        valueInputOption="RAW",
        insertDataOption="OVERWRITE",
        body={"values": [values]},
    ))


def delete_row(user: str, tab: str, match_column: str, match_value: str) -> bool:
    """Finds the first row where match_column == match_value and deletes it
    entirely (rows below shift up). Returns whether a matching row was
    found. Used by promote_application.py to remove a pending_approval row
    once it's been copied over to applied_jobs."""
    profile = load_profile(user)
    service = get_sheets_service(user)

    result = _execute_with_retry(service.spreadsheets().values().get(spreadsheetId=profile.sheet_id, range=tab))
    rows = result.get("values", [])
    if not rows:
        return False

    header = rows[0]
    match_index = header.index(match_column)

    for sheet_row_number, row in enumerate(rows[1:], start=2):
        if match_index < len(row) and row[match_index] == match_value:
            metadata = _execute_with_retry(service.spreadsheets().get(spreadsheetId=profile.sheet_id))
            gid = next(s["properties"]["sheetId"] for s in metadata["sheets"] if s["properties"]["title"] == tab)
            _execute_with_retry(service.spreadsheets().batchUpdate(
                spreadsheetId=profile.sheet_id,
                body={"requests": [{
                    "deleteDimension": {
                        "range": {
                            "sheetId": gid,
                            "dimension": "ROWS",
                            "startIndex": sheet_row_number - 1,
                            "endIndex": sheet_row_number,
                        }
                    }
                }]},
            ))
            return True
    return False


def delete_rows(user: str, tab: str, match_column: str, match_values: set[str]) -> int:
    """Deletes every row where match_column is in match_values, in one
    batchUpdate -- used by dismiss_application.dismiss_applications() for
    bulk dismiss, instead of N separate delete_row() calls (each of which
    re-reads the whole tab). Requests are ordered bottom-to-top so an
    earlier deletion in the same batch can't shift the row index of a
    later one still to be deleted. Returns how many rows were deleted."""
    profile = load_profile(user)
    service = get_sheets_service(user)

    result = _execute_with_retry(service.spreadsheets().values().get(spreadsheetId=profile.sheet_id, range=tab))
    rows = result.get("values", [])
    if not rows:
        return 0

    header = rows[0]
    match_index = header.index(match_column)
    row_numbers = [
        sheet_row_number for sheet_row_number, row in enumerate(rows[1:], start=2)
        if match_index < len(row) and row[match_index] in match_values
    ]
    if not row_numbers:
        return 0

    metadata = _execute_with_retry(service.spreadsheets().get(spreadsheetId=profile.sheet_id))
    gid = next(s["properties"]["sheetId"] for s in metadata["sheets"] if s["properties"]["title"] == tab)
    requests = [
        {"deleteDimension": {"range": {"sheetId": gid, "dimension": "ROWS", "startIndex": n - 1, "endIndex": n}}}
        for n in sorted(row_numbers, reverse=True)
    ]
    _execute_with_retry(service.spreadsheets().batchUpdate(spreadsheetId=profile.sheet_id, body={"requests": requests}))
    return len(row_numbers)


def get_rows(user: str, tab: str) -> list[dict[str, str]]:
    """Returns every data row as a header-keyed dict — one Sheets API read
    for the whole tab, same fetch-once pattern as get_existing_dedupe_keys."""
    profile = load_profile(user)
    service = get_sheets_service(user)

    result = _execute_with_retry(service.spreadsheets().values().get(spreadsheetId=profile.sheet_id, range=tab))
    rows = result.get("values", [])
    if not rows:
        return []

    header = rows[0]
    return [
        {col: (row[i] if i < len(row) else "") for i, col in enumerate(header)}
        for row in rows[1:]
    ]


def update_row(user: str, tab: str, match_column: str, match_value: str, updates: dict) -> bool:
    """Finds the first row where match_column == match_value and updates the
    given columns in place. Returns whether a matching row was found."""
    profile = load_profile(user)
    service = get_sheets_service(user)

    result = _execute_with_retry(service.spreadsheets().values().get(spreadsheetId=profile.sheet_id, range=tab))
    rows = result.get("values", [])
    if not rows:
        return False

    header = rows[0]
    match_index = header.index(match_column)

    for sheet_row_number, row in enumerate(rows[1:], start=2):
        if match_index < len(row) and row[match_index] == match_value:
            new_row = row + [""] * (len(header) - len(row))
            for key, value in updates.items():
                new_row[header.index(key)] = value
            _execute_with_retry(service.spreadsheets().values().update(
                spreadsheetId=profile.sheet_id,
                range=f"{tab}!A{sheet_row_number}",
                valueInputOption="RAW",
                body={"values": [new_row]},
            ))
            return True
    return False
