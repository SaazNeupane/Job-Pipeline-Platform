"""Generate a per-posting cover letter (spec Section 4, step 3/4 + Section 6a).

This is the first place in the pipeline that actually calls an LLM — plain
reordering/rephrasing (tailor_resume.py) can't produce a letter that
"references one or two concrete details from the actual posting" in natural
prose, and the spec's Section 6a style guide only makes sense with generation
in the loop.

Guardrail: the model is only ever shown facts pulled from the tailored resume
JSON and the posting text, with an explicit instruction never to add
anything beyond them. There's no per-letter automated fact-checker (Section
6/6a give the model concrete instructions to follow, and build step 12 has
you review real output end-to-end before the pipeline runs unattended) — but
nothing here invents inputs of its own.

Provider: Google Gemini (free tier, Flash model) — no ongoing cost, no
credit card, and deliberately not linked to a billing-enabled GCP project
(that would forfeit the free tier). Switched from Anthropic after two dry
runs burned through paid API credits generating letters nobody ever sent —
see get_cover_letter()'s dry-run/caching guardrails against that happening
again regardless of provider.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.config import load_secrets
from pipeline.json_cache import read_json_file, write_json_file
from pipeline.writing_style import DEFAULT_MODEL_FALLBACKS, STYLE_RULES, generate_with_gemini

MODEL_FALLBACKS = DEFAULT_MODEL_FALLBACKS  # see writing_style.py's note on model choice + fallback order
MAX_DESCRIPTION_CHARS = 2000

DRY_RUN_PLACEHOLDER = "[DRY RUN — cover letter not generated, to avoid real API calls for a run that never submits anything.]"
CACHE_PATH = Path("output/cover_letter_cache.json")

SYSTEM_PROMPT = f"""\
You write short, genuinely human-sounding cover letters for a real job \
applicant. You are given (1) real facts about the applicant, pulled from \
their actual resume, and (2) a real job posting. Write a cover letter for \
that posting using only the facts you're given.

Hard rules:
{STYLE_RULES}
- Length: roughly 200-300 words.
- Output plain text only — no markdown, no bracketed placeholders, no \
preamble or explanation. Just the letter, ready to send, ending with a \
sign-off and the applicant's name.
"""


def _resume_facts_block(resume: dict) -> str:
    lines = [f"Name: {resume['name']}"]

    lines.append("\nRelevant experience:")
    for entry in resume["experience"]["relevant"]:
        lines.append(f"- {entry['title']} at {entry['company']} ({entry['dates']})")
        for bullet in entry["bullets"]:
            lines.append(f"  * {bullet}")

    lines.append("\nSkills:")
    for category, items in resume["skills"].items():
        lines.append(f"- {category.replace('_', ' ').title()}: {', '.join(items)}")

    return "\n".join(lines)


def _build_user_message(resume: dict, posting, matched_terms: list[str]) -> str:
    description = posting.description_text[:MAX_DESCRIPTION_CHARS]
    return f"""\
APPLICANT FACTS (use only these — do not add to them):
{_resume_facts_block(resume)}

JOB POSTING:
Company: {posting.company}
Title: {posting.title}
Location: {posting.location}
Terms this posting matched from the applicant's target keywords: {', '.join(matched_terms)}

Posting description:
{description}

Write the cover letter now."""


def generate_cover_letter(user: str, resume: dict, posting, matched_terms: list[str]) -> str:
    secrets = load_secrets(user)
    api_key = secrets.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(f"Missing GEMINI_API_KEY in profiles/{user}/secrets.env")

    return generate_with_gemini(
        api_key, MODEL_FALLBACKS, SYSTEM_PROMPT, _build_user_message(resume, posting, matched_terms),
        max_output_tokens=3072,
    )


def _load_cache(cache_path: Path) -> dict[str, str]:
    return read_json_file(cache_path, {})


def _save_cache(cache_path: Path, cache: dict[str, str]) -> None:
    write_json_file(cache_path, cache)


def get_cover_letter(
    user: str, resume: dict, posting, matched_terms: list[str],
    dry_run: bool = True, cache_path: Path = CACHE_PATH,
) -> str:
    """Dry runs never touch the real API — there's nothing to submit, so a
    real generation call would just burn quota for text nobody sends (this
    is exactly what happened live before this module ran on Gemini: two dry
    runs in a row exhausted the Anthropic account generating letters for
    postings held for review, not actually applied to).

    Real (non-dry-run) generation is cached locally by dedupe_key(), so
    re-running against the same posting — e.g. a posting still sitting in
    pending_approval on a later day's run — reuses the letter already
    generated for it instead of paying for a new one."""
    if dry_run:
        return DRY_RUN_PLACEHOLDER

    cache = _load_cache(cache_path)
    key = posting.dedupe_key()
    if key in cache:
        return cache[key]

    text = generate_cover_letter(user, resume, posting, matched_terms)
    cache[key] = text
    _save_cache(cache_path, cache)
    return text
