"""Small formatting helpers shared by dashboard.py and swipe.py, ported unchanged from the
old webapp/app.py."""

from __future__ import annotations

from pipeline.wizard import LANE_TEMPLATES


def lane_label(lane_name: str) -> str:
    preset = LANE_TEMPLATES.get(lane_name)
    return preset["label"] if preset else lane_name.replace("_", " ").title()


def newest_first(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: r.get("posted_date") or r.get("date") or "", reverse=True)


def group_by_lane(rows: list[dict], lane_names: list[str]) -> list[dict]:
    sections = [
        {"slug": name, "label": lane_label(name), "rows": newest_first([r for r in rows if r.get("lane") == name])}
        for name in lane_names
    ]
    other = newest_first([r for r in rows if r.get("lane") not in lane_names])
    if other:
        sections.append({"slug": "other", "label": "Other", "rows": other})
    return sections
