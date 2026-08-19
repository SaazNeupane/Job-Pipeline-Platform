"""Generates a short "why this fits your background" explanation for a queued posting --
the deeper-than-keywords match reasoning a "quality over quantity" positioning needs (see
Posting.fit_reason's own docstring in app/models.py). filter.py's matched_terms is real
signal but it's still keyword overlap, not "why" — this is the first place that actually
explains the fit in a sentence a human would say.

On-demand, not eager: same lazy-generation philosophy as resume/cover-letter (see
swipe_actions.queue_for_swipe's own docstring) -- a posting the user never looks twice at
shouldn't burn an LLM call. Cached in Posting.fit_reason once generated (see
app/routers/swipe.py's explain_match route), so re-viewing the same posting is free.

Same guardrail as cover_letter.py: the model only ever sees facts pulled from the actual
resume and the actual posting, with an explicit instruction never to invent anything beyond
them."""

from __future__ import annotations

from pipeline.config import load_secrets
from pipeline.writing_style import DEFAULT_MODEL_FALLBACKS, STYLE_RULES, generate_with_gemini

MODEL_FALLBACKS = DEFAULT_MODEL_FALLBACKS
MAX_DESCRIPTION_CHARS = 1500

SYSTEM_PROMPT = f"""\
You explain, in plain language, why a specific job posting is or isn't a good fit for a \
real applicant's background. You are given (1) real facts about the applicant, pulled from \
their actual resume, and (2) a real job posting with the keyword terms it already matched. \
Write 1-2 sentences a knowledgeable friend would say, pointing at SPECIFIC overlap between \
the applicant's actual experience and this specific posting -- not a generic restatement of \
the matched keywords.

Hard rules:
{STYLE_RULES}
- Length: 1-2 sentences, under 50 words total.
- Output plain text only -- no markdown, no bracketed placeholders, no preamble.
- Reference at least one concrete detail from the applicant's actual experience (a specific \
role, technology, or accomplishment) and at least one concrete detail from the posting \
(the role, a responsibility, a requirement) -- never a vague "this aligns well with your \
background" with nothing specific attached.
- If the overlap is genuinely thin, say so plainly instead of overselling it -- this is a \
gut-check for the user before they decide to apply, not a sales pitch.
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
APPLICANT FACTS (use only these -- do not add to them):
{_resume_facts_block(resume)}

JOB POSTING:
Company: {posting.company}
Title: {posting.title}
Terms this posting already matched via keyword search: {', '.join(matched_terms) or '(none)'}

Posting description:
{description}

Explain the fit now."""


def generate_fit_reason(user: str, resume: dict, posting, matched_terms: list[str]) -> str:
    secrets = load_secrets(user)
    api_key = secrets.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(f"Missing GEMINI_API_KEY in profiles/{user}/secrets.env")

    # Visible output target is tiny (under 50 words) but Gemini's internal "thinking" eats a
    # real, variable chunk of the same budget regardless of output length (seen live:
    # 1100-1250 tokens on similarly short calls elsewhere in this codebase, see
    # writing_style.generate_with_gemini's own docstring) -- matches cold_email.py's budget
    # for its similarly short-output call, not a token count sized to the visible text alone.
    return generate_with_gemini(
        api_key, MODEL_FALLBACKS, SYSTEM_PROMPT, _build_user_message(resume, posting, matched_terms),
        max_output_tokens=2048,
    )
