"""datetime.utcnow() is deprecated (3.12+) and returns a naive datetime -- the replacement
datetime.now(timezone.utc) is timezone-AWARE, which isn't a drop-in swap here: every
DateTime column in app/models.py is a plain (timezone-naive) column, and every hand-built
ISO string in postings_store.py/main.py already assumes a naive UTC value on both write and
read (e.g. DailySummary.date string comparisons). utcnow() below is the actual drop-in --
same naive-UTC value as datetime.utcnow(), just via a call that isn't deprecated."""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
