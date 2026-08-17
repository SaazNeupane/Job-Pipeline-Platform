"""Swipe-queue mechanics: queueing new matches for a human decision, and
handling that decision once it's made.

Replaces the old fully-automated apply.py submit path (see CLAUDE.md — real
auto-submission rarely cleared captcha/custom-question gates, so the human
now picks which postings are worth pursuing at all, same as swiping through
a deck of cards). run_pipeline.py no longer decides who to apply to; it only
queues candidates via queue_for_swipe(). The actual "apply" step is still
manual — a right-swipe (queue_like(), then generate_liked_materials() in a
background thread — see webapp/app.py's api_swipe_like) generates the
tailored resume/cover letter and hands you a Drive link + the posting URL
in pending_approval, same as a held row always did. You submit the real
application yourself; "Mark applied" (promote_application.py) already
records that. apply.py itself (the Playwright fill/inspect/auto-submit
module) has been removed entirely, not just disconnected — see CLAUDE.md's
"Remove auto-apply" commit.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from pathlib import Path

from pipeline.config import load_profile, load_secrets
from pipeline.cover_letter import get_cover_letter
from pipeline.drive_storage import upload_resume
from pipeline.filter import extract_required_years, posting_fingerprint
from pipeline.postings_store import create_posting, get_existing_fingerprints, get_posting, transition_posting, update_posting
from pipeline.search import Posting
from pipeline.tailor_resume import render_resume_pdf, reword_bullets_with_llm, tailor_resume
from pipeline.writing_style import DEFAULT_MODEL_FALLBACKS, generate_with_gemini


def queue_for_swipe(user: str, lane, matches: list[tuple]) -> int:
    """Appends one swipe_queue row per (posting, matched_terms) pair — the
    lightweight card info a swipe decision needs (title/company/location/
    posted date/stack/salary), without generating a resume or cover letter
    yet. That generation only happens on a like (see like_posting) so a
    reject never burns an LLM call or a Drive upload. Returns how many rows
    were queued."""
    queued = 0
    for posting, matched_terms in matches:
        required_years = extract_required_years(f"{posting.title} {posting.description_text}")
        create_posting(user, "queued", {
            "posting_key": posting.dedupe_key(),
            "date": date.today().isoformat(),
            "lane": lane.name,
            "company": posting.company,
            "role": posting.title,
            "source": posting.source,
            "job_id": posting.job_id,
            "location": posting.location,
            "posted_date": posting.posted_at,
            "application_url": posting.url,
            "description_text": posting.description_text,
            "matched_terms": ",".join(matched_terms),
            "remote_type": posting.remote_type,
            "employment_type": posting.employment_type,
            "salary_min": posting.salary_min,
            "salary_max": posting.salary_max,
            "required_years": required_years,
        })
        queued += 1
    return queued


def _to_float(value: str) -> float | None:
    return float(value) if value else None


def _posting_from_row(row: dict) -> Posting:
    return Posting(
        source=row.get("source", ""),
        company=row.get("company", ""),
        job_id=row.get("job_id", ""),
        title=row.get("role", ""),
        url=row.get("application_url", ""),
        location=row.get("location", ""),
        description_text=row.get("description_text", ""),
        posted_at=row.get("posted_date", ""),
        remote_type=row.get("remote_type", ""),
        employment_type=row.get("employment_type", ""),
        salary_min=_to_float(row.get("salary_min", "")),
        salary_max=_to_float(row.get("salary_max", "")),
    )


_MANUAL_PARSE_SYSTEM_PROMPT = """\
You extract structured fields from a job posting a user pasted in from somewhere else \
(e.g. Indeed, LinkedIn, a company careers page). Respond with ONLY a JSON object with \
exactly these keys: "title", "company", "location", "description" (all strings). No \
markdown, no commentary, no extra keys. Pull the plain-text job description into \
"description" as-is, trimmed of obvious page chrome (nav links, "Apply now" buttons, \
cookie notices) but never summarized or reworded. If a field genuinely isn't present in \
the text, use an empty string for it — never invent a company, title, or location that \
isn't actually there."""


def _parse_pasted_posting(api_key: str, raw_text: str) -> dict:
    raw = generate_with_gemini(
        api_key, DEFAULT_MODEL_FALLBACKS, _MANUAL_PARSE_SYSTEM_PROMPT, raw_text, max_output_tokens=2048,
    )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Couldn't read that as a job posting: {exc}") from exc
    return {key: str(parsed.get(key) or "") for key in ("title", "company", "location", "description")}


def add_manual_posting(user: str, lane_name: str, raw_text: str, url: str = "") -> dict:
    """Lets a posting found somewhere this pipeline doesn't search (Indeed, LinkedIn, a
    direct company site) go through the exact same tailor/cover-letter/Drive-upload chain
    as one it found itself — skips the swipe queue entirely and lands straight in
    pending_approval, same end state a right-swipe reaches, since pasting it in already
    means the user decided they want it. Gemini only ever extracts fields already present
    in the pasted text (see _MANUAL_PARSE_SYSTEM_PROMPT) — it never invents a posting."""
    if not raw_text.strip():
        raise SystemExit("Paste the job posting text first.")

    profile = load_profile(user)
    lane = next((l for l in profile.lanes if l.name == lane_name), None)
    if lane is None:
        raise SystemExit(f"No lane named {lane_name!r} in your profile.")

    secrets = load_secrets(user)
    api_key = secrets.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("Add a Gemini API key in setup before adding a posting this way.")

    parsed = _parse_pasted_posting(api_key, raw_text)
    if not parsed["title"] and not parsed["company"]:
        raise SystemExit("Couldn't find a job title or company in that text — paste the full posting.")

    fingerprint = posting_fingerprint("manual", parsed["company"], parsed["title"], parsed["location"])
    if fingerprint in get_existing_fingerprints(user):
        raise SystemExit("You've already added this posting.")

    posting_key = f"manual:{uuid.uuid4().hex[:12]}"
    match = create_posting(user, "pending", {
        "posting_key": posting_key,
        "date": date.today().isoformat(),
        "lane": lane.name,
        "company": parsed["company"],
        "role": parsed["title"],
        "source": "manual",
        "job_id": posting_key.split(":", 1)[1],
        "location": parsed["location"],
        "application_url": url,
        "description_text": parsed["description"],
        "matched_terms": "",
        "reason_held": "generating",
        "resume_version": lane.resume,
        "resume_link": "",
        "cover_letter": "",
    })
    return match


def queue_like(user: str, posting_key: str) -> dict:
    """Right-swipe, fast path: moves the card from swipe_queue into
    pending_approval immediately (reason_held="generating"), with no resume/
    cover-letter/Drive work done yet. This is deliberately split from
    generate_liked_materials() below — the webapp route calls this
    synchronously (so the swipe UI can advance to the next card right away)
    and hands the returned swipe_queue row off to generate_liked_materials()
    in a background thread. Previously a single like_posting() ran the whole
    tailor/reword/render/cover-letter/Drive-upload chain (several real LLM
    and network calls) inline in the request, which is exactly why every
    right-swipe felt laggy — the click was blocked on that whole chain
    before the UI could move on. Returns the full swipe_queue row (not the
    placeholder written here) since generate_liked_materials() needs its
    description_text/matched_terms, which aren't columns on pending_approval
    and would otherwise be lost once the swipe_queue row is deleted."""
    match = get_posting(user, posting_key)
    if match is None or match.get("status") != "queued":
        raise SystemExit(f"No swipe_queue row found for posting_key={posting_key!r}")

    profile = load_profile(user)
    lane = next((lane for lane in profile.lanes if lane.name == match.get("lane")), None)
    if lane is None:
        raise SystemExit(f"No lane named {match.get('lane')!r} in {user}'s profile — can't tailor a resume for it.")

    transition_posting(user, posting_key, "pending", {
        "date": date.today().isoformat(),
        "reason_held": "generating",
        "resume_version": lane.resume,
        "resume_link": "",
        "cover_letter": "",
    })

    print(f"[swipe_actions] {posting_key} liked -> pending_approval (generating in background).")
    return match


def retry_generation(user: str, posting_key: str) -> dict:
    """Re-attempts generate_liked_materials() for a pending_approval row
    that's stuck (still "generating" from a webapp process that died
    mid-thread -- confirmed live 2026-08-14, a real row sat on "generating"
    for over a day with the webapp process it started in long since closed
    -- or labeled "generation_failed: ..." after a real in-process error,
    see that function's own except block). Best-effort only: the
    swipe_queue row that had the posting's real description_text/
    matched_terms is long gone by this point (queue_like() deletes it), so
    a retry tailors against the lane's own keywords alone, without the
    extra posting-specific signal a fresh like would have had. Still a
    real, usable resume and cover letter -- better than a row stuck
    forever -- just not quite as sharply targeted as the original attempt
    would have been. Sets reason_held back to "generating" immediately so
    the dashboard shows the same in-progress state as a fresh like."""
    row = get_posting(user, posting_key)
    if row is None or row.get("status") != "pending":
        raise SystemExit(f"No pending_approval row found for posting_key={posting_key!r}")

    update_posting(user, posting_key, {"reason_held": "generating"})
    return row


def generate_liked_materials(user: str, match: dict) -> None:
    """The slow half of a right-swipe: tailors the resume, generates a
    cover letter, uploads the resume to Drive, then fills in the
    pending_approval placeholder queue_like() already wrote. Meant to be run
    off the request thread (see webapp/app.py's api_swipe_like) so a swipe
    click isn't blocked on it. Any failure here is caught and written back
    as a visible reason_held rather than left silently stuck on
    "generating" forever — the placeholder row is already real user-facing
    state by the time this runs, so it must never just vanish on error."""
    posting_key = match["posting_key"]
    try:
        profile = load_profile(user)
        lane = next(lane for lane in profile.lanes if lane.name == match.get("lane"))
        posting = _posting_from_row(match)
        matched_terms = [t for t in match.get("matched_terms", "").split(",") if t]

        resume = profile.resumes[lane.name]
        tailored = tailor_resume(resume, lane, matched_terms, posting.title, posting.description_text)
        tailored = reword_bullets_with_llm(user, tailored, posting, dry_run=False, blend_titles=lane.relabel_titles_to_posting)

        output_dir = Path("output")
        stem = f"{lane.name}_{posting.source}_{posting.job_id}"
        resume_pdf_path = output_dir / f"{stem}_resume.pdf"

        content_flags = list(tailored.get("content_flags", []))
        content_flags += render_resume_pdf(tailored, resume_pdf_path)
        cover_letter_text = get_cover_letter(user, tailored, posting, matched_terms, dry_run=False)
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            resume_link = upload_resume(user, resume_pdf_path, f"{stem}_resume.pdf", profile.report_email)
        except Exception as exc:  # noqa: BLE001 — Drive upload must never block writing the row itself
            print(f"[swipe_actions] upload_resume failed for {posting_key}: {exc}")
            resume_link = ""

        update_posting(user, posting_key, {
            "content_flags": "; ".join(content_flags),
            "reason_held": "awaiting_manual_apply",
            "resume_link": resume_link,
            "cover_letter": cover_letter_text,
        })
        print(f"[swipe_actions] {posting_key} materials generated -> pending_approval.")
    except Exception as exc:  # noqa: BLE001 — background thread has no caller to raise to
        print(f"[swipe_actions] generation failed for {posting_key}: {exc}")
        update_posting(user, posting_key, {
            "reason_held": f"generation_failed: {exc}",
        })


def reject_posting(user: str, posting_key: str) -> None:
    """Left-swipe: moves the card straight from swipe_queue to
    dismissed_jobs — no resume/cover letter/Drive upload ever generated.
    run_pipeline.py's dedupe reads dismissed_jobs, so a rejected posting
    never resurfaces in a later run's swipe queue, same permanence as
    dismissing a pending_approval row."""
    match = get_posting(user, posting_key)
    if match is None or match.get("status") != "queued":
        raise SystemExit(f"No swipe_queue row found for posting_key={posting_key!r}")

    transition_posting(user, posting_key, "dismissed", {
        "reason_held": "swiped_left",
        "dismissed_at": datetime.now().isoformat(timespec="seconds"),
    })

    print(f"[swipe_actions] {posting_key} rejected -> dismissed_jobs.")
