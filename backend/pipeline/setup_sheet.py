"""One-time script: creates the Google Sheet described in spec Section 2
(applied jobs log, cold email log, daily run summary tabs) and prints its ID
to paste into profile.yaml. Run manually, once, after authorize_google.py.

Column headers below are a provisional first pass reflecting only what's
already specified (Section 4 steps 6-7) — sheet_log.py (build step 5-6) and
cold_email.py (build step 9) may adjust them once those modules land.

Usage: python setup_sheet.py <user>
"""

from __future__ import annotations

import sys

from pipeline.google_auth import get_sheets_service

APPLIED_JOBS_HEADERS = [
    "posting_key", "date", "lane", "company", "role", "source", "location", "application_status",
    "resume_version", "contact_emailed", "email_sent_at", "notes", "posted_date", "content_flags",
]
COLD_EMAIL_HEADERS = [
    "posting_key", "date", "lane", "company", "location", "contact_name", "contact_email",
    "sent_at", "thread_id", "bounced", "replied", "notes",
]
DAILY_SUMMARY_HEADERS = [
    "date", "applied_count", "pending_approval_count", "emails_sent",
    "errors", "notes", "queued_count", "awaiting_apply_count",
    "cold_email_scanned", "cold_email_eligible", "cold_email_matched", "cold_email_contacts_found",
]
PENDING_APPROVAL_HEADERS = [
    "posting_key", "date", "lane", "company", "role", "source", "location", "reason_held",
    "resume_version", "application_url", "notes", "resume_link", "cover_letter", "posted_date",
    "content_flags", "required_years",
]
DISMISSED_JOBS_HEADERS = [
    "posting_key", "date", "lane", "company", "role", "source", "location", "reason_held",
    "dismissed_at", "notes",
]
SWIPE_QUEUE_HEADERS = [
    "posting_key", "date", "lane", "company", "role", "source", "job_id", "location",
    "posted_date", "application_url", "description_text", "matched_terms",
    "remote_type", "employment_type", "salary_min", "salary_max", "required_years",
]


TAB_COLORS = {
    "applied_jobs": {"red": 0.20, "green": 0.55, "blue": 0.35},       # green — went out
    "cold_emails": {"red": 0.20, "green": 0.40, "blue": 0.70},        # blue — outreach
    "daily_summary": {"red": 0.45, "green": 0.35, "blue": 0.60},      # purple — overview
    "pending_approval": {"red": 0.85, "green": 0.55, "blue": 0.10},   # amber — needs your attention
    "dismissed_jobs": {"red": 0.45, "green": 0.45, "blue": 0.45},     # grey — set aside, not acted on
    "swipe_queue": {"red": 0.70, "green": 0.25, "blue": 0.55},        # pink — awaiting a swipe
}
HEADER_BACKGROUND = {"red": 0.13, "green": 0.16, "blue": 0.22}
HEADER_TEXT_COLOR = {"red": 1, "green": 1, "blue": 1}
BAND_FIRST_COLOR = {"red": 1, "green": 1, "blue": 1}
BAND_SECOND_COLOR = {"red": 0.95, "green": 0.96, "blue": 0.98}
# Real bug found live: data-row text was rendering white-on-white. Sheets'
# addBanding only controls background color, but appended rows apparently
# inherited the header row's white foregroundColor as their own explicit
# text format rather than leaving it unset — effectiveFormat confirmed
# every data cell had textFormat.foregroundColor forced to white, invisible
# against the (white/light-gray) band background. Setting this explicitly
# on every data row, rather than leaving text color unset and hoping it
# defaults sanely, is what actually fixes it.
DATA_TEXT_COLOR = {"red": 0.1, "green": 0.1, "blue": 0.1}
MAX_FORMATTED_ROWS = 2000  # generous headroom so formatting doesn't need re-running as rows accumulate
HEADER_ROW_HEIGHT_PX = 36
DATA_ROW_HEIGHT_PX = 34  # noticeably taller than Sheets' cramped ~21px default
COLUMN_PADDING_PX = 40  # extra breathing room added on top of auto-resize's tight fit


def format_sheet(service, sheet_id: str, tabs_and_headers: dict[str, list[str]]) -> None:
    """Frozen header row, bold header styling, alternating row bands, a
    distinct tab color per tab, auto-sized columns, wrapped long text, and
    conditional highlighting for cold_emails' bounced/replied columns.

    Idempotent — safe to re-run (e.g. after tweaking colors/spacing) since
    Sheets errors on adding banding to an already-banded range, and would
    otherwise pile up duplicate conditional format rules on every re-run."""
    meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    gid_by_title = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    sheet_by_gid = {s["properties"]["sheetId"]: s for s in meta["sheets"]}

    requests = []
    for tab in tabs_and_headers:
        gid = gid_by_title[tab]
        sheet = sheet_by_gid[gid]
        for banded_range in sheet.get("bandedRanges", []):
            requests.append({"deleteBanding": {"bandedRangeId": banded_range["bandedRangeId"]}})
        for i in reversed(range(len(sheet.get("conditionalFormats", [])))):
            requests.append({"deleteConditionalFormatRule": {"sheetId": gid, "index": i}})

    for tab, headers in tabs_and_headers.items():
        gid = gid_by_title[tab]
        n_cols = len(headers)

        requests.append({
            "updateSheetProperties": {
                "properties": {
                    "sheetId": gid,
                    "gridProperties": {"frozenRowCount": 1},
                    "tabColor": TAB_COLORS.get(tab, HEADER_BACKGROUND),
                },
                "fields": "gridProperties.frozenRowCount,tabColor",
            }
        })

        requests.append({
            "repeatCell": {
                "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": n_cols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": HEADER_BACKGROUND,
                    "textFormat": {"foregroundColor": HEADER_TEXT_COLOR, "bold": True, "fontSize": 10},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
            }
        })

        requests.append({
            "updateDimensionProperties": {
                "range": {"sheetId": gid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": HEADER_ROW_HEIGHT_PX},
                "fields": "pixelSize",
            }
        })

        requests.append({
            "updateDimensionProperties": {
                "range": {"sheetId": gid, "dimension": "ROWS", "startIndex": 1, "endIndex": MAX_FORMATTED_ROWS},
                "properties": {"pixelSize": DATA_ROW_HEIGHT_PX},
                "fields": "pixelSize",
            }
        })

        requests.append({
            "addBanding": {
                "bandedRange": {
                    "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": MAX_FORMATTED_ROWS, "startColumnIndex": 0, "endColumnIndex": n_cols},
                    "rowProperties": {
                        "headerColor": HEADER_BACKGROUND,
                        "firstBandColor": BAND_FIRST_COLOR,
                        "secondBandColor": BAND_SECOND_COLOR,
                    },
                }
            }
        })

        requests.append({
            "repeatCell": {
                "range": {"sheetId": gid, "startRowIndex": 1, "endRowIndex": MAX_FORMATTED_ROWS, "startColumnIndex": 0, "endColumnIndex": n_cols},
                "cell": {"userEnteredFormat": {
                    "wrapStrategy": "WRAP",
                    "verticalAlignment": "MIDDLE",
                    "textFormat": {"foregroundColor": DATA_TEXT_COLOR},
                }},
                "fields": "userEnteredFormat(wrapStrategy,verticalAlignment,textFormat.foregroundColor)",
            }
        })

        requests.append({
            "autoResizeDimensions": {
                "dimensions": {"sheetId": gid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": n_cols},
            }
        })

        if tab == "cold_emails":
            bounced_idx = headers.index("bounced")
            replied_idx = headers.index("replied")
            for col_idx, value, color in [
                (bounced_idx, "Y", {"red": 0.75, "green": 0.15, "blue": 0.15}),
                (replied_idx, "Y", {"red": 0.15, "green": 0.55, "blue": 0.25}),
            ]:
                requests.append({
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [{
                                "sheetId": gid, "startRowIndex": 1, "endRowIndex": MAX_FORMATTED_ROWS,
                                "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1,
                            }],
                            "booleanRule": {
                                "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": value}]},
                                "format": {"textFormat": {"foregroundColor": color, "bold": True}},
                            },
                        },
                        "index": 0,
                    }
                })

    service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": requests}).execute()

    # Column padding is a second pass: auto-resize above fits column widths
    # tightly to content, and the resulting pixel sizes are only knowable
    # after that batchUpdate actually runs — so widen each column afterward
    # for breathing room, rather than trying to compute it upfront.
    sized = service.spreadsheets().get(
        spreadsheetId=sheet_id, fields="sheets(properties(sheetId,title),data.columnMetadata)"
    ).execute()

    padding_requests = []
    for sheet in sized["sheets"]:
        tab = sheet["properties"]["title"]
        if tab not in tabs_and_headers:
            continue
        gid = sheet["properties"]["sheetId"]
        n_cols = len(tabs_and_headers[tab])
        column_metadata = sheet.get("data", [{}])[0].get("columnMetadata", [])

        for col_idx in range(n_cols):
            current_width = column_metadata[col_idx].get("pixelSize", 100) if col_idx < len(column_metadata) else 100
            padding_requests.append({
                "updateDimensionProperties": {
                    "range": {"sheetId": gid, "dimension": "COLUMNS", "startIndex": col_idx, "endIndex": col_idx + 1},
                    "properties": {"pixelSize": current_width + COLUMN_PADDING_PX},
                    "fields": "pixelSize",
                }
            })

    service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": padding_requests}).execute()


def create_sheet(user: str) -> str:
    """Creates and formats a new Job Pipeline sheet for `user`, returning its
    sheet_id. Split out from main() so the setup wizard (webapp.py) can call
    it directly instead of shelling out to this script."""
    service = get_sheets_service(user)

    spreadsheet = service.spreadsheets().create(
        body={
            "properties": {"title": f"Job Pipeline — {user}"},
            "sheets": [
                {"properties": {"title": "applied_jobs"}},
                {"properties": {"title": "cold_emails"}},
                {"properties": {"title": "daily_summary"}},
                {"properties": {"title": "pending_approval"}},
                {"properties": {"title": "dismissed_jobs"}},
                {"properties": {"title": "swipe_queue"}},
            ],
        }
    ).execute()

    sheet_id = spreadsheet["spreadsheetId"]

    tabs_and_headers = {
        "applied_jobs": APPLIED_JOBS_HEADERS,
        "cold_emails": COLD_EMAIL_HEADERS,
        "daily_summary": DAILY_SUMMARY_HEADERS,
        "pending_approval": PENDING_APPROVAL_HEADERS,
        "dismissed_jobs": DISMISSED_JOBS_HEADERS,
        "swipe_queue": SWIPE_QUEUE_HEADERS,
    }
    for tab, headers in tabs_and_headers.items():
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            body={"values": [headers]},
        ).execute()

    format_sheet(service, sheet_id, tabs_and_headers)
    return sheet_id


def main(user: str) -> None:
    sheet_id = create_sheet(user)
    print(f"Created sheet: https://docs.google.com/spreadsheets/d/{sheet_id}")
    print(f"sheet_id: {sheet_id}")
    print(f"Paste this into profiles/{user}/profile.yaml under sheet_id.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python setup_sheet.py <user>")
    main(sys.argv[1])
