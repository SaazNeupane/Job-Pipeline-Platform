"""Read/write a JSON file used as a local cache or dedupe backup, shared by
cover_letter.py, tailor_resume.py, and sheet_log.py -- each had its own
near-identical exists-check/read/write pair before this was extracted."""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def read_json_file(path: Path, default: Any) -> Any:
    """A cache file, not a source of truth -- a truncated/corrupt read (e.g. the process
    got killed mid-write by a redeploy) must fall back to `default` rather than crash
    every future caller. Real bug, found live: this cache is a single file shared across
    every user's requests (cover_letter.py's CACHE_PATH), so one interrupted write used
    to break cover-letter generation for the whole instance until the next redeploy wiped
    the disk clean."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("json_cache: %s is corrupt, treating as empty", path)
        return default


def write_json_file(path: Path, data: Any) -> None:
    """Writes via a temp file + atomic rename so a process killed mid-write (e.g. by a
    redeploy) can never leave a truncated file behind for read_json_file to trip over."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)
