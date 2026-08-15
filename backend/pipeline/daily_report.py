"""Summarize the day's run and email/log it (spec Section 4, step 7).

Delivered both ways (confirmed in build step 10): a row appended to the
daily_summary sheet tab for permanent record-keeping, and an email to
report_email (your real inbox — distinct from gmail_address, the dedicated
address that sends cold emails) so the summary actually gets noticed.

Rewritten 2026-08-14 for the swipe-queue architecture (auto-apply was
removed — see CLAUDE.md's "Remove auto-apply" commit and the Build status
correction at the top of that file). The old stats ("Applied" counting
same-day applied_jobs rows, "Pending your approval" counting same-day
pending_approval rows) were both silently broken under the current flow: a
fresh run never writes pending_approval directly anymore — new matches land
in swipe_queue and only become a pending_approval row once you swipe right
— so "Pending your approval: 0" was misleadingly the permanent, guaranteed
value on every single run regardless of whether the run actually found
anything, and "Applied" only ever moves on a manual "Mark applied" click,
never from the run itself. New stats: `queued_count` (new matches added to
the swipe queue today — the real "did this run find anything" signal) and
`awaiting_apply_count` (current backlog of pending_approval rows with real
tailored materials sitting ready, reason_held="awaiting_manual_apply" —
regardless of what day they were generated, since a 3-day-old un-applied
match is exactly as actionable as one from today). `applied_count` and
`emails_sent` keep their original same-day meaning; both are still accurate.

`errors` isn't derived from anything in the Sheet — it's whatever the
orchestrator collected while actually running each step. This module doesn't
run any pipeline steps itself, so until run_pipeline.py exists (build step
11) and can catch failures per step, callers pass in whatever error list
they have (an empty list is fine)."""

from __future__ import annotations

from datetime import date

from pipeline.config import load_profile
from pipeline.google_auth import send_email
from pipeline.postings_store import get_cold_emails, get_postings, record_daily_summary


def build_daily_summary(
    user: str, today: date | None = None, errors: list[str] | None = None, cold_email_stats: dict | None = None,
) -> dict:
    """cold_email_stats, if given, is the funnel dict returned by
    cold_email.run_cold_email_pipeline() (scanned/eligible/matched/
    contacts_found) — cold email now runs its own independent search, so
    those counts can't be reconstructed from the Sheet after the fact the
    way emails_sent (a real sent-today count) still can."""
    today = today or date.today()
    today_str = today.isoformat()
    errors = errors or []
    cold_email_stats = cold_email_stats or {}

    applied_today = [r for r in get_postings(user, status="applied") if r.get("date") == today_str]
    queued_today = [r for r in get_postings(user, status="queued") if r.get("date") == today_str]
    emails_today = [r for r in get_cold_emails(user) if r.get("date") == today_str]
    awaiting_apply = [r for r in get_postings(user, status="pending") if r.get("reason_held") == "awaiting_manual_apply"]

    return {
        "date": today_str,
        "queued_count": len(queued_today),
        "awaiting_apply_count": len(awaiting_apply),
        "applied_count": len(applied_today),
        "emails_sent": len(emails_today),
        "cold_email_scanned": cold_email_stats.get("scanned", 0),
        "cold_email_eligible": cold_email_stats.get("eligible", 0),
        "cold_email_matched": cold_email_stats.get("matched", 0),
        "cold_email_contacts_found": cold_email_stats.get("contacts_found", 0),
        "errors": errors,
    }


def _format_email_body(summary: dict) -> str:
    lines = [
        f"Job pipeline run for {summary['date']}",
        "",
        f"New matches to swipe: {summary['queued_count']}",
        f"Ready to apply (tailored, waiting on you): {summary['awaiting_apply_count']}",
        f"Applied today: {summary['applied_count']}",
        "",
        "Cold email (own search, separate from job-search matches above):",
        f"  Postings scanned: {summary['cold_email_scanned']}",
        f"  Eligible (location/recency): {summary['cold_email_eligible']}",
        f"  Relevant to your resume: {summary['cold_email_matched']}",
        f"  Real contacts found: {summary['cold_email_contacts_found']}",
        f"  Emails sent today: {summary['emails_sent']}",
    ]
    if summary["errors"]:
        lines.append("")
        lines.append(f"Errors ({len(summary['errors'])}):")
        lines.extend(f"- {e}" for e in summary["errors"])
    else:
        lines.append("")
        lines.append("No errors.")
    return "\n".join(lines)


def _stat_cell(value: int, label: str, color: str) -> str:
    return (
        '<td style="background:#ffffff;border:1px solid #ddd6c9;border-radius:9px;'
        'padding:14px 6px;text-align:center;width:25%;">'
        f'<div style="font-size:24px;font-weight:700;color:{color};line-height:1.1;">{value}</div>'
        '<div style="font-size:10px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;'
        f'color:#5b606b;margin-top:4px;">{label}</div>'
        "</td>"
    )


def _format_email_html(summary: dict) -> str:
    """HTML companion to _format_email_body, sent as the multipart/
    alternative html part (see google_auth.send_email) -- table-based
    layout with every style inlined, since email clients (including
    Gmail's own rendering of mail it receives) can't be relied on to
    respect a <style> block or modern CSS the way a browser would."""
    gap = '<td style="width:8px;"></td>'
    job_stats = gap.join([
        _stat_cell(summary["queued_count"], "New to swipe", "#ff6a3d"),
        _stat_cell(summary["awaiting_apply_count"], "Ready to apply", "#ad7a1c"),
        _stat_cell(summary["applied_count"], "Applied today", "#1f7a5c"),
    ])
    cold_email_stats = gap.join([
        _stat_cell(summary["cold_email_scanned"], "Scanned", "#5b606b"),
        _stat_cell(summary["cold_email_matched"], "Relevant", "#ad7a1c"),
        _stat_cell(summary["cold_email_contacts_found"], "Contacts found", "#ff6a3d"),
        _stat_cell(summary["emails_sent"], "Sent today", "#1f7a5c"),
    ])

    if summary["errors"]:
        error_items = "".join(f'<li style="margin-bottom:4px;">{e}</li>' for e in summary["errors"])
        errors_html = (
            '<div style="background:#fbe9e7;border:1px solid #c0392b;border-radius:9px;'
            'padding:12px 16px;margin-top:16px;">'
            f'<div style="font-weight:700;color:#c0392b;margin-bottom:6px;">Errors ({len(summary["errors"])})</div>'
            f'<ul style="margin:0;padding-left:18px;color:#c0392b;font-size:13px;">{error_items}</ul>'
            "</div>"
        )
    else:
        errors_html = (
            '<div style="background:#e1f3ea;border:1px solid #1f7a5c;border-radius:9px;'
            'padding:10px 16px;margin-top:16px;color:#1f7a5c;font-weight:600;font-size:13px;">'
            "No errors."
            "</div>"
        )

    return f"""\
<div style="font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;max-width:480px;
            margin:0 auto;background:#f6f4ef;padding:24px;border-radius:14px;">
  <div style="font-size:11px;font-weight:700;letter-spacing:0.09em;text-transform:uppercase;
              color:#90939c;margin-bottom:4px;">Job Pipeline</div>
  <div style="font-size:22px;font-weight:700;color:#1b1e24;margin-bottom:20px;">
    Run for {summary["date"]}
  </div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>{job_stats}</tr>
  </table>
  <div style="font-size:11px;font-weight:700;letter-spacing:0.09em;text-transform:uppercase;
              color:#90939c;margin-top:20px;margin-bottom:8px;">Cold email (own search)</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>{cold_email_stats}</tr>
  </table>
  {errors_html}
</div>"""


def send_daily_report(user: str, summary: dict) -> None:
    profile = load_profile(user)

    record_daily_summary(user, {
        "date": summary["date"],
        "queued_count": summary["queued_count"],
        "awaiting_apply_count": summary["awaiting_apply_count"],
        "applied_count": summary["applied_count"],
        "emails_sent": summary["emails_sent"],
        "errors": str(len(summary["errors"])),
        "notes": "; ".join(summary["errors"]) if summary["errors"] else "",
        "cold_email_scanned": summary["cold_email_scanned"],
        "cold_email_eligible": summary["cold_email_eligible"],
        "cold_email_matched": summary["cold_email_matched"],
        "cold_email_contacts_found": summary["cold_email_contacts_found"],
    })

    subject = (
        f"Job Pipeline — {summary['date']}: {summary['queued_count']} new to swipe, "
        f"{summary['awaiting_apply_count']} ready to apply, "
        f"{summary['cold_email_contacts_found']} cold contacts found, {summary['emails_sent']} email sent"
    )
    send_email(
        user, profile.report_email, subject,
        _format_email_body(summary), html_body=_format_email_html(summary),
    )
