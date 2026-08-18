"""Pull new postings per lane from configured sources (spec Section 4, step 1).

Greenhouse has no cross-company search — its public API is scoped to one
company's board at a time (`/v1/boards/{token}/jobs`), so the companies to
check come from `profile.yaml`'s `greenhouse_boards` list, not from code.

hiring.cafe (build step 8 spike): its search results come from a Next.js
`_next/data/{build_id}/index.json` endpoint. A plain HTTP client (no browser,
no cookies) got a real 200 with real job data back — tested from this
machine's residential IP, not an actual GitHub Actions runner IP, so this
confirms the endpoint isn't universally blocked but isn't proof Cloudflare
never flags Actions' datacenter IP ranges specifically. Per the spec's own
guidance, this fails soft (skip and log) rather than retrying aggressively
or adding proxy infrastructure — if it does turn out blocked in Actions,
lower-frequency polling or secondary status is the fallback, not a workaround.
"""

from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

GREENHOUSE_API_BASE = "https://boards-api.greenhouse.io/v1/boards"
REQUEST_TIMEOUT_SECONDS = 15
REQUEST_DELAY_SECONDS = 1.0  # be polite to the public API between boards

# A single run can pull thousands of postings (3692 seen in one real local run) into
# memory at once before filter.py narrows them down to the handful that get queued --
# most never need their full description past the initial keyword/years-experience scan
# in filter.py, so an unbounded per-posting description is the single biggest lever on a
# run's peak memory. 20k chars comfortably covers real job descriptions (the signal
# filter.py/tailor_resume.py look for is almost always in the first few thousand chars);
# this only trims the rare pathological outlier, not real content.
MAX_DESCRIPTION_CHARS = 20_000


@dataclass
class Posting:
    source: str
    company: str
    job_id: str
    title: str
    url: str
    location: str = ""
    description_text: str = ""
    posted_at: str = ""
    ats_type: str = ""  # drives apply.py auto-submit eligibility later
    # Real coordinates when the source provides them (hiring.cafe always
    # does via _geoloc; Adzuna sometimes does; Greenhouse never does — no
    # coordinate data in its API at all). None means "unknown," not "0,0" —
    # filter.py's radius check treats these differently.
    latitude: float | None = None
    longitude: float | None = None
    # Best-effort — populated when a source's own API exposes it directly
    # (Adzuna's salary_min/salary_max/contract_time are documented, stable
    # fields; hiring.cafe/Greenhouse have no guaranteed equivalent, so these
    # stay "" / None for most postings from those sources). filter.py's
    # remote/salary/employment-type checks all fail open on these being
    # empty — a data gap should never silently drop a posting, same
    # reasoning as posted_at/latitude/longitude above.
    remote_type: str = ""  # "remote" | "hybrid" | "onsite" | ""
    employment_type: str = ""  # "full_time" | "part_time" | "contract" | ""
    salary_min: float | None = None
    salary_max: float | None = None

    def __post_init__(self) -> None:
        if len(self.description_text) > MAX_DESCRIPTION_CHARS:
            self.description_text = self.description_text[:MAX_DESCRIPTION_CHARS]

    def dedupe_key(self) -> str:
        return f"{self.source}:{self.job_id}"


def _get_with_retry_log(
    url: str, *, source_label: str, item_label: str, params: dict | None = None,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> requests.Response | None:
    """Shared GET-and-log-on-failure shape used by every search_* function
    below (5 near-identical copies before this was extracted) — never
    raises, returns None on any request error so the caller can skip that
    one board/query and keep going rather than losing the whole run."""
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        print(f"[{source_label}] {item_label}: request failed ({exc}), skipping")
        return None


def _strip_html(raw_html: str) -> str:
    text = html.unescape(raw_html or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _infer_remote_type(location_text: str) -> str:
    """Fallback when a source doesn't expose a structured remote/onsite
    field: word-boundary check on the location string itself, which real
    postings across every source commonly phrase as "Remote" or "Remote
    (Hybrid)"/"Toronto, ON (Hybrid)". Deliberately conservative — anything
    not matched stays "" (unknown), not "onsite"; a location string saying
    nothing about work arrangement isn't evidence the role is on-site."""
    text = (location_text or "").lower()
    if re.search(r"\bhybrid\b", text):
        return "hybrid"
    if re.search(r"\bremote\b", text):
        return "remote"
    return ""


_SALARY_METADATA_NAME_RE = re.compile(r"salary|compensation|pay range", re.IGNORECASE)
# Must START with a digit — real bug found live 2026-08-12: the previous
# pattern (`[\d,]+`) allows a match containing ONLY commas (zero digits),
# and DoorDash's real Greenhouse metadata stores salary as a Python-dict-
# repr string (e.g. "{'unit': 'USD', 'amount': '50.0'}") — the bare comma
# between 'USD', and 'amount': matched as if it were a number, and
# `float("".replace(",", ""))` (i.e. `float("")`) raised ValueError. That
# exception was uncaught here, which crashed search_greenhouse() entirely
# for EVERY board configured in the lane, not just the one DoorDash
# posting — both it_tech and ops_supervisor lost their entire Greenhouse
# search for two consecutive daily runs before this was found.
_SALARY_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _greenhouse_metadata_salary(metadata: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    """Greenhouse's job schema has no dedicated salary field, but companies
    can configure custom `metadata` entries (a list of {"name", "value"}
    dicts) — some genuinely use one for a posted salary range (e.g.
    "Salary Range" -> "$90,000 - $120,000"). Best-effort only: returns
    (None, None) for the common case where no such field exists or its
    value doesn't parse as two numbers, never raises — the try/except
    below is a deliberate second layer on top of the digit-requiring regex
    above, not redundant with it: a value shaped unexpectedly enough to
    still slip past the regex must still never take down the entire
    board's search over one malformed field on one job."""
    for entry in metadata:
        name = str(entry.get("name") or "")
        if not _SALARY_METADATA_NAME_RE.search(name):
            continue
        value = str(entry.get("value") or "")
        try:
            numbers = [float(n.replace(",", "")) for n in _SALARY_NUMBER_RE.findall(value)]
        except ValueError:
            continue
        if len(numbers) >= 2:
            return min(numbers[0], numbers[1]), max(numbers[0], numbers[1])
        if len(numbers) == 1:
            return numbers[0], numbers[0]
    return None, None


def search_greenhouse(boards: list[str]) -> list[Posting]:
    postings = []
    for i, token in enumerate(boards):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        url = f"{GREENHOUSE_API_BASE}/{token}/jobs"
        response = _get_with_retry_log(url, source_label="search_greenhouse", item_label=token, params={"content": "true"})
        if response is None:
            continue

        jobs: list[dict[str, Any]] = response.json().get("jobs", [])
        for job in jobs:
            location = (job.get("location") or {}).get("name", "")
            salary_min, salary_max = _greenhouse_metadata_salary(job.get("metadata") or [])
            postings.append(
                Posting(
                    source="greenhouse",
                    company=token,
                    job_id=str(job["id"]),
                    title=job.get("title", ""),
                    url=job.get("absolute_url", ""),
                    location=location,
                    description_text=_strip_html(job.get("content", "")),
                    # first_published, not updated_at — confirmed live these
                    # can differ by months (a job first posted in April can
                    # get a trivial metadata "updated_at" bump in August with
                    # nothing about the listing actually changing), which
                    # would make a stale posting look freshly-posted to a
                    # recency filter using the wrong field.
                    posted_at=job.get("first_published", ""),
                    ats_type="greenhouse",
                    remote_type=_infer_remote_type(f"{location} {job.get('title', '')}"),
                    salary_min=salary_min,
                    salary_max=salary_max,
                )
            )

    return postings


LEVER_API_BASE = "https://api.lever.co/v0/postings"

# Lever's own values, confirmed live against a real board (palantir, 311
# postings): workplaceType is exactly {"remote","hybrid","onsite"} — maps
# straight onto Posting.remote_type, no inference needed. commitment has
# more values than our employment_type enum covers (Internship,
# Fixed-Term, Scholarship, ...) — only the two that map cleanly are kept,
# everything else stays "" (unknown) rather than guessing.
_LEVER_COMMITMENT_TO_EMPLOYMENT_TYPE = {"full-time": "full_time", "contractor": "contract"}


def _lever_posting(company: str, job: dict[str, Any]) -> Posting:
    categories = job.get("categories") or {}
    location = categories.get("location", "") or ""
    workplace_type = job.get("workplaceType", "")
    if workplace_type not in ("remote", "hybrid", "onsite"):
        workplace_type = _infer_remote_type(f"{location} {job.get('text', '')}")

    posted_at = ""
    created_at = job.get("createdAt")
    if created_at:
        try:
            posted_at = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            posted_at = ""

    description_text = " ".join(
        part for part in [job.get("descriptionPlain", ""), job.get("additionalPlain", "")] if part
    )
    salary = job.get("salaryRange") or {}

    return Posting(
        source="lever",
        company=company,
        job_id=str(job["id"]),
        title=job.get("text", ""),
        url=job.get("hostedUrl", ""),
        location=location,
        description_text=description_text,
        posted_at=posted_at,
        ats_type="lever",
        remote_type=workplace_type,
        employment_type=_LEVER_COMMITMENT_TO_EMPLOYMENT_TYPE.get(
            str(categories.get("commitment", "")).strip().lower(), ""
        ),
        salary_min=salary.get("min"),
        salary_max=salary.get("max"),
    )


def search_lever(companies: list[str]) -> list[Posting]:
    """Lever's public postings API, same shape as Greenhouse: one company
    board at a time, no key needed. `companies` are Lever's own url slugs
    (e.g. "palantir" for jobs.lever.co/palantir)."""
    postings = []
    for i, company in enumerate(companies):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        url = f"{LEVER_API_BASE}/{company}"
        response = _get_with_retry_log(url, source_label="search_lever", item_label=company, params={"mode": "json"})
        if response is None:
            continue

        for job in response.json():
            postings.append(_lever_posting(company, job))

    return postings


ASHBY_API_BASE = "https://api.ashbyhq.com/posting-api/job-board"

# Confirmed live against real boards (ramp: 128 postings, linear: 28):
# workplaceType is {"OnSite","Remote","Hybrid"} (mixed case, unlike
# Lever's lowercase) and employmentType is {"FullTime","Contract","Intern",
# ...} — same "only map what maps cleanly" approach as Lever above. No
# compensation field appears without a special query param this endpoint
# doesn't document as public, so salary stays unset (fails open, same as
# every other best-effort field).
_ASHBY_EMPLOYMENT_TYPE_MAP = {"fulltime": "full_time", "parttime": "part_time", "contract": "contract"}


def _ashby_posting(board: str, job: dict[str, Any]) -> Posting:
    location = job.get("location", "") or ""
    workplace_type = str(job.get("workplaceType", "")).strip().lower()
    if workplace_type not in ("remote", "hybrid", "onsite"):
        workplace_type = _infer_remote_type(f"{location} {job.get('title', '')}")

    return Posting(
        source="ashby",
        company=board,
        job_id=str(job["id"]),
        title=job.get("title", ""),
        url=job.get("jobUrl", ""),
        location=location,
        description_text=job.get("descriptionPlain", ""),
        posted_at=job.get("publishedAt", ""),
        ats_type="ashby",
        remote_type=workplace_type,
        employment_type=_ASHBY_EMPLOYMENT_TYPE_MAP.get(
            str(job.get("employmentType", "")).strip().lower(), ""
        ),
    )


def search_ashby(boards: list[str]) -> list[Posting]:
    """Ashby's public job-board API, same one-board-at-a-time shape as
    Greenhouse/Lever. `boards` are Ashby's own url slugs (e.g. "linear" for
    jobs.ashbyhq.com/linear)."""
    postings = []
    for i, board in enumerate(boards):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        url = f"{ASHBY_API_BASE}/{board}"
        response = _get_with_retry_log(url, source_label="search_ashby", item_label=board)
        if response is None:
            continue

        for job in response.json().get("jobs", []):
            postings.append(_ashby_posting(board, job))

    return postings


HIRING_CAFE_HOMEPAGE_URL = "https://hiringcafe.com/"
HIRING_CAFE_DATA_ENDPOINT = "https://hiringcafe.com/_next/data/{build_id}/index.json"

_UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# hiring.cafe hits from an ATS we also query directly get mapped to that
# same source/job_id scheme (search_greenhouse()/search_lever()/
# search_ashby()), so a posting found both ways collapses to one
# dedupe_key() instead of risking a duplicate application. Keyed by
# hit["source"] — confirmed live 2026-08-10 that hiring.cafe tags these
# exactly as "grnhse"/"lever"/"ashby".
#
# Real bug caught before shipping, live: Lever's apply_url from hiring.cafe
# ends in "/apply" (e.g. ".../41136e95-84b3-.../apply") — a naive
# "capture whatever's after the company slug" regex would grab "apply" as
# the job id instead of the real UUID, silently breaking the dedupe this
# whole mechanism exists for. Matching the UUID shape explicitly instead of
# "the next path segment" sidesteps that regardless of what (if anything)
# follows it in the URL.
_ATS_APPLY_URL_PATTERNS: dict[str, tuple[str, re.Pattern]] = {
    "grnhse": ("greenhouse", re.compile(r"greenhouse\.io/([^/]+)/jobs/(\d+)")),
    "lever": ("lever", re.compile(rf"jobs\.lever\.co/([^/]+)/({_UUID_RE})")),
    "ashby": ("ashby", re.compile(rf"jobs\.ashbyhq\.com/([^/]+)/({_UUID_RE})")),
}


def _hiring_cafe_build_id() -> str:
    """The search endpoint is pinned to hiring.cafe's current Next.js build
    and changes on every redeploy, so it's rediscovered on every call (also
    via a plain GET, not a browser) rather than hardcoded."""
    response = requests.get(HIRING_CAFE_HOMEPAGE_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    match = re.search(r'"buildId":"([^"]+)"', response.text)
    if not match:
        raise RuntimeError("hiring.cafe homepage didn't contain a Next.js buildId — page structure may have changed")
    return match.group(1)


def _hiring_cafe_posting(hit: dict[str, Any]) -> Posting:
    """Normalizes a hit into our shared Posting shape. Hits from ATSs we
    also query directly (Greenhouse, Lever, Ashby) are mapped to that same
    source/job_id scheme (see _ATS_APPLY_URL_PATTERNS), so a posting found
    both directly and via this aggregator collapses to one dedupe_key()
    instead of risking a duplicate application. Postings from ATSs we
    haven't integrated directly (Workday, iCIMS, BambooHR, ...) keep their
    real source name — apply.py hasn't been taught those forms' field ids,
    so their fields won't match any known standard/EEOC field and they'll
    naturally fall through to hold-for-review rather than risk a wrong
    auto-fill."""
    apply_url = hit.get("apply_url", "")
    source = hit["source"]

    pattern_entry = _ATS_APPLY_URL_PATTERNS.get(source)
    ats_match = pattern_entry[1].search(apply_url) if pattern_entry else None
    if ats_match:
        mapped_ats_type = pattern_entry[0]
        board_token, job_id = ats_match.groups()
        posting_source, posting_job_id, company, ats_type = mapped_ats_type, job_id, board_token, mapped_ats_type
    else:
        posting_source = "hiring_cafe"
        posting_job_id = hit["id"]
        company = (hit.get("enriched_company_data") or {}).get("name") or hit.get("board_token", "")
        ats_type = source

    v5 = hit.get("v5_processed_job_data") or {}
    description_text = " ".join(
        part for part in [
            v5.get("core_job_title", ""),
            v5.get("requirements_summary", ""),
            ", ".join(v5.get("technical_tools") or []),
            ", ".join(v5.get("role_activities") or []),
        ] if part
    )

    # A list containing one {"lat":..., "lon":...} dict, confirmed live —
    # always present on real hits, unlike Adzuna's sometimes-null lat/long.
    geoloc = (hit.get("_geoloc") or [{}])[0]
    location = v5.get("formatted_workplace_location", "")

    # v5_processed_job_data's own field names for these vary across hits and
    # haven't been enumerated from a live raw response — best-effort direct
    # read via a small set of plausible keys (per hiring.cafe's naming
    # convention elsewhere in v5), falling back to inferring from the
    # location string, same as Greenhouse.
    remote_type = str(v5.get("workplace_type") or v5.get("remote_type") or "").lower()
    if remote_type not in ("remote", "hybrid", "onsite"):
        remote_type = _infer_remote_type(f"{location} {v5.get('core_job_title', '')}")
    employment_type = str(v5.get("employment_type") or v5.get("commitment") or "").lower().replace(" ", "_")
    if employment_type not in ("full_time", "part_time", "contract"):
        employment_type = ""
    salary_info = v5.get("yearly_compensation_range") or v5.get("salary_range") or {}
    salary_min = salary_info.get("min") if isinstance(salary_info, dict) else None
    salary_max = salary_info.get("max") if isinstance(salary_info, dict) else None

    return Posting(
        source=posting_source,
        company=company,
        job_id=str(posting_job_id),
        title=(hit.get("job_information") or {}).get("title", ""),
        url=apply_url,
        location=location,
        description_text=description_text,
        posted_at=v5.get("estimated_publish_date", ""),
        ats_type=ats_type,
        latitude=geoloc.get("lat"),
        longitude=geoloc.get("lon"),
        remote_type=remote_type,
        employment_type=employment_type,
        salary_min=salary_min,
        salary_max=salary_max,
    )


# Unlike Adzuna (paginated, explicitly capped at 3 pages/query below), this endpoint
# returns every hit for a query in one response with no pagination at all -- a real run
# pulled 3692 unique postings total across sources for one lane's 6 keywords, and this
# uncapped source was the dominant contributor (confirmed against Render's memory graph
# spiking exactly at the hourly scheduled-run trigger, 2026-08-17). Capped per query, same
# defensive reasoning as Adzuna's own cap: bound worst-case memory for one run, not chase
# a slow leak that isn't there.
HIRING_CAFE_MAX_HITS_PER_QUERY = 150


def search_hiring_cafe(queries: list[str]) -> list[Posting]:
    try:
        build_id = _hiring_cafe_build_id()
    except (requests.RequestException, RuntimeError) as exc:
        print(f"[search_hiring_cafe] could not resolve build id ({exc}), skipping source")
        return []

    url = HIRING_CAFE_DATA_ENDPOINT.format(build_id=build_id)
    postings_by_key: dict[str, Posting] = {}

    for i, query in enumerate(queries):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)
        response = _get_with_retry_log(
            url, source_label="search_hiring_cafe", item_label=f"query {query!r}",
            params={"searchState": json.dumps({"searchQuery": query})},
        )
        if response is None:
            continue

        hits = response.json().get("pageProps", {}).get("ssrHits", [])[:HIRING_CAFE_MAX_HITS_PER_QUERY]
        for hit in hits:
            posting = _hiring_cafe_posting(hit)
            postings_by_key[posting.dedupe_key()] = posting

    return list(postings_by_key.values())


ADZUNA_API_BASE = "https://api.adzuna.com/v1/api/jobs"
ADZUNA_RESULTS_PER_PAGE = 50
# Only page 1 was ever fetched before — real volume left unfetched, and
# Adzuna's small/independent-employer postings are exactly where a listed
# contact email (cold_email.py's find_contact) actually shows up, unlike the
# big-tech ATS boards which never include one. Capped at 3 pages/query (150
# results) to bound cost; stops early once a page comes back short (no more
# results for that query).
ADZUNA_MAX_PAGES = 3


_ADZUNA_CONTRACT_TIME_TO_EMPLOYMENT_TYPE = {"full_time": "full_time", "part_time": "part_time"}


def _adzuna_posting(job: dict[str, Any]) -> Posting:
    # Adzuna is itself an aggregator — redirect_url can point to almost any
    # career site, not just ATSs we know how to parse — so unlike the
    # hiring.cafe/Greenhouse normalization, there's no general way to
    # collapse an Adzuna hit with the same posting found via another source.
    # A rare cross-source duplicate is possible; not solved here.
    location = (job.get("location") or {}).get("display_name", "")
    # Adzuna's documented, stable schema: contract_time is "full_time" /
    # "part_time"; contract_type ("permanent"/"contract") maps a real
    # contract listing to our "contract" employment_type, contract_time
    # otherwise takes priority when both happen to be present.
    employment_type = _ADZUNA_CONTRACT_TIME_TO_EMPLOYMENT_TYPE.get(job.get("contract_time") or "", "")
    if not employment_type and job.get("contract_type") == "contract":
        employment_type = "contract"
    return Posting(
        source="adzuna",
        company=(job.get("company") or {}).get("display_name", ""),
        job_id=str(job["id"]),
        title=job.get("title", ""),
        url=job.get("redirect_url", ""),
        location=location,
        description_text=job.get("description", ""),
        posted_at=job.get("created", ""),
        ats_type="adzuna",
        # Confirmed live: present on some real listings, null on others —
        # not every Adzuna job carries coordinates.
        latitude=job.get("latitude"),
        longitude=job.get("longitude"),
        remote_type=_infer_remote_type(f"{location} {job.get('title', '')}"),
        employment_type=employment_type,
        salary_min=job.get("salary_min"),
        salary_max=job.get("salary_max"),
    )


def search_adzuna(queries: list[str], country: str, app_id: str, app_key: str) -> list[Posting]:
    """Adzuna's public API, documented and stable (unlike hiring.cafe's
    internal endpoint) — one query per lane keyword, results merged and
    deduped by posting id, same pattern as the other sources."""
    postings_by_key: dict[str, Posting] = {}
    first_request = True

    for query in queries:
        for page in range(1, ADZUNA_MAX_PAGES + 1):
            if not first_request:
                time.sleep(REQUEST_DELAY_SECONDS)
            first_request = False

            url = f"{ADZUNA_API_BASE}/{country}/search/{page}"
            response = _get_with_retry_log(
                url, source_label="search_adzuna", item_label=f"query {query!r} page {page}",
                params={
                    "app_id": app_id,
                    "app_key": app_key,
                    "what": query,
                    "results_per_page": ADZUNA_RESULTS_PER_PAGE,
                    "content-type": "application/json",
                },
            )
            if response is None:
                break

            results = response.json().get("results", [])
            for job in results:
                posting = _adzuna_posting(job)
                postings_by_key[posting.dedupe_key()] = posting

            if len(results) < ADZUNA_RESULTS_PER_PAGE:
                break  # short page — no more results for this query

    return list(postings_by_key.values())
