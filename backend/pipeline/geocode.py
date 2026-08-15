"""Turns a plain-text address into (latitude, longitude) via Nominatim (OpenStreetMap) --
no API key, no billing account, same free-tier-only philosophy already used for Gemini
elsewhere in this project. Replaces the old wizard flow of manually right-clicking Google
Maps and pasting in raw coordinates."""

from __future__ import annotations

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim's usage policy requires a real identifying User-Agent -- an unmarked default
# requests UA is liable to get silently rate-limited or blocked.
_USER_AGENT = "job-pipeline-platform (setup-wizard address lookup)"
_TIMEOUT_SECONDS = 8


def geocode_address(address: str) -> tuple[float, float] | None:
    """Returns (latitude, longitude) for the first match, or None if the address can't be
    geocoded (never raises for a bad/unrecognized address -- only for a real network/HTTP
    failure, which the caller should surface as a real error rather than swallow)."""
    address = address.strip()
    if not address:
        return None

    response = requests.get(
        NOMINATIM_URL,
        params={"q": address, "format": "json", "limit": 1},
        headers={"User-Agent": _USER_AGENT},
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        return None

    return float(results[0]["lat"]), float(results[0]["lon"])
