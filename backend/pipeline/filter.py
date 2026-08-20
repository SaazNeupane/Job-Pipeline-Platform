"""Match postings against lane keywords/seniority and dedupe against the Sheet
log (spec Section 4, step 2). Also extracts which lane terms a posting
matched — reused by tailor_resume.py in build step 6.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

from pipeline.config import Applicant, Lane
from pipeline.search import Posting
from pipeline.text_match import word_boundary_match

RECENCY_MAX_AGE_DAYS = 14
EARTH_RADIUS_KM = 6371.0

# A lane's seniority_max is a cap on a small ladder (intern < entry <
# intermediate < senior), not just a binary entry-only switch -- each tier
# below is title-based signal for where a posting sits on that ladder. A
# title matching none of them defaults to "entry", same as the original
# entry-only behavior before this ladder existed (most entry postings never
# bother labeling themselves "entry-level" at all, so treating unlabeled
# titles as senior-by-default would silently exclude the bulk of real entry
# postings from an entry-capped lane).
INTERN_TITLE_TERMS = ["intern", "internship", "co-op", "coop", "trainee"]
JUNIOR_TITLE_TERMS = ["junior", "jr.", "entry level", "entry-level", "new grad", "new-grad"]
# "intermediate"/"ii"/"iii"/"iv" added 2026-08-06 after a real live gap:
# "Intermediate Backend Engineer" isn't "senior"-labeled at all, so the
# original entry-only list let it straight through an entry-capped lane --
# the intent is "not entry-level", not just "not literally called senior."
MID_TITLE_TERMS = ["intermediate", "mid-level", "mid level", "ii", "iii", "iv"]
SENIOR_TITLE_TERMS = [
    "senior", "sr.", "staff", "principal", "director", "vp", "vice president",
    "head of", "manager", "executive", "lead",
]

SENIORITY_LEVELS = ["intern", "entry", "intermediate", "senior"]
_SENIORITY_RANK = {level: i for i, level in enumerate(SENIORITY_LEVELS)}


def _title_seniority_rank(title: str) -> int:
    if any(word_boundary_match(term, title) for term in SENIOR_TITLE_TERMS):
        return _SENIORITY_RANK["senior"]
    if any(word_boundary_match(term, title) for term in MID_TITLE_TERMS):
        return _SENIORITY_RANK["intermediate"]
    if any(word_boundary_match(term, title) for term in INTERN_TITLE_TERMS):
        return _SENIORITY_RANK["intern"]
    if any(word_boundary_match(term, title) for term in JUNIOR_TITLE_TERMS):
        return _SENIORITY_RANK["entry"]
    return _SENIORITY_RANK["entry"]

# Pulls a stated minimum years-of-experience requirement out of a posting's
# own text — "5+ years of experience", "3-5 years experience",
# "2 years professional experience". Requires the word "experience" nearby
# (not just any "N years") so it doesn't false-positive on unrelated phrases
# like "5 years of Python" that aren't a tenure requirement at all.
_YEARS_EXPERIENCE_RE = re.compile(
    r"(\d{1,2})\+?\s*(?:-\s*\d{1,2}\s*)?\+?\s*years?(?:\s+of)?\s+"
    r"(?:relevant\s+|professional\s+|related\s+|work(?:ing)?\s+)?experience",
    re.IGNORECASE,
)


def extract_required_years(text: str) -> int | None:
    """Best-effort minimum years-of-experience requirement stated in a
    posting's own title+description text. None when no such phrase is
    found — never guessed at, and never invented for a posting that simply
    doesn't say. When more than one such phrase appears, returns the
    highest — the more conservative reading for an exclusion check."""
    matches = _YEARS_EXPERIENCE_RE.findall(text)
    return max((int(m) for m in matches), default=None)

# Matched against a whole segment of a location string, never as a
# substring of a city name — several real Ontario cities (London, Cambridge,
# Kitchener, Windsor...) share a name with a non-Canadian city, so matching
# on city name would misclassify them in both directions.
#
# Keyed by the same lowercase country code convention as profile.yaml's
# adzuna_country/target_countries (e.g. "ca", "us", "gb", "au"). Each entry
# splits into two tiers deliberately (see _matches_target_countries): short
# abbreviations are only ever checked against comma/semicolon-delimited
# segments (the classic "City, Province/State" format), not the broader
# hyphen/slash/"or"-based splitting used for full names — "on-site" is
# common, ordinary phrasing in location strings and hyphen-splits into a
# bare "on" segment, which would otherwise be misread as Ontario. Only a
# handful of countries are curated here (the ones real postings have
# actually been checked against) — anything else falls back to a plain
# substring match on the country name the user typed, see
# _matches_target_countries.
COUNTRY_LOCATION_ALIASES: dict[str, dict[str, set[str]]] = {
    "ca": {
        "abbreviations": {"on", "bc", "ab", "qc", "mb", "sk", "ns", "nb", "nl", "pe", "pei", "yt", "nt", "nu"},
        "full_names": {
            "canada",
            "ontario", "british columbia", "alberta", "quebec", "manitoba", "saskatchewan",
            "nova scotia", "new brunswick", "newfoundland and labrador", "newfoundland",
            "prince edward island", "yukon", "northwest territories", "nunavut",
        },
    },
    "us": {
        "abbreviations": {
            "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in", "ia",
            "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
            "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt",
            "va", "wa", "wv", "wi", "wy", "dc", "usa",
        },
        "full_names": {"united states", "united states of america", "usa", "u.s.", "u.s.a."},
    },
    "gb": {
        "abbreviations": {"uk", "gb"},
        "full_names": {
            "united kingdom", "england", "scotland", "wales", "northern ireland", "great britain",
        },
    },
    "au": {
        "abbreviations": {"nsw", "vic", "qld", "wa", "sa", "tas", "act", "nt"},
        "full_names": {
            "australia", "new south wales", "victoria", "queensland",
            "western australia", "south australia", "tasmania",
        },
    },
}


def _matches_target_countries(location: str, target_countries: list[str]) -> bool:
    """Positive match only — an unrecognized, ambiguous ("Remote"), or blank
    location is treated as NOT in any target country rather than "probably
    fine." Same reasoning as the original Canada-only check this replaces:
    the safer failure mode is dropping an actually-eligible posting with a
    vague location string, not letting an out-of-scope one through
    unchecked — this is a hard eligibility rule, not a quality heuristic.

    For each entry in target_countries: if it matches a curated country code
    in COUNTRY_LOCATION_ALIASES (see that dict for why the two-tier
    abbreviation/full-name split exists), check the location against that
    country's real abbreviation/full-name tables. Otherwise, treat the
    entry itself as a full country/region name typed by the user (e.g. a
    wizard-entered "Germany") and check it the same way full names are
    checked — no abbreviation guessing possible without curated data."""
    if not location or not target_countries:
        return False

    comma_segments = [e.strip().lower() for e in re.split(r"[;,]", location)]
    loose_segments = [e.strip().lower() for e in re.split(r"[;,/()-]|\bor\b", location, flags=re.IGNORECASE)]

    for country in target_countries:
        code = country.strip().lower()
        aliases = COUNTRY_LOCATION_ALIASES.get(code)
        if aliases:
            if any(seg in aliases["abbreviations"] | aliases["full_names"] for seg in comma_segments):
                return True
            if any(seg in aliases["full_names"] for seg in loose_segments):
                return True
        else:
            if code in comma_segments or code in loose_segments:
                return True
    return False


def _matches_target_regions(location: str, target_regions: list[str] | None) -> bool:
    """Province/state-level sibling of _matches_target_countries -- an optional, finer
    filter within whatever countries are already targeted (e.g. "Ontario and BC only",
    not all of Canada). Empty/unset target_regions means no region restriction at all
    (returns True), matching the "no filter" default every other optional lane/profile
    setting uses.

    Region names aren't scoped to a specific country's alias table here (unlike
    _matches_target_countries, which only checks a country's own abbreviations/full
    names) -- a user's target_regions list is usually short and self-evidently regional
    ("on", "bc", "texas"), so this checks the entered value against every curated
    country's abbreviation/full-name tables plus a plain substring fallback, same
    positive-match-only, fail-closed reasoning as the country check: an unrecognized or
    blank location is NOT a match, never "probably fine".

    Unlike _matches_target_countries, this applies to every source including Adzuna --
    Adzuna's own request-level scoping is by country only, never by province/state, so
    there's no equivalent "already correct by construction" exemption here."""
    if not target_regions:
        return True
    if not location:
        return False

    comma_segments = [e.strip().lower() for e in re.split(r"[;,]", location)]
    loose_segments = [e.strip().lower() for e in re.split(r"[;,/()-]|\bor\b", location, flags=re.IGNORECASE)]
    all_abbreviations = {a for aliases in COUNTRY_LOCATION_ALIASES.values() for a in aliases["abbreviations"]}
    all_full_names = {n for aliases in COUNTRY_LOCATION_ALIASES.values() for n in aliases["full_names"]}

    for region in target_regions:
        code = region.strip().lower()
        if not code:
            continue
        if code in all_abbreviations and any(seg == code for seg in comma_segments):
            return True
        if code in all_full_names and any(seg == code for seg in loose_segments):
            return True
        if code not in all_abbreviations and code not in all_full_names:
            if code in comma_segments or code in loose_segments:
                return True
    return False


def _is_recent(posted_at: str, now: datetime | None = None, max_age_days: int = RECENCY_MAX_AGE_DAYS) -> bool:
    """Missing or unparseable posted_at is treated as recent (fail open) —
    unlike the Canada-location check, staleness is a quality heuristic, not
    a hard eligibility rule, so a data gap should never silently drop an
    otherwise-good posting. All three sources now populate real ISO 8601
    dates (see search.py's first_published/estimated_publish_date/created
    fixes) so this branch should be rare in practice.

    max_age_days defaults to RECENCY_MAX_AGE_DAYS but can be overridden per
    call — e.g. a manually-triggered run widening the window to catch
    postings an earlier scheduled run's 14-day cutoff would have missed."""
    if not posted_at:
        return True
    try:
        posted = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return now - posted <= timedelta(days=max_age_days)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r, lon1_r, lat2_r, lon2_r = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    d_lat = lat2_r - lat1_r
    d_lon = lon2_r - lon1_r
    a = math.sin(d_lat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _within_radius(posting: Posting, lane: Lane, applicant: Applicant | None) -> bool:
    """Only applies when the lane sets radius_km (currently just
    ops_supervisor — an in-person lane bound to a real commute distance,
    unlike it_tech which stays Canada-wide since remote work is genuinely
    wanted there). Missing posting coordinates are included rather than
    excluded — explicit user choice: Greenhouse never provides coordinates
    at all and Adzuna only sometimes does, so excluding on absence would
    silently drop real nearby postings over a data gap, which the user
    judged worse than occasionally letting an actually-far-away posting
    through. Missing applicant coordinates (lane misconfigured without a
    matching profile.yaml entry) fail open the same way rather than
    crashing the whole filter step."""
    if lane.radius_km is None:
        return True
    if posting.latitude is None or posting.longitude is None:
        return True
    if applicant is None or applicant.latitude is None or applicant.longitude is None:
        return True
    distance = _haversine_km(applicant.latitude, applicant.longitude, posting.latitude, posting.longitude)
    return distance <= lane.radius_km


def posting_fingerprint(source: str, company: str, title: str, location: str) -> str:
    """Normalized (source, company, title, location) key used as a fallback
    dedupe signal alongside posting_key. Confirmed live: Adzuna re-lists the
    same real job under a brand new ad id when it re-indexes, so posting_key
    (keyed on that id) alone lets an already-applied-to/dismissed/queued job
    right back in looking "new." Deliberately keeps `source` in the key —
    collapsing the same title+company+location across DIFFERENT sources is
    a separate, harder problem (different id schemes entirely, no shared
    ground truth that it's really the same posting) that this isn't meant
    to solve."""
    norm = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())
    return f"{norm(source)}|{norm(company)}|{norm(title)}|{norm(location)}"


def _match_terms(posting: Posting, lane: Lane) -> list[str]:
    """`keywords` are checked against the full title+description — real
    role-defining phrases like "shift lead" or "IT support" are specific
    enough that description-wide matching is safe. `industries` are
    checked against the TITLE ONLY, not the full description — confirmed
    live 2026-08-06: every single Faire posting's description repeats the
    same "About Us" boilerplate ("Independent retailers around the
    globe..."), so description-wide matching on a single generic word like
    "retail" false-positived on completely unrelated roles (a Senior
    Applied AI/ML Scientist posting, among others) purely because the
    company's business description happens to mention retail."""
    full_text = f"{posting.title} {posting.description_text}".lower()
    title_text = posting.title.lower()
    keyword_matches = [
        term for term in lane.keywords
        if word_boundary_match(term.lower(), full_text)
    ]
    industry_matches = [
        term for term in lane.industries
        if word_boundary_match(term.lower(), title_text)
    ]
    return keyword_matches + industry_matches


def _match_score(matched: list[str], lane: Lane) -> float:
    """0-1 relevance score from the same matched-terms signal run_pipeline.py
    already sorts queued matches by (see queue_matches's sort key) — required
    keywords count double since a required-keyword hit is a stronger signal
    than an incidental one. Denominator includes required_keywords' own
    length as extra weight slots so a lane whose entire keyword list is
    required doesn't get capped below 1.0 by double-counting."""
    total_terms = len(lane.keywords) + len(lane.industries)
    if total_terms == 0:
        return 0.0
    required = set(lane.required_keywords or [])
    weighted_total = total_terms + len(required)
    weighted_matched = sum(2.0 if term in required else 1.0 for term in matched)
    return min(weighted_matched / weighted_total, 1.0)


def _exceeds_seniority(posting: Posting, lane: Lane) -> bool:
    cap = lane.seniority_max
    if not cap or cap not in _SENIORITY_RANK:
        return False
    return _title_seniority_rank(posting.title.lower()) > _SENIORITY_RANK[cap]


def _exceeds_years_experience(posting: Posting, lane: Lane) -> bool:
    if lane.max_years_experience is None:
        return False
    required = extract_required_years(f"{posting.title} {posting.description_text}")
    return required is not None and required > lane.max_years_experience


def _matches_remote_type(posting: Posting, lane: Lane) -> bool:
    """Empty lane.remote_types means no filter. Fails open when the posting
    itself doesn't carry a remote_type — most postings from most sources
    don't (see Posting.remote_type's own docstring) — only excludes when
    the posting positively states an arrangement the lane didn't ask for."""
    if not lane.remote_types:
        return True
    if not posting.remote_type:
        return True
    return posting.remote_type in lane.remote_types


def _matches_employment_type(posting: Posting, lane: Lane) -> bool:
    if not lane.employment_types:
        return True
    if not posting.employment_type:
        return True
    return posting.employment_type in lane.employment_types


def _matches_salary(posting: Posting, lane: Lane) -> bool:
    """Empty lane bounds (both None) means no filter. Fails open when the
    posting has no salary data at all. When only one side of either range
    is known, compares what's available rather than requiring both."""
    if lane.salary_min is None and lane.salary_max is None:
        return True
    if posting.salary_min is None and posting.salary_max is None:
        return True
    posting_min = posting.salary_min if posting.salary_min is not None else posting.salary_max
    posting_max = posting.salary_max if posting.salary_max is not None else posting.salary_min
    if lane.salary_max is not None and posting_min > lane.salary_max:
        return False
    if lane.salary_min is not None and posting_max < lane.salary_min:
        return False
    return True


def filter_postings(
    postings: list[Posting],
    lane: Lane,
    existing_keys: set[str],
    applicant: Applicant | None = None,
    target_countries: list[str] | None = None,
    existing_fingerprints: set[str] | None = None,
    max_age_days: int = RECENCY_MAX_AGE_DAYS,
    target_regions: list[str] | None = None,
) -> list[tuple[Posting, list[str], float]]:
    """Returns (posting, matched_terms, match_score) tuples for postings that are new
    (not in existing_keys, and not matching existing_fingerprints if given
    — see posting_fingerprint's own docstring for why posting_key alone
    isn't enough), within the lane's seniority cap (title-based)
    and years-of-experience cap (description-based, if lane.max_years_experience
    is set), posted within the last RECENCY_MAX_AGE_DAYS, within the lane's radius_km of applicant
    (if set), matching the lane's remote_types/employment_types/salary
    bounds (if set — all fail open on missing posting data, see each
    _matches_* function), match at least one of the lane's
    keywords/industries (AND at least one of `required_keywords`
    specifically, if the lane sets it — see Lane's own docstring for why),
    and are located in one of `target_countries` (user directive: only
    apply to postings in the countries the profile actually targets,
    nowhere else — generalized from what used to be a hardcoded
    Canada-only rule, see _matches_target_countries/
    COUNTRY_LOCATION_ALIASES).

    Adzuna postings skip the location check — Adzuna's API is already
    scoped by country (profile.yaml's adzuna_country) at the request level,
    so it's already correct by construction; re-checking its own
    location-string format client-side risks a false exclusion if that
    format doesn't happen to match COUNTRY_LOCATION_ALIASES, dropping
    already-correct results for no reason. Greenhouse and hiring.cafe have
    no such guarantee, so they do go through the check.

    `applicant` is only needed for lanes with radius_km set — omitted (the
    default) simply skips that check for lanes that don't use it.
    `target_countries` defaults to `["ca"]` if omitted, matching
    `Profile.target_countries`'s own default for backward compatibility.
    `max_age_days` defaults to RECENCY_MAX_AGE_DAYS — overridable per call
    (see run_pipeline.py's manual-run lane/days override). `target_regions`
    is an optional finer filter within target_countries (see
    _matches_target_regions) -- unlike target_countries, it applies to
    every source, Adzuna included, since Adzuna's own request-level scoping
    is by country only."""
    target_countries = target_countries or ["ca"]
    results = []
    for posting in postings:
        if posting.dedupe_key() in existing_keys:
            continue
        if existing_fingerprints is not None:
            fp = posting_fingerprint(posting.source, posting.company, posting.title, posting.location)
            if fp in existing_fingerprints:
                continue
        if posting.source != "adzuna" and not _matches_target_countries(posting.location, target_countries):
            continue
        if not _matches_target_regions(posting.location, target_regions):
            continue
        if not _is_recent(posting.posted_at, max_age_days=max_age_days):
            continue
        if not _within_radius(posting, lane, applicant):
            continue
        if _exceeds_seniority(posting, lane):
            continue
        if _exceeds_years_experience(posting, lane):
            continue
        if not _matches_remote_type(posting, lane):
            continue
        if not _matches_employment_type(posting, lane):
            continue
        if not _matches_salary(posting, lane):
            continue
        matched = _match_terms(posting, lane)
        if not matched:
            continue
        if lane.required_keywords and not any(term in matched for term in lane.required_keywords):
            continue
        score = _match_score(matched, lane)
        if lane.min_match_score is not None and score < lane.min_match_score:
            continue
        results.append((posting, matched, score))
    return results
