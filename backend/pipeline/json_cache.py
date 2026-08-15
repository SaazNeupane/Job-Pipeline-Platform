"""Read/write a JSON file used as a local cache or dedupe backup, shared by
cover_letter.py, tailor_resume.py, and sheet_log.py -- each had its own
near-identical exists-check/read/write pair before this was extracted."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json_file(path: Path, default: Any) -> Any:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def write_json_file(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
