"""Send capped, personalized cold emails via the Gmail API (spec Section 4,
step 5) with the ramp/bounce-rate logic from Section 5.

Contact-finding (confirmed in build step 9): postings are only emailed when
a REAL, explicitly published contact email can be found — never guessed
(e.g. careers@{domain}), a wrong guess bounces, which directly hurts the
ramp/reputation goal this whole module exists to protect. Postings with no
findable contact are simply skipped for cold email; they're already
reachable via the application path.

Two ways a contact gets found, both "real text somewhere, never invented":
1. `find_contact()` — the posting's own text lists an email, plain or
   obfuscated ("jane [at] acme [dot] com").
2. `find_contact_via_company_site()` — 2026-08-13 addition, explicitly
   reverses the earlier "no company-site scraping" call once the ~1-in-1900
   real hit rate on (1) alone was confirmed too low to be useful. Adzuna is
   the only source whose `url` points somewhere other than the ATS page
   already scanned by (1) — Greenhouse/Lever/Ashby/hiring.cafe postings all
   link back to the same page their description_text came from, so
   following them again would just re-find nothing. Adzuna's URL is
   followed for real (its own redirect chain, not a guessed domain) and the
   landing page's text is scanned with the same extraction/exclusion logic.
   Capped per run (`COMPANY_SITE_LOOKUP_MAX_ATTEMPTS_PER_RUN`) since this is
   a real network fetch per posting, not free like the regex-only path.

Ramp (Section 5): weeks 1-2 cap at daily_cap_week1, week 3+ ramps to
daily_cap_week3plus — but only if the bounce rate over sent history stays
under BOUNCE_RATE_THRESHOLD. A spiking bounce rate holds the cap at the
week-1 level regardless of how much time has elapsed, per "pause ramp-up
automatically if bounce rate spikes."

Provider: Google Gemini (free tier, Flash model) — same as cover_letter.py,
same reasoning (no ongoing cost, no credit card, not linked to a
billing-enabled GCP project).

2026-08-14: cold email got its own search (`search_cold_email_candidates`)
and its own filter/relevance step (`run_cold_email_pipeline`), replacing the
old design where it simply reused whatever `filter_postings` already
matched for job-search lanes. Two reasons: (1) `filter_postings`'s
seniority/radius/required_keywords rules are apply-fit rules — "would I
actually take this job" — which have nothing to do with "is this a real
person I can email," so they were needlessly shrinking the contact-eligible
pool; (2) Greenhouse/Lever/Ashby (the job-search lanes' main sources) are
curated big-tech boards that structurally never publish a raw contact email
in posting text — confirmed live, cold email's real hits all came from
Adzuna/hiring.cafe's smaller, more varied listings. The new search only hits
those two sources. Still fully independent of whether a posting is a good
personal fit for THIS applicant's actual resume: `_best_lane_match()` scores
a posting against every configured lane's own `keywords` and only proceeds
if at least one lane has real overlap — a posting with zero overlap with
either resume gets skipped, since there'd be nothing true to say in the
email. Location (target_countries) and recency stay as hard/soft filters —
those are policy floors ("only email real, current, in-scope postings"),
not apply-fit judgment calls."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import requests

from pipeline.config import load_secrets
from pipeline.filter import _is_recent, _matches_target_countries
from pipeline.google_auth import get_gmail_service, send_email
from pipeline.postings_store import get_cold_email_dedupe_keys, get_cold_emails, record_cold_email, update_cold_email
from pipeline.search import REQUEST_TIMEOUT_SECONDS, _strip_html, search_adzuna, search_hiring_cafe
from pipeline.sheet_log import record_cold_email_dedupe_backup
from pipeline.text_match import word_boundary_match
from pipeline.writing_style import DEFAULT_MODEL_FALLBACKS, STYLE_RULES, generate_with_gemini

COMPANY_SITE_LOOKUP_MAX_ATTEMPTS_PER_RUN = 10
# Landing pages this large are almost never a small company's own contact
# page (they're another ATS's own multi-posting board, a redirect
# intermediary, etc.) — skip scanning them, not worth the false-positive
# surface of a giant page of unrelated boilerplate/other-company emails.
COMPANY_SITE_MAX_TEXT_CHARS = 200_000

MODEL_FALLBACKS = DEFAULT_MODEL_FALLBACKS  # see writing_style.py's note on model choice + fallback order
MAX_DESCRIPTION_CHARS = 1500
BOUNCE_RATE_THRESHOLD = 0.05

# Boilerplate/system addresses that show up incidentally in posting text
# (ATS footers, compliance statements) — not real hiring contacts.
_EXCLUDED_EMAIL_DOMAINS = {
    "greenhouse.io", "lever.co", "myworkday.com", "workday.com",
    "adzuna.com", "adzuna.ca", "indeed.com", "linkedin.com", "hiringcafe.com",
    # Real bug, live 2026-08-14: cold email's own-search rollout sent 4 real
    # emails to the literal placeholder "your.name@email.com" -- a generic
    # example address baked into some Adzuna posting templates, extracted
    # as if it were a real contact. "email.com" itself is never a real
    # company's mail domain, so excluding it outright is safe. "domain.com"
    # added the same day after a second real send, to "your.email@domain.com"
    # -- the same class of placeholder, different template wording. Neither
    # is ever a real company's own mail domain.
    "email.com", "domain.com", "example.com",
}

# Domain-based exclusion isn't enough — e.g. accommodations-ext@figma.com is
# a real figma.com address, so it survives the domain check, but it's an ADA
# accommodation-request mailbox, not a hiring contact (confirmed via live
# testing: it was one of only two unique addresses found across ~1900 real
# postings). Excluded by local-part pattern instead of domain.
_EXCLUDED_LOCAL_PART_PATTERNS = (
    "accommodation", "accessib", "ada-", "-ada", "eeoc", "legal", "privacy",
    "compliance", "noreply", "no-reply", "donotreply", "unsubscribe",
    "webmaster", "abuse", "security", "recruiting-support", "recruitment-support",
    # Template placeholder local-parts, same "your.name@email.com" bug as
    # the email.com domain exclusion above -- catches the same placeholder
    # under a domain that isn't email.com too.
    "your.name", "yourname", "your-name", "firstname.lastname",
)

# Two confirmed real sends the same day used two different placeholder
# templates ("your.name@email.com", "your.email@domain.com") -- the shared
# signal isn't the specific words, it's that the local-part literally
# starts with "your". A real person's local-part starting with the literal
# word "your" is not a real pattern; a future template variant under an
# otherwise-real-looking domain (which the domain exclusion list above
# can't catch) still gets caught here.
_PLACEHOLDER_LOCAL_PART_PREFIX = "your"

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9\-.]+")

# Postings sometimes obfuscate a real contact address to dodge scrapers —
# "jane [at] acmecorp [dot] com", "jane AT acmecorp DOT com", "jane(at)acmecorp(dot)com".
# Same real-address principle as the plain regex above, just a different
# spelling of "@"/".": still never guessed, still literally present in the
# posting text.
_OBFUSCATED_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9_.+-]+\s*[\[(]?\s*at\s*[\])]?\s*[a-zA-Z0-9-]+"
    r"(?:\s*[\[(]?\s*dot\s*[\])]?\s*[a-zA-Z0-9-]+)+",
    re.IGNORECASE,
)


def _deobfuscate(raw: str) -> str:
    text = re.sub(r"\s*[\[(]?\s*at\s*[\])]?\s*", "@", raw, count=1, flags=re.IGNORECASE)
    return re.sub(r"\s*[\[(]?\s*dot\s*[\])]?\s*", ".", text, flags=re.IGNORECASE)

SYSTEM_PROMPT = f"""\
You write short, genuinely human-sounding cold outreach emails for a real \
job applicant reaching out directly to a hiring contact whose email was \
found on a real job posting. You are given (1) real facts about the \
applicant, pulled from their actual resume, and (2) the real posting. Write \
a brief note using only the facts you're given.

Hard rules:
{STYLE_RULES}
- Length: 80-120 words. Shorter than a cover letter — this is a quick, \
direct note, not a full pitch.
- Output plain text only — no markdown, no bracketed placeholders, no \
subject line, no preamble. Just the email body, ready to send, ending with \
a sign-off and the applicant's name.
- This email has no attachment and links to nothing. Never say or imply \
that a resume, portfolio, or any file is attached, linked, or enclosed — \
common phrases like "I've attached my resume" or "please find attached" \
would be false here. If you want to reference their experience, describe \
it directly in the note instead.
"""


@dataclass
class ContactMatch:
    email: str


def _candidate_emails(text: str) -> list[str]:
    plain = list(_EMAIL_RE.findall(text))
    obfuscated = [_deobfuscate(m) for m in _OBFUSCATED_EMAIL_RE.findall(text)]
    return plain + obfuscated


def _first_valid_email(candidates: list[str]) -> str | None:
    """Same domain/local-part/placeholder exclusion rules applied to any raw
    candidate list, regardless of where the candidates came from (visible
    body text or a mailto: href) — see the excluded-pattern comments above
    for what each check catches and why."""
    for raw_match in candidates:
        # Strip trailing sentence punctuation the regex greedily swallows
        # (e.g. "...contact support@greenhouse.io." at the end of a sentence
        # would otherwise leave the domain as "greenhouse.io." — a trailing
        # dot that fails to match the exclusion set and lets it slip through).
        email = raw_match.rstrip(".,;:)")
        local_part, _, domain = email.lower().partition("@")
        if domain in _EXCLUDED_EMAIL_DOMAINS:
            continue
        if any(pattern in local_part for pattern in _EXCLUDED_LOCAL_PART_PATTERNS):
            continue
        if local_part.startswith(_PLACEHOLDER_LOCAL_PART_PREFIX):
            continue
        return email
    return None


def _first_real_contact_email(text: str) -> str | None:
    return _first_valid_email(_candidate_emails(text))


# href="mailto:jane@acmecorp.com" -- a structured signal _strip_html discards
# entirely (it drops every tag and attribute, keeping only visible text), so
# a contact/careers page that links a mailto: address rather than printing it
# in visible text was previously invisible to find_contact_via_company_site
# no matter how the cap/scan logic was tuned. Matched against the RAW
# response body, before _strip_html runs.
_MAILTO_RE = re.compile(r'href=["\']mailto:([^"\'?]+)', re.IGNORECASE)


def _mailto_candidates(raw_html: str) -> list[str]:
    return _MAILTO_RE.findall(raw_html or "")


def find_contact(posting) -> ContactMatch | None:
    email = _first_real_contact_email(posting.description_text)
    return ContactMatch(email=email) if email else None


def find_contact_via_company_site(posting) -> ContactMatch | None:
    """Follows an Adzuna posting's own redirect_url for real (never a
    guessed domain) and looks for a published contact email, using the exact
    same extraction/exclusion rules as find_contact(). Checks mailto: links
    in the raw HTML first (a structured signal the visible-text scan can't
    see), then falls back to scanning the landing page's visible text.
    Adzuna-only — see this module's docstring for why every other source's
    url is redundant with description_text already scanned by
    find_contact(). Never raises: a network failure, non-HTML response, or
    oversized page just means "no contact found here," same as posting text
    with nothing in it."""
    if posting.source != "adzuna" or not posting.url:
        return None
    try:
        response = requests.get(posting.url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
        response.raise_for_status()
    except requests.RequestException:
        return None

    mailto_email = _first_valid_email(_mailto_candidates(response.text))
    if mailto_email:
        return ContactMatch(email=mailto_email)

    text = _strip_html(response.text)[:COMPANY_SITE_MAX_TEXT_CHARS]
    email = _first_real_contact_email(text)
    return ContactMatch(email=email) if email else None


def _resume_facts_block(resume: dict) -> str:
    lines = [f"Name: {resume['name']}"]
    lines.append("\nRelevant experience:")
    for entry in resume["experience"]["relevant"]:
        lines.append(f"- {entry['title']} at {entry['company']} ({entry['dates']})")
        for bullet in entry["bullets"]:
            lines.append(f"  * {bullet}")
    return "\n".join(lines)


def _build_user_message(resume: dict, posting, matched_terms: list[str]) -> str:
    description = posting.description_text[:MAX_DESCRIPTION_CHARS]
    return f"""\
APPLICANT FACTS (use only these — do not add to them):
{_resume_facts_block(resume)}

JOB POSTING:
Company: {posting.company}
Title: {posting.title}
Terms this posting matched from the applicant's target keywords: {', '.join(matched_terms)}

Posting description:
{description}

Write the outreach email now."""


def generate_cold_email_note(user: str, resume: dict, posting, matched_terms: list[str]) -> str:
    secrets = load_secrets(user)
    api_key = secrets.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(f"Missing GEMINI_API_KEY in profiles/{user}/secrets.env")

    return generate_with_gemini(
        api_key, MODEL_FALLBACKS, SYSTEM_PROMPT, _build_user_message(resume, posting, matched_terms),
        max_output_tokens=2048,
    )


def send_cold_email(user: str, to_email: str, subject: str, body: str) -> dict:
    return send_email(user, to_email, subject, body)


# ---------------------------------------------------------------------------
# Ramp / bounce-rate logic (spec Section 5)
# ---------------------------------------------------------------------------


def _current_week_number(ramp_start_date: str, today: date) -> int:
    start = date.fromisoformat(ramp_start_date)
    days_elapsed = (today - start).days
    return max(1, days_elapsed // 7 + 1)


def _bounce_rate(sent_rows: list[dict]) -> float:
    checked = [r for r in sent_rows if r.get("bounced") in ("Y", "N")]
    if not checked:
        return 0.0
    bounced = sum(1 for r in checked if r.get("bounced") == "Y")
    return bounced / len(checked)


def compute_daily_cap(user: str, cold_email_config, today: date | None = None) -> int:
    today = today or date.today()
    week = _current_week_number(cold_email_config.ramp_start_date, today)
    sent_rows = get_cold_emails(user)
    bounce_rate = _bounce_rate(sent_rows)

    if week <= 2 or bounce_rate > BOUNCE_RATE_THRESHOLD:
        return cold_email_config.daily_cap_week1
    return cold_email_config.daily_cap_week3plus


def count_sent_today(user: str, today: date | None = None) -> int:
    today = today or date.today()
    rows = get_cold_emails(user)
    return sum(1 for r in rows if r.get("date") == today.isoformat())


# ---------------------------------------------------------------------------
# Bounce/reply detection
# ---------------------------------------------------------------------------

_BOUNCE_SENDER_MARKERS = ("mailer-daemon", "mail delivery subsystem", "postmaster")


def check_bounce_or_reply(user: str, thread_id: str) -> tuple[bool, bool]:
    """Returns (bounced, replied) for a previously sent cold email's thread."""
    gmail = get_gmail_service(user)
    thread = gmail.users().threads().get(userId="me", id=thread_id, format="metadata").execute()
    messages = thread.get("messages", [])

    bounced = False
    replied = False
    for message in messages[1:]:  # first message is the one we sent
        headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
        from_header = headers.get("from", "").lower()
        subject = headers.get("subject", "").lower()
        if any(marker in from_header for marker in _BOUNCE_SENDER_MARKERS) or "delivery status" in subject:
            bounced = True
        else:
            replied = True

    return bounced, replied


def refresh_bounce_and_reply_status(user: str) -> None:
    """Re-checks every sent cold email that hasn't been marked bounced/replied
    yet and updates the sheet. Call this before compute_daily_cap so the
    ramp decision reflects current data."""
    for row in get_cold_emails(user):
        thread_id = row.get("thread_id")
        if not thread_id or row.get("bounced") in ("Y", "N"):
            continue
        bounced, replied = check_bounce_or_reply(user, thread_id)
        update_cold_email(user, row["posting_key"], {
            "bounced": "Y" if bounced else "N",
            "replied": "Y" if replied else "N",
        })


# ---------------------------------------------------------------------------
# Cold email's own search + relevance filter (independent of job-search lanes)
# ---------------------------------------------------------------------------


def search_cold_email_candidates(profile, secrets: dict) -> list:
    """Adzuna + hiring.cafe only — see module docstring for why
    Greenhouse/Lever/Ashby (the job-search lanes' curated big-tech boards)
    aren't worth searching again here. `profile.cold_email.search_keywords`
    if set, otherwise the union of every lane's own `keywords` (so an
    existing profile.yaml with no explicit search_keywords still searches
    at least as wide as today's per-lane behavior did)."""
    keywords = profile.cold_email.search_keywords or sorted({kw for lane in profile.lanes for kw in lane.keywords})

    postings_by_key = {}
    for posting in search_hiring_cafe(keywords):
        postings_by_key[posting.dedupe_key()] = posting

    app_id, app_key = secrets.get("ADZUNA_APP_ID"), secrets.get("ADZUNA_APP_KEY")
    if app_id and app_key:
        for posting in search_adzuna(keywords, profile.adzuna_country, app_id, app_key):
            postings_by_key[posting.dedupe_key()] = posting

    return list(postings_by_key.values())


def _best_lane_match(posting, lanes) -> tuple[object, list[str]] | None:
    """Scores a posting against every lane's own `keywords` (not
    required_keywords/seniority/radius — those are apply-fit rules, out of
    scope here) and returns whichever lane has the most overlap, so the
    email can be grounded in a real resume with genuinely matching
    experience. None if no lane has any overlap at all — nothing true to
    personalize with."""
    full_text = f"{posting.title} {posting.description_text}".lower()
    best_lane, best_terms = None, []
    for lane in lanes:
        terms = [term for term in lane.keywords if word_boundary_match(term.lower(), full_text)]
        if len(terms) > len(best_terms):
            best_lane, best_terms = lane, terms
    return (best_lane, best_terms) if best_lane is not None else None


def run_cold_email_pipeline(user: str, profile, secrets: dict) -> dict:
    """Cold email's own end-to-end pipeline: search -> location/recency
    filter -> per-lane relevance match -> send. Returns funnel stats
    (scanned/eligible/matched/contacts_found/sent) for daily_report.py's own
    cold-email section — deliberately tracked as a separate funnel from the
    job-search lanes', since it's now a genuinely separate search."""
    postings = search_cold_email_candidates(profile, secrets)

    eligible = [
        p for p in postings
        if _matches_target_countries(p.location, profile.target_countries) and _is_recent(p.posted_at)
    ]

    resumes_by_lane: dict[str, dict] = {}
    candidates = []
    for posting in eligible:
        match = _best_lane_match(posting, profile.lanes)
        if match is None:
            continue
        lane, matched_terms = match
        if lane.name not in resumes_by_lane:
            resumes_by_lane[lane.name] = profile.resumes[lane.name]
        candidates.append((posting, matched_terms, lane.name, resumes_by_lane[lane.name]))

    # More matched terms = closer fit — same reasoning as run_pipeline.py's
    # swipe-queue ordering: when the daily cap cuts the list short, keep the
    # strongest matches, not an arbitrary subset.
    candidates.sort(key=lambda c: len(c[1]), reverse=True)

    send_stats = _send_cold_emails(user, profile, candidates)

    return {
        "scanned": len(postings),
        "eligible": len(eligible),
        "matched": len(candidates),
        "contacts_found": send_stats["contacts_found"],
        "sent": len(send_stats["results"]),
    }


def _send_cold_emails(user: str, profile, candidates: list[tuple]) -> dict:
    """Sends cold emails for candidates with a findable contact, up to
    today's ramp-adjusted cap, skipping anything already emailed (dedup
    against the cold_emails tab). Keeps scanning past the cap (cheap regex
    contact-finding only) so `contacts_found` reflects real untapped
    opportunity on capped days, not just what fit under the cap — sending
    itself still stops at the cap."""
    refresh_bounce_and_reply_status(user)

    daily_cap = compute_daily_cap(user, profile.cold_email)
    existing_keys = get_cold_email_dedupe_keys(user)
    already_sent_today = count_sent_today(user)
    company_site_lookups_used = 0  # per run — see COMPANY_SITE_LOOKUP_MAX_ATTEMPTS_PER_RUN

    results = []
    contacts_found = 0
    for posting, matched_terms, lane_name, resume in candidates:
        if posting.dedupe_key() in existing_keys:
            continue

        contact = find_contact(posting)
        if contact is None and company_site_lookups_used < COMPANY_SITE_LOOKUP_MAX_ATTEMPTS_PER_RUN:
            company_site_lookups_used += 1
            contact = find_contact_via_company_site(posting)
        if contact is None:
            continue
        contacts_found += 1

        if already_sent_today >= daily_cap:
            continue

        # A single posting's generation/send failure (real live case,
        # 2026-08-14: Gemini's whole fallback chain exhausted mid-run) must
        # not lose every remaining candidate in the batch along with it --
        # same "one bad item shouldn't sink the run" principle as
        # run_pipeline.py's per-step _try wrapper. Logged, skipped, moves on.
        try:
            body = generate_cold_email_note(user, resume, posting, matched_terms)
            subject = f"Regarding the {posting.title} role at {posting.company}"
            sent = send_cold_email(user, contact.email, subject, body)
        except Exception as exc:  # noqa: BLE001 — deliberately broad, see comment above
            print(f"[cold_email] {posting.dedupe_key()}: generation/send failed ({exc}), skipping")
            continue

        record_cold_email(user, {
            "posting_key": posting.dedupe_key(),
            "date": date.today().isoformat(),
            "lane": lane_name,
            "company": posting.company,
            "contact_email": contact.email,
            "sent_at": date.today().isoformat(),
            "thread_id": sent.get("threadId", ""),
            "location": posting.location,
        })
        record_cold_email_dedupe_backup(posting.dedupe_key())

        already_sent_today += 1
        results.append({"posting": posting, "contact_email": contact.email, "sent": True})

    return {"results": results, "contacts_found": contacts_found}
