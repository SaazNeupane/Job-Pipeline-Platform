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
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

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


WORKDAY_RESULTS_PER_PAGE = 20
# Confirmed live against workday.wd5.myworkdayjobs.com/Workday (342 real postings):
# the list endpoint (`POST .../wday/cxs/{tenant}/{site}/jobs`) has no per-company cap
# and no description field — only a job-detail fetch (one request per posting) has
# jobDescription. Doing that per posting would multiply request count by however many
# jobs a board lists (342 here); same "bound worst-case cost, don't chase every field"
# reasoning as hiring.cafe/Adzuna's own page caps, so this stays list-only for now —
# filter.py's keyword/years-experience checks fall back to title-only matching when
# description_text is empty, same fail-open behavior as any other missing field.
WORKDAY_MAX_PAGES = 5

_WORKDAY_TIME_TYPE_TO_EMPLOYMENT_TYPE = {"full time": "full_time", "part time": "part_time", "contract": "contract"}
# Confirmed live: remoteType facet values are exactly {"Flex","Onsite","Remote"}.
# "Flex" (Workday's own term for a mixed/flexible arrangement) doesn't map cleanly to
# our hybrid/onsite/remote enum, so it's left unmapped and falls through to the same
# location-text inference every other source uses for unrecognized values.
_WORKDAY_REMOTE_TYPE_MAP = {"remote": "remote", "onsite": "onsite"}


def _post_with_retry_log(
    url: str, *, source_label: str, item_label: str, json_body: dict,
) -> requests.Response | None:
    try:
        response = requests.post(url, json=json_body, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        print(f"[{source_label}] {item_label}: request failed ({exc}), skipping")
        return None


def _workday_posting(host: str, site: str, tenant: str, job: dict[str, Any]) -> Posting:
    location = job.get("locationsText", "") or ""
    title = job.get("title", "")
    remote_type = _WORKDAY_REMOTE_TYPE_MAP.get(str(job.get("remoteType", "")).strip().lower(), "")
    if not remote_type:
        remote_type = _infer_remote_type(f"{location} {title}")

    req_ids = job.get("bulletFields") or []
    job_id = str(req_ids[0]) if req_ids else str(job.get("externalPath", ""))

    return Posting(
        source="workday",
        company=tenant,
        job_id=job_id,
        title=title,
        url=f"https://{host}/{site}{job.get('externalPath', '')}",
        location=location,
        posted_at=job.get("postedOn", ""),
        ats_type="workday",
        remote_type=remote_type,
        employment_type=_WORKDAY_TIME_TYPE_TO_EMPLOYMENT_TYPE.get(
            str(job.get("timeType", "")).strip().lower(), ""
        ),
    )


def search_workday(boards: list[str]) -> list[Posting]:
    """Workday's public job-board API — unlike Greenhouse/Lever/Ashby, one board needs
    three identifiers, not one: the tenant's own myworkdayjobs.com host (varies per
    company, e.g. "workday.wd5.myworkdayjobs.com"), the tenant slug, and the site name
    (Workday's term for a specific careers page under that tenant). `boards` entries are
    "host/tenant/site" strings, e.g. "workday.wd5.myworkdayjobs.com/workday/Workday".
    Confirmed live against that exact board: POST with a JSON body (not query params,
    unlike every other source here), no key needed.
    """
    postings = []
    for i, board in enumerate(boards):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        try:
            host, tenant, site = board.split("/", 2)
        except ValueError:
            print(f"[search_workday] {board!r}: expected \"host/tenant/site\", skipping")
            continue

        url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        offset = 0
        for page in range(WORKDAY_MAX_PAGES):
            if page > 0:
                time.sleep(REQUEST_DELAY_SECONDS)
            response = _post_with_retry_log(
                url, source_label="search_workday", item_label=f"{board} offset {offset}",
                json_body={"appliedFacets": {}, "limit": WORKDAY_RESULTS_PER_PAGE, "offset": offset, "searchText": ""},
            )
            if response is None:
                break

            jobs = response.json().get("jobPostings", [])
            for job in jobs:
                postings.append(_workday_posting(host, site, tenant, job))

            if len(jobs) < WORKDAY_RESULTS_PER_PAGE:
                break  # short page — no more results for this board
            offset += WORKDAY_RESULTS_PER_PAGE

    return postings


SMARTRECRUITERS_API_BASE = "https://api.smartrecruiters.com/v1/companies"
SMARTRECRUITERS_JOBS_URL = "https://jobs.smartrecruiters.com/{company}/{job_id}"
SMARTRECRUITERS_RESULTS_PER_PAGE = 100
# Confirmed live 2026-08-19 against a real board (Visa, 2 postings): list
# response's "ref" field is the api.smartrecruiters.com endpoint, NOT a
# human-clickable posting page (real bug caught before shipping -- would
# have queued postings whose "apply" link 404s for a person opening it) --
# jobs.smartrecruiters.com/{company}/{id} confirmed to 200/resolve directly
# instead. typeOfEmployment.id values confirmed live: "permanent" (maps to
# full_time), others ("intern"/"temporary"/"contract") left unmapped per the
# same "only map what maps cleanly" rule as lever/ashby above.
SMARTRECRUITERS_MAX_PAGES = 5
_SMARTRECRUITERS_EMPLOYMENT_TYPE_MAP = {"permanent": "full_time", "contract": "contract", "temporary": "contract"}


def _smartrecruiters_posting(company: str, job: dict[str, Any]) -> Posting:
    location = job.get("location") or {}
    location_text = ", ".join(
        part for part in [location.get("city"), location.get("region"), location.get("country")] if part
    )
    if location.get("remote"):
        remote_type = "remote"
    elif location.get("hybrid"):
        remote_type = "hybrid"
    else:
        remote_type = _infer_remote_type(f"{location_text} {job.get('name', '')}")
    job_id = str(job["id"])
    return Posting(
        source="smartrecruiters",
        company=company,
        job_id=job_id,
        title=job.get("name", ""),
        url=SMARTRECRUITERS_JOBS_URL.format(company=company, job_id=job_id),
        location=location_text,
        posted_at=job.get("releasedDate", ""),
        ats_type="smartrecruiters",
        remote_type=remote_type,
        employment_type=_SMARTRECRUITERS_EMPLOYMENT_TYPE_MAP.get(
            str((job.get("typeOfEmployment") or {}).get("id", "")).strip().lower(), ""
        ),
    )


def search_smartrecruiters(companies: list[str]) -> list[Posting]:
    """SmartRecruiters' public Postings API, same one-company-at-a-time
    shape as Greenhouse. `companies` are SmartRecruiters' own company
    identifiers. The list endpoint doesn't include the full job
    description (only the detail endpoint does, one request per posting) --
    same list-only tradeoff as search_workday, description_text stays
    empty and filter.py falls back to title-only matching."""
    postings = []
    for i, company in enumerate(companies):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        url = f"{SMARTRECRUITERS_API_BASE}/{company}/postings"
        offset = 0
        for page in range(SMARTRECRUITERS_MAX_PAGES):
            if page > 0:
                time.sleep(REQUEST_DELAY_SECONDS)
            response = _get_with_retry_log(
                url, source_label="search_smartrecruiters", item_label=f"{company} offset {offset}",
                params={"limit": SMARTRECRUITERS_RESULTS_PER_PAGE, "offset": offset},
            )
            if response is None:
                break

            jobs = response.json().get("content", [])
            for job in jobs:
                postings.append(_smartrecruiters_posting(company, job))

            if len(jobs) < SMARTRECRUITERS_RESULTS_PER_PAGE:
                break  # short page -- no more results for this company
            offset += SMARTRECRUITERS_RESULTS_PER_PAGE

    return postings


WORKABLE_API_BASE = "https://apply.workable.com/api/v1/widget/accounts"
# Not confirmed live this session -- couldn't find a real active account slug
# to test against (jobs.workable.com's own listing page is JS-rendered, no
# plain HTML links to scrape one from). Field names below follow Workable's
# own published widget-response shape (location nested under "location" with
# city/region/country/telecommuting/workplace_type, per Workable's help docs)
# -- same defensive-parsing caveat as smartrecruiters above, verify against a
# real account before relying on this in production.
_WORKABLE_EMPLOYMENT_TYPE_MAP = {"full-time": "full_time", "part-time": "part_time", "contract": "contract"}


def _workable_posting(account: str, job: dict[str, Any]) -> Posting:
    location = job.get("location") or {}
    location_text = location.get("location_str") or ", ".join(
        part for part in [location.get("city"), location.get("region"), location.get("country")] if part
    )
    workplace_type = str(location.get("workplace_type", "")).strip().lower()
    if workplace_type not in ("remote", "hybrid", "onsite"):
        workplace_type = "remote" if location.get("telecommuting") else _infer_remote_type(f"{location_text} {job.get('title', '')}")
    return Posting(
        source="workable",
        company=account,
        job_id=str(job.get("shortcode") or job.get("id") or job.get("title", "")),
        title=job.get("title", "") or job.get("full_title", ""),
        url=job.get("url", "") or job.get("application_url", ""),
        location=location_text,
        posted_at=job.get("published_on", "") or job.get("created_at", ""),
        ats_type="workable",
        remote_type=workplace_type,
        employment_type=_WORKABLE_EMPLOYMENT_TYPE_MAP.get(
            str(job.get("employment_type", "")).strip().lower(), ""
        ),
    )


def search_workable(accounts: list[str]) -> list[Posting]:
    """Workable's public widget API, same one-account-at-a-time shape as
    Lever. `accounts` are Workable's own account subdomains. The widget
    endpoint doesn't include the full job description either (a separate
    per-job request does) -- same list-only tradeoff as smartrecruiters
    above."""
    postings = []
    for i, account in enumerate(accounts):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        url = f"{WORKABLE_API_BASE}/{account}"
        response = _get_with_retry_log(url, source_label="search_workable", item_label=account)
        if response is None:
            continue

        for job in response.json().get("jobs", []):
            postings.append(_workable_posting(account, job))

    return postings


RECRUITEE_API_BASE = "https://{company}.recruitee.com/api/offers/"
# Not confirmed live this session -- same defensive-parsing caveat as above.
# Unlike smartrecruiters/workable, Recruitee's public offers endpoint is
# documented to include the full HTML description directly in the list
# response, so description_text is populated here (stripped, same as
# greenhouse's content field).
_RECRUITEE_EMPLOYMENT_TYPE_MAP = {"full_time": "full_time", "part_time": "part_time", "contract": "contract"}


def _recruitee_posting(company: str, job: dict[str, Any]) -> Posting:
    locations = job.get("locations") or []
    location_text = ", ".join(loc.get("city", "") for loc in locations if loc.get("city")) or (job.get("location") or "")
    remote_type = "remote" if job.get("remote") else _infer_remote_type(f"{location_text} {job.get('title', '')}")
    return Posting(
        source="recruitee",
        company=company,
        job_id=str(job["id"]),
        title=job.get("title", ""),
        url=job.get("careers_url", "") or job.get("careers_apply_url", ""),
        location=location_text,
        description_text=_strip_html(job.get("description", "")),
        posted_at=job.get("published_at", "") or job.get("created_at", ""),
        ats_type="recruitee",
        remote_type=remote_type,
        employment_type=_RECRUITEE_EMPLOYMENT_TYPE_MAP.get(
            str(job.get("employment_type", "")).strip().lower(), ""
        ),
    )


def search_recruitee(companies: list[str]) -> list[Posting]:
    """Recruitee's public offers API, same one-company-at-a-time shape as
    Greenhouse. `companies` are Recruitee's own company subdomains."""
    postings = []
    for i, company in enumerate(companies):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        url = RECRUITEE_API_BASE.format(company=company)
        response = _get_with_retry_log(url, source_label="search_recruitee", item_label=company)
        if response is None:
            continue

        for job in response.json().get("offers", []):
            postings.append(_recruitee_posting(company, job))

    return postings


BREEZY_API_BASE = "https://{company}.breezy.hr/json"
# Not confirmed live this session -- same defensive-parsing caveat as above.
# This endpoint returns a bare JSON array (not wrapped in an object), unlike
# every other source here.
_BREEZY_EMPLOYMENT_TYPE_MAP = {"full_time": "full_time", "part_time": "part_time", "contract": "contract"}


def _breezy_posting(company: str, job: dict[str, Any]) -> Posting:
    location = job.get("location") or {}
    location_text = location.get("name", "") or ""
    return Posting(
        source="breezy",
        company=company,
        job_id=str(job["id"]),
        title=job.get("name", ""),
        url=job.get("url", ""),
        location=location_text,
        posted_at=job.get("published_date", ""),
        ats_type="breezy",
        remote_type=_infer_remote_type(f"{location_text} {job.get('name', '')}"),
        employment_type=_BREEZY_EMPLOYMENT_TYPE_MAP.get(
            str(job.get("type", "")).strip().lower().replace(" ", "_"), ""
        ),
    )


def search_breezy(companies: list[str]) -> list[Posting]:
    """Breezy's public JSON board API, same one-company-at-a-time shape as
    Greenhouse. `companies` are Breezy's own company subdomains. No full
    description in this endpoint either -- same list-only tradeoff as
    smartrecruiters/workable above."""
    postings = []
    for i, company in enumerate(companies):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        url = BREEZY_API_BASE.format(company=company)
        response = _get_with_retry_log(url, source_label="search_breezy", item_label=company)
        if response is None:
            continue

        jobs = response.json()
        if isinstance(jobs, list):
            for job in jobs:
                postings.append(_breezy_posting(company, job))

    return postings


COMPANY_SITE_MAX_SITEMAPS_PER_SITE = 5
# Real per-URL page fetch below (no structured job list exists for a generic
# company site, unlike every JSON-API source above) -- capped hard, same
# bounded-cost reasoning as every other MAX_PAGES/MAX_HITS constant in this
# module, just at the individual-job-page level instead of the results-page
# level.
COMPANY_SITE_MAX_JOB_PAGES_PER_SITE = 30
_JOB_URL_KEYWORDS_RE = re.compile(r"job|career|vacanc|opening|position|employment", re.IGNORECASE)
_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESC_RE = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', re.IGNORECASE)


def _sitemap_locs(root: ET.Element) -> list[str]:
    """<loc> entries, regardless of whether the sitemap declares the standard
    sitemaps.org namespace -- real sitemaps in the wild are inconsistent
    about this, so matching by local tag name (stripping any `{ns}` prefix)
    instead of a namespace-qualified xpath is what actually works across
    real sites, not just spec-compliant ones."""
    return [el.text.strip() for el in root.iter() if el.tag.split("}")[-1] == "loc" and el.text]


def _discover_sitemap_urls(base_url: str) -> list[str]:
    """Finds real sitemap URLs for a site: `{base}/sitemap.xml` first, then
    whatever robots.txt's own `Sitemap:` directive declares -- some real
    sites only declare it there (a non-default path/filename), not at the
    conventional location."""
    candidates = [urljoin(base_url, "/sitemap.xml")]
    robots = _get_with_retry_log(
        urljoin(base_url, "/robots.txt"), source_label="search_company_sites", item_label=f"{base_url} robots.txt",
    )
    if robots is not None:
        for line in robots.text.splitlines():
            if line.strip().lower().startswith("sitemap:"):
                candidates.append(line.split(":", 1)[1].strip())

    seen: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.append(candidate)
    return seen


def _job_urls_from_sitemaps(base_url: str) -> list[str]:
    job_urls: list[str] = []
    queue = _discover_sitemap_urls(base_url)[:COMPANY_SITE_MAX_SITEMAPS_PER_SITE]
    fetched = 0

    while queue and fetched < COMPANY_SITE_MAX_SITEMAPS_PER_SITE:
        url = queue.pop(0)
        if fetched > 0:
            time.sleep(REQUEST_DELAY_SECONDS)
        fetched += 1

        response = _get_with_retry_log(url, source_label="search_company_sites", item_label=url)
        if response is None:
            continue
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            print(f"[search_company_sites] {url}: not valid XML ({exc}), skipping")
            continue

        locs = _sitemap_locs(root)
        if root.tag.split("}")[-1] == "sitemapindex":
            # A sitemap *index* -- its <loc> entries are more sitemaps, not job
            # pages, so queue them instead of treating them as job candidates.
            queue.extend(locs[: COMPANY_SITE_MAX_SITEMAPS_PER_SITE - fetched])
        else:
            job_urls.extend(loc for loc in locs if _JOB_URL_KEYWORDS_RE.search(loc))

    return job_urls[:COMPANY_SITE_MAX_JOB_PAGES_PER_SITE]


def _company_site_posting(company: str, job_url: str) -> Posting | None:
    response = _get_with_retry_log(job_url, source_label="search_company_sites", item_label=job_url)
    if response is None:
        return None

    title_match = _TITLE_TAG_RE.search(response.text)
    title = html.unescape(title_match.group(1)).strip() if title_match else ""
    if not title:
        return None  # nothing usable to queue without even a title

    desc_match = _META_DESC_RE.search(response.text)
    description_text = (
        html.unescape(desc_match.group(1)).strip() if desc_match else _strip_html(response.text)[:2000]
    )

    return Posting(
        source="company_site",
        company=company,
        job_id=job_url,
        title=title,
        url=job_url,
        description_text=description_text,
        ats_type="company_site",
        remote_type=_infer_remote_type(f"{title} {description_text[:500]}"),
    )


def search_company_sites(sites: list[str]) -> list[Posting]:
    """No-ATS fallback source, for companies with a custom careers page and
    no known ATS. Discovers real job postings via the site's own
    sitemap.xml (or robots.txt's declared Sitemap: directive) instead of
    scraping arbitrary page HTML/navigation -- a sitemap is a stable,
    crawl-intended contract, unlike page structure, so this doesn't break on
    every redesign the way a hand-written CSS-selector scraper would.
    `sites` entries are "company_name|https://company.com" strings.

    Job-looking URLs are picked out of the sitemap by path keywords
    (job/career/vacancy/opening/position/employment). Each candidate URL
    then gets ONE real page fetch to pull a title (<title> tag) and
    description (meta description, else a stripped-body fallback) -- unlike
    every JSON-API source above, there's no structured job list here, so
    this is genuine per-URL scraping, bounded per site
    (COMPANY_SITE_MAX_JOB_PAGES_PER_SITE) to cap cost. No structured
    location/salary/employment-type data exists at all for this source --
    those fields fail open (empty/None), same as any other source's missing
    field, not "assume false."

    False-positive URLs (e.g. a blog post whose slug happens to contain
    "career") are expected and acceptable, not a bug to chase down --  same
    principle as the whole pipeline: a human swipes right/left on every
    posting before anything real happens (see run_pipeline.py's module
    docstring), so recall matters more here than precision.
    """
    postings: list[Posting] = []
    for i, site in enumerate(sites):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        try:
            company, base_url = site.split("|", 1)
        except ValueError:
            print(f"[search_company_sites] {site!r}: expected \"company_name|https://...\", skipping")
            continue

        job_urls = _job_urls_from_sitemaps(base_url)
        if not job_urls:
            print(f"[search_company_sites] {company}: no sitemap-discoverable job URLs found, skipping")
            continue

        for j, job_url in enumerate(job_urls):
            if j > 0:
                time.sleep(REQUEST_DELAY_SECONDS)
            posting = _company_site_posting(company, job_url)
            if posting is not None:
                postings.append(posting)

    return postings


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
