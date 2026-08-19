"""Orchestrator entrypoint, run daily via GitHub Actions cron (spec Section 2
/ Section 7, step 11).

Error handling (confirmed in build step 11): every step is wrapped so a
failure is logged and skipped rather than crashing the whole run — the
daily report always goes out summarizing whatever did succeed, plus the
list of what failed.

No auto-submit: this pipeline used to fill and submit ATS forms itself
(the old apply.py, gated by DRY_RUN/auto_submit_daily_cap). Removed per
explicit user request — captcha/custom-question gates meant real
auto-submission almost never actually cleared (see CLAUDE.md), so a human
deciding which postings are even worth pursuing is now the first gate,
not the last one. apply.py and its cap are deleted entirely, not just
unused. Every filtered match is queued into the swipe_queue sheet tab
(pipeline.swipe_actions.queue_for_swipe) with just enough info for a
swipe decision — title/company/location/posted date/stack/salary, no
resume or cover letter generated yet. Swiping right (pipeline.swipe_actions.queue_like, called from the webapp)
drops a placeholder in pending_approval immediately and generates the
resume/cover letter/Drive link afterward in a background thread
(generate_liked_materials) so the swipe click itself isn't blocked on that
work; swiping left moves it straight to dismissed_jobs, same permanence as
the dashboard's existing Dismiss action.
"""

from __future__ import annotations

import logging
import os
import sys

from pipeline.cold_email import run_cold_email_pipeline
from pipeline.config import load_profile, load_secrets
from pipeline.daily_report import build_daily_summary, send_daily_report
from pipeline.drive_storage import cleanup_old_files
from pipeline.filter import RECENCY_MAX_AGE_DAYS, filter_postings, posting_fingerprint
from pipeline.postings_store import get_existing_dedupe_keys, get_existing_fingerprints
from pipeline.search import search_adzuna, search_ashby, search_greenhouse, search_hiring_cafe, search_lever
from pipeline.swipe_actions import queue_for_swipe


def run(
    user: str, lane_filter: str | None = None, max_age_days: int | None = None, cold_email_only: bool = False,
) -> None:
    """`lane_filter`, if given, only runs the one lane with that name (e.g.
    a manual re-run of a single lane after tweaking its keywords) instead
    of every lane in the profile. `max_age_days` overrides
    filter.RECENCY_MAX_AGE_DAYS for this run only — e.g. widening the
    window on a manual run to catch postings an earlier scheduled run's
    default 14-day cutoff would have missed. `cold_email_only` skips the
    job-search lanes' search/filter/queue-for-swipe steps entirely and only
    runs cold email — its own search/filter (see cold_email.py) is
    unaffected by lane_filter/max_age_days either way, since it's
    independent of the job-search lanes. All three default to their
    original no-override behavior."""
    errors: list[str] = []
    max_age_days = max_age_days if max_age_days is not None else RECENCY_MAX_AGE_DAYS

    def _try(step_name, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — deliberately broad, see module docstring
            message = f"{step_name}: {exc}"
            errors.append(message)
            logging.error("[run_pipeline] %s", message)
            return None

    profile = load_profile(user)
    secrets = load_secrets(user)

    lanes = profile.lanes
    if lane_filter:
        lanes = [lane for lane in profile.lanes if lane.name == lane_filter]
        if not lanes:
            errors.append(f"lane_filter={lane_filter!r} does not match any configured lane, nothing to run")
    if cold_email_only:
        lanes = []

    print(
        f"[run_pipeline] starting run for {user!r} "
        f"(lanes={[l.name for l in lanes]}, max_age_days={max_age_days}, cold_email_only={cold_email_only})"
    )

    # Board-based sources (greenhouse/lever/ashby) search the same profile-level board
    # list regardless of which lane asked for them -- fetching once per lane that shares
    # a source used to refetch the exact same boards multiple times per run (confirmed
    # live: a real 2-lane profile with both lanes listing "greenhouse" fetched all 24
    # configured boards twice, ~118MB of redundant traffic, a real contributor to the
    # Render OOM restarts). Keyword-based sources (adzuna/hiring_cafe) differ per lane,
    # so those fetch once per source too, but with the UNION of every lane's keywords
    # that wants that source -- still covers every lane's real search terms, just
    # without re-querying a keyword two lanes happen to share.
    sources_needed = {s for lane in lanes for s in lane.sources}
    all_postings = []

    if "greenhouse" in sources_needed:
        result = _try("search_greenhouse", search_greenhouse, profile.greenhouse_boards)
        all_postings.extend(result or [])

    if "lever" in sources_needed:
        result = _try("search_lever", search_lever, profile.lever_companies)
        all_postings.extend(result or [])

    if "ashby" in sources_needed:
        result = _try("search_ashby", search_ashby, profile.ashby_boards)
        all_postings.extend(result or [])

    if "hiring_cafe" in sources_needed:
        hiring_cafe_keywords = sorted({kw for lane in lanes if "hiring_cafe" in lane.sources for kw in lane.keywords})
        result = _try("search_hiring_cafe", search_hiring_cafe, hiring_cafe_keywords)
        all_postings.extend(result or [])

    if "adzuna" in sources_needed:
        app_id, app_key = secrets.get("ADZUNA_APP_ID"), secrets.get("ADZUNA_APP_KEY")
        if app_id and app_key:
            adzuna_keywords = sorted({kw for lane in lanes if "adzuna" in lane.sources for kw in lane.keywords})
            result = _try("search_adzuna", search_adzuna, adzuna_keywords, profile.adzuna_country, app_id, app_key)
            all_postings.extend(result or [])
        else:
            errors.append("search_adzuna: missing ADZUNA_APP_ID/ADZUNA_APP_KEY, skipped")

    # Postings can arrive from more than one source in the same run (e.g. a
    # Greenhouse posting found both directly and via hiring.cafe) — collapse
    # by dedupe_key before filtering, not just against the Sheet's history.
    unique_postings = list({p.dedupe_key(): p for p in all_postings}.values())
    print(f"[run_pipeline] {len(unique_postings)} unique postings across all sources")
    # all_postings (pre-dedupe, can hold real duplicates across sources -- e.g. the same
    # Greenhouse posting found both directly and via hiring.cafe) is never read again below,
    # but the rest of this function (dedupe-key lookups, per-lane filtering, queueing, cold
    # email) is long -- drop the reference now instead of holding two overlapping copies of
    # the same postings alive for no reason for the rest of the run.
    del all_postings

    # Dedupe against applied_jobs (real submissions), pending_approval (held
    # postings), AND dismissed_jobs (postings you explicitly said no to via
    # the dashboard) — a posting that's already sitting in pending_approval
    # shouldn't get a fresh resume/cover letter/Drive upload generated for
    # it every single run, and a dismissed posting shouldn't come back at
    # all. Trade-off, confirmed with the user: a posting held for a
    # transient reason (e.g. an intermittent captcha) no longer gets
    # automatically retried on a later run — clearing/removing its
    # pending_approval row (Mark as Applied) is now the way to make it
    # eligible for reprocessing again; Dismiss instead moves it to
    # dismissed_jobs so it's excluded permanently.
    #
    # Skipped entirely in cold_email_only mode -- nothing here feeds
    # anything but the job-search lanes' own filter_postings loop below,
    # which doesn't run at all when lanes is empty.
    existing_keys: set[str] = set()
    existing_fingerprints: set[str] = set()
    if lanes:
        applied_keys = _try("get_existing_dedupe_keys[applied]", get_existing_dedupe_keys, user, "applied") or set()
        held_keys = (
            _try("get_existing_dedupe_keys[pending]", get_existing_dedupe_keys, user, "pending")
            or set()
        )
        dismissed_keys = (
            _try("get_existing_dedupe_keys[dismissed]", get_existing_dedupe_keys, user, "dismissed")
            or set()
        )
        # queued too — a posting already sitting in the queue (pending
        # a swipe either way) shouldn't get a duplicate card appended next run.
        queued_keys = (
            _try("get_existing_dedupe_keys[queued]", get_existing_dedupe_keys, user, "queued")
            or set()
        )
        existing_keys = applied_keys | held_keys | dismissed_keys | queued_keys

        # Fingerprint dedupe (source+company+title+location, see
        # posting_fingerprint's own docstring) catches what posting_key
        # alone can't: confirmed live 2026-08-13, Adzuna re-listed a real
        # posting (CMHA Thames Valley, "IT Support Helpdesk") under a brand
        # new ad id after the user had already applied to the original
        # listing — same job, different id, so the posting_key check let it
        # right back in looking new. Same four statuses as existing_keys, same
        # reasoning.
        for status in ("applied", "pending", "dismissed", "queued"):
            existing_fingerprints |= _try(f"get_existing_fingerprints[{status}]", get_existing_fingerprints, user, status) or set()

    total_matched = 0
    for lane in lanes:
        matches = _try(
            f"filter_postings[{lane.name}]", filter_postings, unique_postings, lane, existing_keys,
            profile.applicant, profile.target_countries, existing_fingerprints, max_age_days,
        )
        total_matched += len(matches or [])
        if not matches:
            continue
        print(f"[run_pipeline] {lane.name}: {len(matches)} matches after filter/dedupe")

        # More matched terms = closer fit — a simple relevance ordering so
        # the queue cap (needed once live testing showed 250+ matches in a
        # single run) keeps the strongest matches rather than an arbitrary
        # subset. apply_daily_cap now bounds how many NEW cards get queued
        # for a swipe per lane per run, not how many get auto-applied to —
        # same field/semantics repurposed rather than adding a new profile
        # setting for what's functionally the same "don't flood one run" cap.
        queue_matches = sorted(matches, key=lambda m: m[2], reverse=True)[:profile.apply_daily_cap]
        print(f"[run_pipeline] {lane.name}: queuing {len(queue_matches)} for swipe (apply_daily_cap={profile.apply_daily_cap})")

        _try(f"queue_for_swipe[{lane.name}]", queue_for_swipe, user, lane, queue_matches)
        # existing_keys was computed once before this loop started — without
        # updating it here, a posting matching two lanes' criteria (e.g. a
        # posting that happens to satisfy both it_tech and ops_supervisor)
        # would get queued a second time under the next lane in this same
        # run, since the sheet write above doesn't retroactively appear in
        # a variable already sitting in memory. Real bug, found live.
        existing_keys = existing_keys | {posting.dedupe_key() for posting, _, _ in queue_matches}
        existing_fingerprints = existing_fingerprints | {
            posting_fingerprint(posting.source, posting.company, posting.title, posting.location)
            for posting, _, _ in queue_matches
        }

    # Cold email now runs its own search (Adzuna/hiring.cafe, not the
    # job-search lanes' Greenhouse/Lever/Ashby boards) and its own
    # relevance/location/recency filter — no longer tied to job-search
    # lanes' matches or run once per lane. See cold_email.py's module
    # docstring for why.
    cold_email_stats = _try("run_cold_email_pipeline", run_cold_email_pipeline, user, profile, secrets)

    deleted_count = _try("cleanup_old_files", cleanup_old_files, user)
    if deleted_count:
        print(f"[run_pipeline] cleanup_old_files: deleted {deleted_count} resume(s) older than 7 days")

    run_stats = {"total_postings_found": len(unique_postings), "total_matched": total_matched}
    summary = _try("build_daily_summary", build_daily_summary, user, None, errors, cold_email_stats, run_stats) or {
        "date": "", "queued_count": 0, "awaiting_apply_count": 0, "applied_count": 0, "emails_sent": 0,
        "cold_email_scanned": 0, "cold_email_eligible": 0, "cold_email_matched": 0, "cold_email_contacts_found": 0,
        "total_postings_found": 0, "total_matched": 0,
        "errors": errors,
    }
    _try("send_daily_report", send_daily_report, user, summary)

    if errors:
        # Errors are swallowed step-by-step on purpose (module docstring) so one bad source
        # doesn't kill the whole run -- but a run where e.g. all five search sources failed
        # still needs to look like a failure somewhere visible, not a cheerful "done" print
        # indistinguishable from a real success. logging.error (not print) is what actually
        # shows up in Render's captured stdout at a filterable level.
        logging.error("[run_pipeline] done for %r — %d error(s): %s", user, len(errors), "; ".join(errors))
    else:
        print(f"[run_pipeline] done for {user!r} — 0 errors")


if __name__ == "__main__":
    # PIPELINE_LANE/PIPELINE_RECENCY_DAYS/PIPELINE_COLD_EMAIL_ONLY: set by
    # the dashboard's manual "Run now" flow (webapp/app.py -> gh workflow
    # run -f lane=... -f days=... -f cold_email_only=... -> daily.yml's
    # workflow_dispatch inputs -> these env vars) so a one-off run can
    # target a single lane, widen the recency window, or run cold email
    # alone without touching profile.yaml. Unset/false on the normal
    # scheduled cron run, so behavior there is unchanged.
    _days_env = os.environ.get("PIPELINE_RECENCY_DAYS", "").strip()
    run(
        sys.argv[1] if len(sys.argv) > 1 else "saaz",
        lane_filter=os.environ.get("PIPELINE_LANE", "").strip() or None,
        max_age_days=int(_days_env) if _days_env else None,
        cold_email_only=os.environ.get("PIPELINE_COLD_EMAIL_ONLY", "").strip().lower() == "true",
    )
