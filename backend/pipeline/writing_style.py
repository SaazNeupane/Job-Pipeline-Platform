"""Shared Section 6a writing-style guardrails for LLM-generated text.

Used by cover_letter.py, cold_email.py, and (as of 2026-08-06)
tailor_resume.py's reword_bullets_with_llm() — resume bullet phrasing was
originally deterministic-only (build step 6), reversed for that one piece
by explicit user request. tailor_resume.py uses its own dedicated style
rules (BULLET_REWORD_STYLE_RULES) rather than STYLE_RULES below — a resume
bullet's register (short, action-verb-led fragments) is different enough
from a cover letter's prose that reusing the same rules verbatim didn't fit.

Provider: Google Gemini (free tier) — switched from Anthropic after two dry
runs burned through paid API credits generating letters nobody ever sent
(see cover_letter.get_cover_letter's dry-run/caching guardrails against
that, which apply regardless of provider).

Model choice is deliberately a specific pinned model, not an alias — tried
both directions live and both failed differently:
  - Pinning too old: gemini-2.0-flash and gemini-2.0-flash-001 both return
    429 with `limit: 0` (not "used up" — zero free-tier quota allotted).
    Superseded models can get dropped from free-tier eligibility entirely.
  - Tracking "latest": gemini-flash-latest resolved to gemini-3.6-flash (the
    newest release at the time) — 20 requests/day, 5/minute. A brand-new
    flagship model gets a much smaller initial free-tier allowance, so
    "-latest" isn't actually the safe default it looks like; it can silently
    swap you onto whatever's most quota-constrained right now.
  - gemini-2.5-flash and gemini-2.5-flash-lite: 404 NOT_FOUND, "no longer
    available to new users" — pinned models eventually get retired too.
  - What worked: gemini-3.1-flash-lite. Lite-tier models are cheaper to
    serve and tend to get more generous free quotas; not the newest release
    either, so past the initial-rollout throttling window. This will
    presumably need revisiting again eventually as Google's lineup shifts —
    there's no permanent fix here, just "check what currently has both
    quota and isn't deprecated" when it breaks again.

Callers now pass an ORDERED LIST of models rather than a single pin (added
2026-08-11) — the three failures above (quota-zero, throttled-latest,
retired-model) were each a single point of failure that silently broke
every LLM call in the pipeline until someone happened to notice and
manually repin. generate_with_gemini tries each candidate in order and
only moves on when the error looks model-level (quota/not-found/invalid
model), so a working primary pin still resolves in one call as before —
this doesn't guess a permanently correct model, it just stops the next
break from being silent.
"""

import logging

from google import genai
from google.genai import errors, types

logger = logging.getLogger(__name__)

# Error codes that mean "this specific model is unusable right now" (zero
# quota, retired/not found, rejected model argument, or — 503, added
# 2026-08-12 after a real live failure — "This model is currently
# experiencing high demand," Gemini's own wording, confirmed model-
# specific rather than a general outage) as opposed to a transient network
# issue or a problem with the request itself that would fail identically
# on any model — only these are worth retrying on the next candidate. The
# 503 that prompted this: a real run's process_application errored out
# entirely on it (no fallback existed yet) and the posting was silently
# dropped for the day — never held, never submitted, just lost until the
# next run happened to re-find it.
_MODEL_LEVEL_ERROR_CODES = {400, 404, 429, 503}

# Single source of truth for all three call sites (cover_letter.py,
# cold_email.py, tailor_resume.py) — previously each held its own MODEL
# constant, which meant a future repin had to be made in three places and
# could silently drift out of sync. gemini-3.1-flash-lite is the primary
# pin, confirmed live. gemini-2.0-flash-lite (the original third fallback)
# was confirmed DEAD in a real live run 2026-08-14 — 404 "no longer
# available" — after the first two candidates both hit transient 503s in
# the same call, which is exactly the scenario this fallback list exists to
# survive; instead it hit a permanently retired last candidate and crashed
# the whole call (see cold_email._send_cold_emails' per-candidate try/except
# for the other half of that fix — a dead last-resort fallback shouldn't be
# able to take down an entire batch either). Replaced with
# gemini-2.5-flash-lite, confirmed present in a live models.list() call the
# same day. Re-verify whichever candidate actually ends up serving a
# request before trusting it the way the primary pin has been.
DEFAULT_MODEL_FALLBACKS = ["gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-2.5-flash-lite"]


def generate_with_gemini(
    api_key: str, models: str | list[str], system_prompt: str, user_message: str, max_output_tokens: int
) -> str:
    """Callers must pass a max_output_tokens with real headroom above the
    visible text they expect — Gemini's internal "thinking" consumes part of
    this same budget, and how much varies a lot per call (seen live: 1159
    and 1253 tokens of thinking on similar-sized prompts). Tried disabling
    it via thinking_config(thinking_budget=0) first; the current model
    rejected that (400 INVALID_ARGUMENT — some Gemini generations require a
    non-zero minimum), so headroom is the portable fix. require_complete()
    below is still the actual safety net if a budget ever isn't enough.

    `models` is tried in order; a model-level error (see
    _MODEL_LEVEL_ERROR_CODES) falls through to the next candidate instead of
    raising immediately. If every candidate fails, the last error is
    raised — this never silently returns nothing."""
    candidates = [models] if isinstance(models, str) else models
    client = genai.Client(api_key=api_key)

    last_error: Exception | None = None
    for i, model in enumerate(candidates):
        try:
            response = client.models.generate_content(
                model=model,
                contents=user_message,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=max_output_tokens,
                ),
            )
            if i > 0:
                logger.warning("Gemini fell back to model %r (candidates before it failed)", model)
            return require_complete(response.text.strip())
        except errors.APIError as exc:
            last_error = exc
            if exc.code not in _MODEL_LEVEL_ERROR_CODES or i == len(candidates) - 1:
                raise
            logger.warning("Gemini model %r failed (%s), trying next candidate", model, exc.code)

    # Unreachable if candidates is non-empty (loop above always returns or
    # raises), but keeps type-checkers happy and fails loudly if it isn't.
    raise last_error or RuntimeError("generate_with_gemini called with no model candidates")


def require_complete(text: str) -> str:
    """Raises if text looks cut off mid-sentence. Caught live: a tight
    max_tokens budget let thinking eat into the output budget and the note
    stopped mid-sentence while the API still reported a normal end_turn — a
    truncated note should never be sent as-is, and stop_reason alone doesn't
    guarantee that, so this checks the actual text.

    A valid ending isn't always terminal punctuation — these prompts always
    close with a sign-off name (e.g. "Saaz Neupane"), which has none. First
    version of this check didn't account for that and flagged a genuinely
    complete note as truncated. A short, capitalized, digit-free final line
    is treated as a valid sign-off; anything else needs real punctuation.

    Also accepts "}"/"]" — confirmed live 2026-08-06: tailor_resume.py's
    bullet-reword call generates strict JSON (no sign-off, no sentence
    punctuation at all), and a genuinely complete, valid JSON payload was
    being flagged as truncated for having neither. The caller (
    _reword_bullets) separately parses and shape-validates the JSON anyway,
    so accepting "}"/"]" here doesn't weaken the actual safety net — a
    truncated-mid-JSON string essentially never happens to end in a
    balanced closing brace AND fail that stricter downstream check too."""
    stripped = text.rstrip()
    if stripped.endswith((".", "!", "?", '"', "}", "]")):
        return text

    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    last_line = lines[-1] if lines else ""
    words = last_line.split()
    looks_like_signoff_name = (
        1 <= len(words) <= 4
        and not any(char.isdigit() for char in last_line)
        and last_line[:1].isupper()
    )
    if not looks_like_signoff_name:
        raise RuntimeError(f"Generated text looks truncated, refusing to use it: {text!r}")
    return text


STYLE_RULES = """\
- Never invent skills, tools, employers, titles, dates, numbers, or \
achievements that aren't in the provided facts. If you're not sure \
something is stated, leave it out rather than guess or generalize it in.
- Reference one or two concrete details from the actual posting or company \
text you were given — not generic enthusiasm.
- Vary sentence length and rhythm. Do not write in symmetrical three-clause \
sentences.
- Avoid stock phrases: "I am passionate about," "in today's fast-paced \
world," "leverage my skills," "proven track record," "dynamic environment," \
"I would be a great fit."
- Avoid em-dash overuse and rigid "firstly / secondly / finally" pacing.
- Each paragraph should add new ground. If two jobs would prove the same \
point, don't give both a full paragraph — cover the weaker one briefly or \
fold it into a sentence instead of repeating the same case twice.
- When connecting your background to the role, state the connection \
directly. Don't hedge it with phrases like "I imagine" or "I would guess."
- Tone: direct and slightly informal, not corporate-polished.\
"""
