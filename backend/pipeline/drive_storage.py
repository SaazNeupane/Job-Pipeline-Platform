"""Uploads held-posting resumes to a dedicated Google Drive folder so
pending_approval can link to them instead of losing the tailored PDF once
the CI runner's ephemeral filesystem disappears (spec Section 4 follow-on,
decided in the 2026-08-06 session). Only called for postings that end up
held, not ones that actually auto-submit — see apply.py's
process_application.

Uses the drive.file OAuth scope (narrower than full "drive") — it only
grants access to files this app itself creates, which is also what makes
cleanup_old_files() safe to run unconditionally: everything in the
dedicated folder was created by this app, so deleting by age alone can
never touch the user's other Drive files.

No "already applied" detection — not reliably automatable, since the user
manually finishing a held application happens outside the pipeline's
visibility entirely. A fixed 7-day auto-delete is the practical bound
instead: a held posting is almost always stale after a week anyway.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from googleapiclient.http import MediaFileUpload

from pipeline.google_auth import get_drive_service

FOLDER_NAME = "Job Pipeline Resumes"
MAX_AGE_DAYS = 7


def _escape_query_literal(value: str) -> str:
    """Drive's `q=` search grammar treats a single-quoted string as a
    literal, with `\\'` as its own escape for an embedded quote (per Drive
    API docs). filename is derived from posting.job_id (external, Greenhouse/
    Adzuna/hiring.cafe-controlled) -- escape any embedded quote/backslash
    before interpolating it into a query string, rather than trusting
    external data not to contain one."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _get_or_create_folder(service) -> str:
    """Finds the dedicated resume folder, creating it on first use. Scoped
    by name + folder mimeType + not-trashed so a second call never creates
    a duplicate folder."""
    response = service.files().list(
        q=f"name='{_escape_query_literal(FOLDER_NAME)}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        spaces="drive",
        fields="files(id)",
    ).execute()
    files = response.get("files", [])
    if files:
        return files[0]["id"]

    folder = service.files().create(
        body={"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"},
        fields="id",
    ).execute()
    return folder["id"]


def upload_resume(user: str, resume_pdf_path: Path, filename: str, share_with_email: str) -> str:
    """Uploads a tailored resume PDF to the dedicated Drive folder and
    returns a link to it. Shared directly with share_with_email (the user's
    own report_email) rather than "anyone with the link" — a resume carries
    real PII, so a scoped grant is worth the one extra API call over a
    public link nobody but the user actually needs.

    Reuses (overwrites) an existing file with the same filename in the
    folder rather than always creating a new one — filename is derived from
    posting_key, so re-processing the same posting (e.g. after a sheet clear
    + re-run) previously left an ever-growing pile of stale duplicate PDFs
    behind, none of which pending_approval's resume_link pointed at anymore."""
    service = get_drive_service(user)
    folder_id = _get_or_create_folder(service)

    existing = service.files().list(
        q=f"name='{_escape_query_literal(filename)}' and '{_escape_query_literal(folder_id)}' in parents and trashed=false",
        spaces="drive",
        fields="files(id)",
    ).execute()
    existing_files = existing.get("files", [])

    media_body = MediaFileUpload(str(resume_pdf_path), mimetype="application/pdf")

    if existing_files:
        file_id = existing_files[0]["id"]
        service.files().update(fileId=file_id, media_body=media_body).execute()
    else:
        uploaded = service.files().create(
            body={"name": filename, "parents": [folder_id]},
            media_body=media_body,
            fields="id",
        ).execute()
        file_id = uploaded["id"]

        service.permissions().create(
            fileId=file_id,
            body={"type": "user", "role": "reader", "emailAddress": share_with_email},
            sendNotificationEmail=False,
            fields="id",
        ).execute()

    return f"https://drive.google.com/file/d/{file_id}/view"


def cleanup_old_files(user: str) -> int:
    """Deletes every file in the dedicated folder older than MAX_AGE_DAYS.
    Returns the count deleted. Meant to be called once per pipeline run
    (see run_pipeline.py) — cheap no-op when nothing has aged out yet."""
    service = get_drive_service(user)
    folder_id = _get_or_create_folder(service)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).isoformat()

    response = service.files().list(
        q=f"'{_escape_query_literal(folder_id)}' in parents and trashed=false and createdTime < '{cutoff}'",
        spaces="drive",
        fields="files(id)",
    ).execute()
    files = response.get("files", [])
    for f in files:
        service.files().delete(fileId=f["id"]).execute()
    return len(files)
