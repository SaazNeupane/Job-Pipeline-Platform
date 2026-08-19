"""Reorder/rephrase the lane's structured resume JSON to match a posting,
optionally reword relevant-experience bullets via an LLM, then render a
one-page PDF (spec Section 4, step 3).

Reordering/synonym-swapping is deterministic — no LLM involved:
  - Bullets/skills/entries are stable-reordered to bring posting-matched
    terms to the front, within the relevant/additional structure already
    decided per lane (build step 2) — additional experience never jumps
    above relevant experience just because it happens to match.
  - Terminology swaps only happen within a lane's own `synonym_groups`
    (hand-curated, not the raw keywords list) — e.g. ops_supervisor treats
    "shift lead"/"supervisor"/"assistant manager"/"team lead" as
    interchangeable wording for the same real role. IT's keyword list is
    mostly distinct skill areas (QA vs backend), not synonyms, so most of
    it is deliberately excluded from swapping to avoid misrepresenting facts.
  - Swaps touch bullet/skill text and (as of 2026-08-06, explicit user
    request) the job TITLE of "relevant" experience entries — but ONLY via
    the same hand-curated `synonym_groups`, e.g. ops_supervisor's real
    title "Supervisor / Shift Manager" can display as "Shift Lead / Shift
    Manager" for a posting that matched "shift lead" — never a free-form
    relabel, never a title the person didn't actually hold. `company`,
    `dates`, `location`, and ALL of "additional" experience (title
    included) are still never touched — additional stays factual, same
    reasoning as why it never outranks relevant experience in reordering.

Reordering additionally considers the posting's own title/description text
(`_posting_specific_terms`), not just the lane's fixed keyword list — two
postings in the same lane can want very different real skills already on
the resume (e.g. "Django" vs "React"), and the lane's generic keyword list
alone can't tell those apart. This only ever surfaces skills/tools already
listed on the resume; it never invents anything.

A one-line `headline` (e.g. "Backend Engineer | Python, Django, REST APIs")
is added under the name, built from the posting's own title plus matched
skill terms — a real, standard resume convention (stating the target role),
not a claim about past employment.

`reword_bullets_with_llm()` (added 2026-08-06, explicit user request,
reversing the original "deterministic only" call for this one piece) uses
Gemini to reword "relevant experience" bullets toward a specific posting's
own language — same guardrails as cover_letter.py: never invent a fact/
number not already in the bullet, dry runs skip the real API call, real
generations are cached by posting.dedupe_key(). Deliberately scoped to
"relevant" experience only — "additional" experience is intentionally
lower-priority/supplementary, and rewording it toward an unrelated
posting's language would risk misrepresenting it, the same reasoning that
already keeps it from ever outranking relevant experience in reordering.

The same call also blends each relevant entry's job TITLE with the
posting's language, for lanes with `relabel_titles_to_posting=True`
(2026-08-08, explicit user reversal of the earlier verbatim-copy version —
a byte-for-byte match to the posting's own title read as fake/overclaiming
rather than a real "vibe match"). One combined Gemini call handles both
bullets and title per posting rather than two separate calls — this
project's free-tier Gemini quota has been as low as 20 requests/day on
some models, so halving call count here matters.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Callable

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table

from pipeline.config import load_secrets
from pipeline.json_cache import read_json_file, write_json_file
from pipeline.text_match import word_boundary_match, word_boundary_pattern
from pipeline.writing_style import DEFAULT_MODEL_FALLBACKS, generate_with_gemini

# ---------------------------------------------------------------------------
# Tailoring (reorder + rephrase)
# ---------------------------------------------------------------------------

MAX_HEADLINE_TERMS = 5

# Generic seniority modifiers, not domain-relevance signals — same
# distinction filter.py's Lane.required_keywords already makes for
# inclusion matching. Excluded specifically from ENTRY-level (job
# title+bullets) reordering, not bullet-level reordering within an entry:
# real bug found live 2026-08-06, a posting titled "Junior IT Helpdesk
# Technician" put "junior" in reorder_terms, which then matched the totally
# unrelated "Junior Graphics Designer" (2018-2019, a graphic-design role)
# purely because of that shared word in its job TITLE — sorting it to the
# front of "additional experience" ahead of far more substantial, recent
# work (a real shift-supervisor role), and since render_resume_pdf's
# content-level ladder keeps only the first N additional entries when
# space is tight, the wrong entry could end up the ONLY one shown. Bullet-
# level reordering keeps these terms — a bullet that legitimately mentions
# "entry-level" work is real, specific content, not a title-word collision.
_SENIORITY_MODIFIER_TERMS = {"entry level", "junior"}


def _matches_any(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(word_boundary_match(term.lower(), lowered) for term in terms)


def _rephrase_text(text: str, matched_terms: list[str], synonym_groups: list[list[str]], title_case: bool = False) -> str:
    """`title_case=True` (used only for job-title relabeling — see
    tailor_resume()) capitalizes every word of the replacement, e.g.
    "shift lead" -> "Shift Lead", matching real job-title conventions.
    The default (used for bullets/skills, ordinary sentence text) only
    capitalizes the replacement's first letter when the matched text
    itself started uppercase — "Shift Lead" in title case would look wrong
    dropped into the middle of a bullet."""
    matched_lower = {term.lower() for term in matched_terms}
    for group in synonym_groups:
        target = next((term for term in group if term.lower() in matched_lower), None)
        if target is None:
            continue
        for term in group:
            if term.lower() == target.lower():
                continue

            def _replace(m: re.Match, target: str = target) -> str:
                if title_case:
                    return target.title()
                return target[:1].upper() + target[1:] if m.group(0)[:1].isupper() else target

            text = re.sub(word_boundary_pattern(term), _replace, text, flags=re.IGNORECASE)
    return text


def _reorder(items: list[Any], matched_terms: list[str], text_fn: Callable[[Any], str]) -> list[Any]:
    """Stable sort bringing items that match a posting term to the front."""
    return sorted(items, key=lambda item: not _matches_any(text_fn(item), matched_terms))


def _posting_specific_terms(resume: dict, posting_text: str) -> list[str]:
    """Resume's own skill/tool names that also appear (word-boundary,
    case-insensitive) in the posting's own title+description text. This is
    what makes reordering vary per SPECIFIC posting rather than just per
    lane — never surfaces anything not already on the resume."""
    if not posting_text:
        return []
    haystack = posting_text.lower()
    seen: list[str] = []
    for items in resume.get("skills", {}).values():
        for term in items:
            if term not in seen and word_boundary_match(term.lower(), haystack):
                seen.append(term)
    return seen


def _build_headline(posting_title: str, terms: list[str]) -> str:
    """Plain "Target Role | skill, skill, skill" line — deliberately not a
    sentence, so there's no prose to sound AI-generated, and no dash/em-dash
    connector, just a pipe. Terms already contained in posting_title itself
    are dropped — real bug, found live: a term like "IT support" surviving
    into the term list for a posting titled "IT Support Analyst" produced
    "IT Support Analyst | IT support", which reads as the same title stated
    twice rather than the headline's real purpose (naming skills BEYOND the
    title itself)."""
    if not posting_title:
        return ""
    deduped: list[str] = []
    for term in terms:
        if term.lower() in {t.lower() for t in deduped}:
            continue
        if word_boundary_match(term.lower(), posting_title.lower()):
            continue
        deduped.append(term)
    top_terms = deduped[:MAX_HEADLINE_TERMS]
    if not top_terms:
        return posting_title
    return f"{posting_title} | {', '.join(top_terms)}"


def _resume_text(tailored: dict) -> str:
    """Flattens every place a required term could legitimately land — title,
    headline, all bullets (relevant + additional), skills — into one
    lowercased haystack for a single word-boundary presence check."""
    parts = [tailored.get("headline", "")]
    experience = tailored.get("experience", {})
    for bucket in ("relevant", "additional"):
        for entry in experience.get(bucket, []):
            parts.append(entry.get("title", ""))
            parts.extend(entry.get("bullets", []))
    for items in tailored.get("skills", {}).values():
        parts.extend(items)
    return " ".join(parts).lower()


def _flag_unmatched_keywords(tailored: dict, matched_terms: list[str]) -> None:
    """`_rephrase_text` above already guarantees a matched term lands
    verbatim wherever a lane.synonym_groups member for it exists anywhere on
    the resume — this only catches the remaining case: a term the posting
    wants that has no synonym-equivalent anywhere on the resume at all, so
    nothing could be substituted. Deliberately never invents content to
    close that gap (same "never invent" contract as reword_bullets_with_llm)
    — just surfaces it via content_flags so it's visible instead of silent."""
    haystack = _resume_text(tailored)
    missing = [t for t in matched_terms if not word_boundary_match(t.lower(), haystack)]
    if missing:
        tailored.setdefault("content_flags", []).append(
            "ATS keyword gap (no synonym on resume to substitute, left as-is): " + ", ".join(missing)
        )


def tailor_resume(
    resume: dict, lane, matched_terms: list[str], posting_title: str = "", posting_text: str = ""
) -> dict:
    tailored = copy.deepcopy(resume)

    reorder_terms = matched_terms + _posting_specific_terms(resume, f"{posting_title} {posting_text}")
    entry_reorder_terms = [t for t in reorder_terms if t.lower() not in _SENIORITY_MODIFIER_TERMS]

    experience = tailored.get("experience", {})
    for bucket in ("relevant", "additional"):
        entries = experience.get(bucket, [])
        for entry in entries:
            rephrased = [_rephrase_text(b, matched_terms, lane.synonym_groups) for b in entry["bullets"]]
            entry["bullets"] = _reorder(rephrased, reorder_terms, text_fn=lambda b: b)
            if bucket == "relevant":
                # Job TITLE relabeling — explicit user request. Two
                # mechanisms depending on the lane, both scoped to
                # "relevant" only (see Lane.relabel_titles_to_posting's own
                # docstring for why "additional" never gets touched):
                # - relabel_titles_to_posting=True: display the posting's
                #   OWN title verbatim — for lanes whose real titles have
                #   no natural synonym coverage (it_tech).
                # - otherwise: word-substitution within lane.synonym_groups
                #   (ops_supervisor's "Supervisor" <-> "Shift Lead" family)
                #   — narrower, but a closer paraphrase of the real title
                #   where that coverage already exists.
                # relabel_titles_to_posting no longer copies the posting's
                # title verbatim (2026-08-08, explicit user reversal: an
                # exact word-for-word match read as fake/overclaiming). It's
                # now a signal to reword_bullets_with_llm to BLEND the real
                # title with the posting's language instead -- see that
                # function. Left as the real title here, unchanged, which
                # is also the safe fallback if the LLM blend is skipped
                # (dry run) or fails validation.
                if not lane.relabel_titles_to_posting:
                    entry["title"] = _rephrase_text(entry["title"], matched_terms, lane.synonym_groups, title_case=True)
        experience[bucket] = _reorder(
            entries, entry_reorder_terms, text_fn=lambda e: e["title"] + " " + " ".join(e["bullets"])
        )

    skills = tailored.get("skills", {})
    for category, items in list(skills.items()):
        rephrased = [_rephrase_text(i, matched_terms, lane.synonym_groups) for i in items]
        skills[category] = _reorder(rephrased, reorder_terms, text_fn=lambda i: i)

    # Reorder which CATEGORY appears first too, not just items within one —
    # a posting asking for security/testing work should show a "Security"
    # or "Practices" category before "Databases"/"Data Tools", using
    # whatever's genuinely already on the resume. Still zero invention:
    # this only ever reorders real, already-listed skills, never adds one.
    if skills:
        ordered_categories = _reorder(
            list(skills.items()), reorder_terms, text_fn=lambda pair: pair[0] + " " + " ".join(pair[1]),
        )
        tailored["skills"] = dict(ordered_categories)

    tailored["headline"] = _build_headline(posting_title, reorder_terms)
    _flag_unmatched_keywords(tailored, matched_terms)

    return tailored


# ---------------------------------------------------------------------------
# LLM-based bullet rewording (relevant experience only — see module docstring)
# ---------------------------------------------------------------------------

BULLET_REWORD_MODEL_FALLBACKS = DEFAULT_MODEL_FALLBACKS  # see writing_style.py's note on model choice + fallback order
BULLET_REWORD_CACHE_PATH = Path("output/bullet_reword_cache.json")
MAX_BULLET_REWORD_DESCRIPTION_CHARS = 2000

BULLET_REWORD_STYLE_RULES = """\
- You may restructure a bullet's phrasing, emphasis, and word order to \
speak directly to a specific requirement stated in the posting — this \
goes beyond light wording tweaks. But the absolute limit: every fact, \
number, tool, or technology in your output must ALREADY be present in \
that same original bullet. Restructure and re-emphasize; never add.
- You MAY frame real backend/infrastructure/technical work using general \
IT-operations language when the bullet's own content genuinely involves \
that kind of work — e.g. "Constructed backend systems using Django to \
handle 10,000 requests per second" may honestly be framed as improving \
"system reliability and performance"; implementing two-factor \
authentication and encryption may honestly be framed as strengthening \
"IT security". This is honest reframing of real engineering work, not \
fabrication.
- Do NOT claim a specific duty or task type the bullet's own content \
never actually involved — that's a categorically different kind of work, \
not just different wording. A real example of what NOT to do: a bullet \
about general cross-functional collaboration on feature delivery, \
reworded to say "managed helpdesk-related requirements" for a \
helpdesk-flavored posting — the original bullet said nothing about \
helpdesk work, so that phrase must never appear in it. The same applies \
to any other hands-on duty claim (e.g. "ticket resolution", "desktop \
support", "end-user support") the original bullet doesn't actually \
describe. If a posting requirement has no real match in a given bullet, \
leave that bullet's content alone rather than forcing a connection.
- Every number/metric in the original must appear unchanged in the \
reworded version.
- Do NOT describe the work as being for a specific industry, product \
domain, or business vertical (e.g. "financial product", "healthcare \
system", "e-commerce platform") unless the original bullet already named \
that domain. A real example of what NOT to do: a bullet about general \
cross-functional ownership at an unrelated startup, reworded to say it \
delivered "integrated financial product features" because the posting \
happens to be for a fintech company — the entry's real employer had \
nothing to do with finance, so that framing must never appear. Job \
entries at different real companies can have completely different \
industries than the posting you're tailoring for; never borrow the \
posting's own industry onto a different, unrelated real job.
- Keep the resume-bullet register: action-verb-led fragments, not full \
sentences or flowing prose — restructuring is about emphasis and framing, \
not turning a bullet into a paragraph.
- No em-dashes. No stock phrases ("proven track record", "dynamic \
environment", "leverage", "results-driven", "spearheaded" unless the \
original already used it).
"""

TITLE_BLEND_STYLE_RULES = """\
- For each entry, also write a blended job title: a real "in between" of \
the candidate's actual title and the posting's own title/language — NOT \
a word-for-word copy of the posting's title (that reads as fabricated), \
and not just their unchanged original title either (that's what a plain \
title-case wording swap already handles elsewhere). Base the blend on \
the entry's real bullets, not just the two titles in isolation.
- Never introduce a seniority or authority word (Senior, Lead, Principal, \
Staff, Manager, Director, Head, Chief, Supervisor, VP, etc.) that isn't \
already in the candidate's real original title for that entry — a \
blended title must never imply the person held more seniority or \
authority than they actually did.
- Never introduce a job function/duty the entry's real bullets don't \
support. A real example of what NOT to do: turning "Full Stack Engineer" \
into "Senior IT Manager" for an unrelated posting — neither "Senior" nor \
"Manager" reflects anything in the real title or bullets, and \
"IT Manager" claims a management duty that was never held. A reasonable \
blend for that same case, if the bullets show relevant backend/ops work, \
would be something like "IT Support Engineer" — plausible, honest, and \
not a literal copy of either title.
- No em-dashes.
"""

BULLET_REWORD_SYSTEM_PROMPT = f"""\
You rewrite real resume bullet points so they directly address the \
specific requirements listed in a job posting, using only the facts \
already present in each bullet — restructuring and re-emphasizing real \
content, never inventing new content. You are given resume bullets \
grouped by job entry, and a real job posting.

Hard rules for bullets:
{BULLET_REWORD_STYLE_RULES}

Hard rules for the per-entry title you also produce:
{TITLE_BLEND_STYLE_RULES}
- Output strict JSON only: an object whose keys are the entry indices given \
to you (as strings) and whose values are objects with a "title" string \
and a "bullets" array (reworded bullets, same order and same count as \
given for that entry). No markdown, no commentary, no code fences.
"""


def _build_bullet_reword_message(entries: list[dict], posting) -> str:
    lines = ["RESUME ENTRIES TO REWORD (grouped by job entry):"]
    for i, entry in enumerate(entries):
        lines.append(f'\nEntry {i} — real title: "{entry["title"]}" at {entry["company"]}')
        for j, bullet in enumerate(entry["bullets"]):
            lines.append(f"{j}: {bullet}")

    description = posting.description_text[:MAX_BULLET_REWORD_DESCRIPTION_CHARS]
    lines.append(f"""

JOB POSTING:
Company: {posting.company}
Title: {posting.title}

Posting description:
{description}

Return the JSON now.""")
    return "\n".join(lines)


def _reworded_shape_matches_entries(parsed: Any, entries: list[dict]) -> bool:
    """True if `parsed` has the right {{entry_index: {{"title", "bullets"}}}}
    shape AND each entry's bullet COUNT still matches `entries`. Used for
    both a fresh model response and a cached one — a cache entry can go
    stale the same way a bad model response can (real bug found live
    2026-08-08: editing resume_it.json to add more bullets per entry left a
    cached reword response with the OLD bullet count, which crashed with an
    IndexError instead of falling back, because only fresh generations were
    shape-checked before this fix — a cache hit was trusted blindly)."""
    if not isinstance(parsed, dict) or len(parsed) != len(entries):
        return False
    for i, entry in enumerate(entries):
        result = parsed.get(str(i))
        if not isinstance(result, dict):
            return False
        bullets = result.get("bullets")
        if not isinstance(bullets, list) or len(bullets) != len(entry["bullets"]):
            return False
    return True


def _reword_bullets(api_key: str, entries: list[dict], posting) -> dict[str, dict] | None:
    """Returns the parsed {{entry_index: {{"title": ..., "bullets": [...]}}}}
    mapping, or None if the model's output doesn't validate (wrong shape,
    wrong bullet counts) — callers must fall back to the original bullets/
    title rather than apply a malformed result, same fail-safe principle as
    everywhere else in this project (e.g. apply.py never guesses an
    unanswerable form field)."""
    message = _build_bullet_reword_message(entries, posting)
    raw = generate_with_gemini(
        api_key, BULLET_REWORD_MODEL_FALLBACKS, BULLET_REWORD_SYSTEM_PROMPT, message, max_output_tokens=4096,
    )
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    if not _reworded_shape_matches_entries(parsed, entries):
        return None
    return parsed


def _load_bullet_cache(cache_path: Path) -> dict:
    return read_json_file(cache_path, {})


def _save_bullet_cache(cache_path: Path, cache: dict) -> None:
    write_json_file(cache_path, cache)


# Generic IT-operations/reliability framing — even when one of these comes
# from the posting's own matched language (and so would otherwise be
# treated as "new" by the check below), introducing it describes a real
# QUALITY/OUTCOME of engineering work (e.g. "improved system reliability")
# rather than claiming a distinct job function that was never performed.
# Explicit user decision (2026-08-07), after a title relabeled to "IT
# Helpdesk Analyst" sat atop 100%-unchanged backend-engineering bullets —
# none of the real content could honestly bridge to helpdesk language
# under the old all-headline-terms check, so title and bullets read as
# incoherent. Deliberately NOT in this list — stays hard-blocked exactly
# as before: "helpdesk", "ticket", "desktop support", "end-user support",
# or any other term that claims a specific hands-on duty type rather than
# describing an outcome of real engineering work.
_SAFE_BRIDGE_TERMS = {
    "reliability", "system reliability", "infrastructure", "it infrastructure",
    "technical support", "it support", "system stability", "stability",
    "security", "it security", "troubleshooting", "technical troubleshooting",
    "it operations", "operations", "system performance", "performance",
    "uptime", "internal systems", "system maintenance", "maintenance",
}

# Industry/business-vertical descriptors — checked unconditionally (not
# derived from a specific posting) alongside the headline-derived sensitive
# terms. Real bug caught live 2026-08-08: rewording a Pi Tech (a general
# tech startup, no financial-industry work at all) bullet for a Robinhood
# posting produced "deliver integrated financial product features" —
# "financial" was never in the matched-keyword headline (it's an industry
# word inferred from the posting's company context, not a skill/keyword
# match), so the existing sensitive-terms check, scoped only to headline
# terms, couldn't catch it. Same failure class as the original "helpdesk"
# bug, different source. A job entry at one real company can be in a
# completely different industry than the posting being tailored for.
_INDUSTRY_DOMAIN_TERMS = [
    "financial", "finance", "fintech", "banking", "healthcare", "medical",
    "e-commerce", "ecommerce", "retail", "insurance", "government",
    "education", "real estate", "logistics", "manufacturing", "gaming",
    "hospitality", "telecom", "telecommunications", "automotive",
    "pharmaceutical", "biotech", "legal", "nonprofit",
]


def _bullet_introduces_new_sensitive_term(original: str, reworded: str, sensitive_terms: list[str]) -> bool:
    """True if `reworded` contains one of `sensitive_terms` (word-boundary,
    case-insensitive) that wasn't already present in `original`. Real bug
    caught live 2026-08-06: told (in the prompt) not to invent anything,
    the model still rewrote "Collaborated with cross-functional teams to
    gather requirements..." (a Syyar Tech/full-stack bullet, no helpdesk
    work involved at all) into "...manage helpdesk-related requirements..."
    — pulling "helpdesk" in from the posting's own matched terms because
    that's what it was told to echo, stretching a real bullet to imply
    something the original never said. An instruction not to invent things
    isn't a guardrail on its own — this is the actual check."""
    original_lower = original.lower()
    reworded_lower = reworded.lower()
    for term in sensitive_terms:
        term = term.strip()
        if not term:
            continue
        pattern = word_boundary_pattern(term.lower())
        if re.search(pattern, reworded_lower) and not re.search(pattern, original_lower):
            return True
    return False


def _headline_terms(headline: str) -> list[str]:
    if "|" not in headline:
        return []
    return [t.strip() for t in headline.split("|", 1)[1].split(",") if t.strip()]


# Authority/seniority words a blended title must never introduce unless the
# person's own real title already had one — see _title_blend_claims_new_seniority.
_TITLE_SENIORITY_TERMS = {
    "senior", "sr", "lead", "principal", "staff", "manager", "director",
    "head", "chief", "vp", "vice president", "president", "executive", "supervisor",
}


def _title_blend_claims_new_seniority(original_title: str, blended_title: str) -> bool:
    """True if `blended_title` contains a seniority/authority word (word-
    boundary, case-insensitive) that `original_title` didn't already have —
    the title-blend analogue of _bullet_introduces_new_sensitive_term. A
    blend that borrows "IT Support Manager" from a posting when the real
    title was "IT Support Technician" would claim a management duty that
    was never held, not just different wording for the same real job."""
    original_lower = original_title.lower()
    blended_lower = blended_title.lower()
    for term in _TITLE_SENIORITY_TERMS:
        pattern = word_boundary_pattern(term)
        if re.search(pattern, blended_lower) and not re.search(pattern, original_lower):
            return True
    return False


def _valid_blended_title(title: Any, original_title: str) -> bool:
    return (
        isinstance(title, str) and bool(title.strip()) and len(title) <= 120 and "\n" not in title
        and not _title_blend_claims_new_seniority(original_title, title)
    )


def reword_bullets_with_llm(
    user: str, tailored: dict, posting, dry_run: bool = True,
    blend_titles: bool = False, cache_path: Path = BULLET_REWORD_CACHE_PATH,
) -> dict:
    """Rewords "relevant experience" bullets in place (also returns the same
    dict, for chaining) so they speak more directly to this specific
    posting's language, and — when `blend_titles` is True (lanes with
    `relabel_titles_to_posting`, see tailor_resume()) — also blends each
    entry's job title with the posting's language in the same call. Dry
    runs skip the real API call entirely and leave bullets/titles
    unchanged — same guardrail as get_cover_letter, same reason (avoid
    burning quota generating text for a run that never submits anything).
    Real generations are cached by dedupe_key(). A model response that
    fails validation, or a missing API key, leaves bullets/titles
    unchanged rather than risk applying something malformed — logged, not
    raised, since a resume that's merely un-reworded is never worse than
    the deterministic version already computed.

    A per-bullet content check runs on every result (cached or fresh, see
    _bullet_introduces_new_sensitive_term) — any single bullet that pulled
    in a posting-matched term (from the headline, already computed by
    tailor_resume) not present in its own original text is reverted to the
    original wording for just that bullet, not the whole response. Titles
    get the analogous check (_valid_blended_title) — a blend that claims
    new seniority, is empty, or is malformed reverts to the real original
    title. Both checks run on every result, cached or fresh — a bad result
    cached before either check existed gets caught and neutralized on
    every future load too, without needing cache invalidation."""
    entries = tailored.get("experience", {}).get("relevant", [])
    if not entries or dry_run:
        return tailored

    cache = _load_bullet_cache(cache_path)
    key = posting.dedupe_key()
    reworded = cache.get(key)
    if reworded is not None and not _reworded_shape_matches_entries(reworded, entries):
        # Stale cache entry — e.g. the resume's own bullet count changed
        # since this posting was last cached. Same as an invalid model
        # response: don't trust it, regenerate.
        print(f"[tailor_resume] reword_bullets_with_llm: cached entry for {key} no longer matches the resume's shape, regenerating")
        reworded = None
    if reworded is None:
        secrets = load_secrets(user)
        api_key = secrets.get("GEMINI_API_KEY")
        if not api_key:
            print("[tailor_resume] reword_bullets_with_llm: missing GEMINI_API_KEY, leaving bullets as-is")
            tailored.setdefault("content_flags", []).append("bullet reword skipped: missing GEMINI_API_KEY")
            return tailored

        reworded = _reword_bullets(api_key, entries, posting)
        if reworded is None:
            print(f"[tailor_resume] reword_bullets_with_llm: model output didn't validate for {key}, leaving bullets as-is")
            tailored.setdefault("content_flags", []).append("bullet reword skipped: model output failed validation")
            return tailored
        cache[key] = reworded
        _save_bullet_cache(cache_path, cache)

    sensitive_terms = [
        t for t in _headline_terms(tailored.get("headline", "")) if t.strip().lower() not in _SAFE_BRIDGE_TERMS
    ] + _INDUSTRY_DOMAIN_TERMS
    content_flags = tailored.setdefault("content_flags", [])
    for i, entry in enumerate(entries):
        result = reworded[str(i)]
        original_bullets = entry["bullets"]
        new_bullets = list(result["bullets"])
        for j, original in enumerate(original_bullets):
            if _bullet_introduces_new_sensitive_term(original, new_bullets[j], sensitive_terms):
                print(f"[tailor_resume] reword_bullets_with_llm: reverted a bullet that introduced an unsupported term for {key}")
                content_flags.append(f"bullet reverted in '{entry['title']}': reworded version introduced an unsupported term")
                new_bullets[j] = original
        entry["bullets"] = new_bullets

        if blend_titles:
            blended_title = result.get("title")
            if _valid_blended_title(blended_title, entry["title"]):
                entry["title"] = blended_title
            else:
                print(f"[tailor_resume] reword_bullets_with_llm: title blend for entry {i} failed validation, keeping real title for {key}")
                content_flags.append(f"title blend rejected for '{entry['title']}': failed validation, kept real title")

    return tailored


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------

_BASE_STYLES = getSampleStyleSheet()

# Tried largest-first: a short resume should use the page, not leave the
# bottom third blank at the smallest/default size — render_resume_pdf picks
# the LARGEST scale in this list that fits at a given content level (see
# _CONTENT_LEVELS), only stepping down when that content genuinely doesn't
# fit yet. Floor is 0.87 (~8.3pt body) deliberately — never shrunk further
# than that for legibility; a real resume with more content than fits at a
# readable size needs LESS content, not an illegibly small font (confirmed
# live 2026-08-06: even 0.6x scale/tight margins, ~5.7pt body, was needed
# to fit a real 5-job resume's full content on one page — nowhere near
# usable, so content trimming is the actual right lever past this floor).
_FONT_SCALE_STEPS = [1.15, 1.08, 1.0, 0.93, 0.87]

# Each level is (max_bullets_per_entry, max_additional_entries,
# drop_sections) — None means "no cap." Tried in order, least
# content-reduction first, each across the FULL font-scale range above
# before moving to a more aggressive level — preserving real content is
# prioritized over maximizing font size within the already-legible range.
#
# Real numbers behind this ladder, tested live against an actual 5-job,
# 2-project resume (2026-08-06): trimming bullet COUNT alone never freed
# enough space on its own (even capping every entry to 2 bullets, with
# additional experience AND interests already dropped, still didn't fit one
# page) — the real bottleneck is structural (a header/dates row + spacer per
# entry, not just bullets), so which SECTIONS and which historical entries
# appear at all is what actually closes the gap. "additional" experience
# (older/lower-priority roles) is dropped before PROJECTS, not after —
# explicit user decision (2026-08-18): projects are curated, deliberately
# chosen work; additional experience is whatever didn't make "relevant."
# Dropping PROJECTS entirely is the true last resort now.
_CONTENT_LEVELS: list[tuple[int | None, int | None, list[str]]] = [
    (None, None, []),
    (None, None, ["interests"]),
    (None, None, ["interests", "additional"]),
    (5, None, ["interests", "additional"]),
    (4, None, ["interests", "additional"]),
    (3, None, ["interests", "additional"]),
    (2, None, ["interests", "additional", "projects"]),
]


def _apply_content_level(resume: dict, max_bullets: int | None, max_additional_entries: int | None) -> dict:
    """Bullets kept are always the FIRST N in each entry's list — i.e. the
    ones tailor_resume()'s deterministic reorder already sorted to the
    front as the best matches for this posting, so trimming never discards
    the most relevant content in favor of something less relevant."""
    trimmed = copy.deepcopy(resume)
    for bucket in ("relevant", "additional"):
        for entry in trimmed.get("experience", {}).get(bucket, []):
            if max_bullets is not None:
                entry["bullets"] = entry["bullets"][:max_bullets]
    if max_additional_entries is not None:
        additional = trimmed.get("experience", {}).get("additional", [])
        trimmed["experience"]["additional"] = additional[:max_additional_entries]
    return trimmed


def _build_styles(scale: float) -> dict[str, ParagraphStyle]:
    return {
        "name": ParagraphStyle("Name", parent=_BASE_STYLES["Title"], fontSize=18 * scale, spaceAfter=2 * scale),
        "headline": ParagraphStyle(
            "Headline", parent=_BASE_STYLES["Normal"], fontSize=10.5 * scale,
            spaceAfter=4 * scale, textColor="#444444",
        ),
        "contact": ParagraphStyle("Contact", parent=_BASE_STYLES["Normal"], fontSize=9 * scale, spaceAfter=12 * scale),
        "section": ParagraphStyle(
            "Section", parent=_BASE_STYLES["Heading2"], fontSize=11 * scale,
            spaceBefore=10 * scale, spaceAfter=4 * scale, textColor="#222222",
        ),
        "role": ParagraphStyle("Role", parent=_BASE_STYLES["Normal"], fontSize=10 * scale, fontName="Helvetica-Bold"),
        "subtle": ParagraphStyle("Subtle", parent=_BASE_STYLES["Normal"], fontSize=10 * scale, alignment=2),
        "body": ParagraphStyle("Body", parent=_BASE_STYLES["Normal"], fontSize=9.5 * scale, leading=13 * scale),
        "bullet": ParagraphStyle(
            "Bullet", parent=_BASE_STYLES["Normal"], fontSize=9.5 * scale, leading=13 * scale, leftIndent=12,
        ),
        # ListFlowable's own bulletFontSize default is a fixed 12pt,
        # unrelated to (and never shrunk alongside) the body text size --
        # at any scale that draws the "circle" bullet glyph noticeably
        # larger than the text next to it. Tying it to the same scale
        # factor, at roughly half the body font size, keeps it a small dot.
        "bullet_size": 5 * scale,
        # ReportLab positions a ListItem's bullet glyph using its own
        # ascent, not aligned to the adjacent Paragraph's baseline — with
        # bullet_size this much smaller than the body text's leading, the
        # bullet draws visibly higher than the text next to it. -4.2165 per
        # unit scale is an exact, zero-residual constant (confirmed by
        # measuring real glyph bounding boxes in rendered PDFs at every one
        # of render_resume_pdf's actual _FONT_SCALE_STEPS — bullet and text
        # vertical centers matched to sub-0.01pt at all five, not just one).
        "bullet_offset_y": -4.2165 * scale,
        "spacer": 6 * scale,
    }


def _header_row(left: str, right: str, styles: dict, left_style_key: str = "role") -> Table:
    table = Table(
        [[Paragraph(left, styles[left_style_key]), Paragraph(right, styles["subtle"])]],
        colWidths=[4.5 * inch, 2.5 * inch],
    )
    table.setStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)])
    return table


def _bullet_list(bullets: list[str], styles: dict) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(b, styles["bullet"]), leftIndent=12) for b in bullets],
        bulletType="bullet", start="circle", leftIndent=12, bulletFontSize=styles["bullet_size"],
        bulletOffsetY=styles["bullet_offset_y"],
    )


def _entry_header_left(entry: dict) -> str:
    """"Title | Company" — a pipe, not an em dash, per explicit user
    request to keep generated resume formatting plain."""
    return f'{entry["title"]} | {entry["company"]}'


def _project_line(project: dict) -> str:
    return f'<b>{project["name"]}</b> | {project["description"]}'


def _build_story(resume: dict, styles: dict, drop_sections: list[str]) -> list:
    spacer = styles["spacer"]
    story = [Paragraph(resume["name"], styles["name"])]
    if resume.get("headline"):
        story.append(Paragraph(resume["headline"], styles["headline"]))
    story.append(Paragraph(
        f'{resume["contact"]["phone"]} | {resume["contact"]["email"]} | {resume["contact"]["website"]}',
        styles["contact"],
    ))

    education = resume.get("education")
    if education:
        story.append(Paragraph("EDUCATION", styles["section"]))
        for edu in education:
            story.append(_header_row(edu["institution"], edu["location"], styles))
            story.append(_header_row(f'{edu["credential"]} | GPA: {edu["gpa"]}', edu["dates"], styles, left_style_key="body"))
            if edu.get("highlights"):
                story.append(_bullet_list(edu["highlights"], styles))
            story.append(Spacer(1, spacer))

    relevant = resume["experience"]["relevant"]
    if relevant:
        story.append(Paragraph("RELEVANT EXPERIENCE" if resume["experience"].get("additional") else "EXPERIENCE", styles["section"]))
        for entry in relevant:
            story.append(_header_row(_entry_header_left(entry), entry["location"], styles))
            story.append(_header_row("", entry["dates"], styles, left_style_key="body"))
            story.append(_bullet_list(entry["bullets"], styles))
            story.append(Spacer(1, spacer))

    additional = resume["experience"].get("additional") if "additional" not in drop_sections else None
    if additional:
        story.append(Paragraph("ADDITIONAL EXPERIENCE", styles["section"]))
        for entry in additional:
            story.append(_header_row(_entry_header_left(entry), entry["location"], styles))
            story.append(_header_row("", entry["dates"], styles, left_style_key="body"))
            story.append(_bullet_list(entry["bullets"], styles))
            story.append(Spacer(1, spacer))

    projects = resume.get("projects") if "projects" not in drop_sections else None
    if projects:
        story.append(Paragraph("PROJECTS", styles["section"]))
        for project in projects:
            story.append(Paragraph(_project_line(project), styles["body"]))
            story.append(_bullet_list(project["bullets"], styles))
            story.append(Spacer(1, spacer))

    skills = resume.get("skills")
    if skills:
        story.append(Paragraph("SKILLS", styles["section"]))
        for category, items in skills.items():
            label = category.replace("_", " ").title()
            story.append(Paragraph(f"<b>{label}:</b> {', '.join(items)}", styles["body"]))

    interests = resume.get("interests") if "interests" not in drop_sections else None
    if interests:
        story.append(Paragraph("INTERESTS", styles["section"]))
        story.append(Paragraph(", ".join(interests), styles["body"]))

    return story


def _content_level_flag(max_bullets: int | None, max_additional_entries: int | None, drop_sections: list[str]) -> str | None:
    """Describes what a content level actually cut, or None for the
    full-content level (nothing to flag)."""
    parts = []
    if drop_sections:
        parts.append(f"dropped {', '.join(drop_sections)}")
    if max_bullets is not None:
        parts.append(f"capped to {max_bullets} bullets/entry")
    if max_additional_entries is not None:
        noun = "entry" if max_additional_entries == 1 else "entries"
        parts.append(f"kept only {max_additional_entries} additional-experience {noun}")
    if not parts:
        return None
    return "resume content trimmed to fit one page: " + "; ".join(parts)


def render_resume_pdf(resume: dict, output_path: Path) -> list[str]:
    """Tries each content level in _CONTENT_LEVELS in order (least content
    reduction first), and within each level picks the LARGEST font scale in
    _FONT_SCALE_STEPS that fits on one page — a short/lightly-trimmed
    resume uses the page instead of leaving it visibly sparse at a fixed
    default size, but never shrinks past a readable floor. Bullet wording
    itself is never touched here — every kept bullet is copied verbatim
    (rewording is reword_bullets_with_llm's job, a separate step upstream
    of this one); this function only decides font size and which
    entries/sections/bullets are INCLUDED.

    Returns content flags describing what was trimmed (empty list if the
    resume fit at full content) — callers should surface these alongside
    reword_bullets_with_llm's own flags rather than let a real content
    reduction go unnoticed until someone happens to read the PDF by hand."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    last_doc = None
    for max_bullets, max_additional_entries, drop_sections in _CONTENT_LEVELS:
        variant = _apply_content_level(resume, max_bullets, max_additional_entries)
        for scale in _FONT_SCALE_STEPS:
            doc = SimpleDocTemplate(
                str(output_path), pagesize=LETTER,
                topMargin=0.5 * inch, bottomMargin=0.5 * inch, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
            )
            styles = _build_styles(scale)
            story = _build_story(variant, styles, drop_sections)
            doc.build(story)
            last_doc = doc
            if doc.page <= 1:
                # Page-trim content_flags disabled per explicit user request
                # (2026-08-18) -- the message was noisy/unwanted in the
                # Dashboard/Swipe UI. Trimming itself still happens exactly
                # as before; only the user-visible flag is suppressed.
                # flag = _content_level_flag(max_bullets, max_additional_entries, drop_sections)
                # return [flag] if flag else []
                return []

    print(f"[tailor_resume] render_resume_pdf: could not fit one page even at the most-trimmed content level/smallest scale ({last_doc.page} pages) — left the most-trimmed render in place")
    # return [f"resume did not fit one page even at the most-trimmed content level ({last_doc.page} pages) — kept the most-trimmed render"]
    return []
