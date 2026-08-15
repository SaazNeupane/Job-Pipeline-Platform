"""Word-boundary phrase matching, shared by filter.py and tailor_resume.py.

Both modules independently re-derived the same `rf"\b{re.escape(term)}\b"`
regex at 8 call sites before this was extracted -- a naive substring check
would let "team lead" false-match inside "team leadership", or "junior"
false-match a coincidentally-titled unrelated job entry (both real bugs
documented in CLAUDE.md). Word-boundary matching is the fix; this module is
just the one place that fix lives now, instead of eight.
"""

from __future__ import annotations

import re


def word_boundary_pattern(term: str) -> str:
    return rf"\b{re.escape(term)}\b"


def word_boundary_match(term: str, text: str) -> bool:
    return re.search(word_boundary_pattern(term), text) is not None
