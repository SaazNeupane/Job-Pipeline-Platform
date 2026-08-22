import { useState } from "react";
import { sourceLabel } from "../sourceLabels.js";

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // clipboard API unavailable (e.g. non-HTTPS context) -- fail silently,
      // the text is already right there to select by hand
      return;
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <button type="button" className="ghost copy-btn" onClick={copy}>
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function matchPercent(score) {
  if (score === null || score === undefined || score === "") return null;
  return Math.round(Number(score) * 100);
}

const OUTCOME_LABELS = {
  "": "No response yet",
  responded: "Got a response",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
};

export default function PostingCard({ row, selected, onToggleSelect, onPromote, onDismiss, onRetry, onSetOutcome, open, onToggleOpen, applied, busy }) {
  const generating = row.reason_held === "generating";
  const failed = (row.reason_held || "").startsWith("generation_failed");
  const match = matchPercent(row.match_score);
  const terms = (row.matched_terms || "").split(",").filter(Boolean);
  const flags = (row.content_flags || "").split("; ").filter(Boolean);
  return (
    <div className={`posting-card ${applied ? "posting-card--applied" : "posting-card--pending"}${selected ? " selected" : ""}`}>
      <div className="posting-card-top">
        {!applied && (
          <label className="posting-select">
            <input type="checkbox" checked={selected} onChange={(e) => onToggleSelect(e.target.checked)} disabled={!!busy || generating} />
          </label>
        )}
        <div className="posting-main">
          <div className="posting-company">{row.company}</div>
          <div className="posting-role">{row.role}</div>
          <div className="posting-meta">
            {generating && (
              <span className="badge signal spinner-badge">
                <span className="spinner" />Tailoring resume &amp; cover letter…
                <button type="button" className="badge-retry" onClick={onRetry} disabled={!!busy} title="Stuck? Try again">retry</button>
              </span>
            )}
            {failed && (
              <span className="badge danger" title={row.reason_held}>
                Generation failed
                <button type="button" className="badge-retry" onClick={onRetry} disabled={!!busy}>{busy === "retry" ? "retrying…" : "retry"}</button>
              </span>
            )}
            {match !== null && <span className="badge signal">{match}% match</span>}
            {row.source && <span className="badge">{sourceLabel(row.source)}</span>}
            {row.location && <span className="badge">{row.location}</span>}
            {row.required_years && <span className="badge">{row.required_years}+ yrs exp</span>}
            {applied && <span className="badge pine">{row.application_status}</span>}
            {applied && onSetOutcome && (
              <select
                className="outcome-select"
                value={row.outcome || ""}
                disabled={busy === "outcome"}
                onChange={(e) => onSetOutcome(e.target.value)}
              >
                {Object.entries(OUTCOME_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            )}
            <span className="hint">
              {applied ? "applied" : "found"} {row.date}
              {row.posted_date ? ` · posted ${row.posted_date.slice(0, 10)}` : ""}
            </span>
          </div>
        </div>
        <div className="posting-actions">
          {(row.application_url || row.resume_link || row.cover_letter) && (
            <button type="button" className="ghost" onClick={onToggleOpen} disabled={!!busy}>{open ? "Hide" : "Details"}</button>
          )}
          {!applied && (
            <>
              <button type="button" className="danger" onClick={onDismiss} disabled={!!busy}>{busy === "dismiss" ? "Working…" : "Dismiss"}</button>
              <button type="button" className="primary" onClick={onPromote} disabled={!!busy || generating} title={generating ? "Still tailoring your resume and cover letter" : undefined}>{busy === "promote" ? "Working…" : "Mark applied"}</button>
            </>
          )}
        </div>
      </div>
      {open && (
        <div className="detail-panel">
          <div className="detail-panel-links">
            {row.application_url && <a className="button" href={row.application_url} target="_blank" rel="noopener">View posting &amp; apply</a>}
            {row.resume_link && <a className="button secondary" href={row.resume_link} target="_blank" rel="noopener">Open tailored resume</a>}
          </div>
          {terms.length > 0 && (
            <div className="swipe-card-terms">
              {terms.map((t) => <span key={t} className="badge amber">{t}</span>)}
            </div>
          )}
          {flags.length > 0 && (
            <div className="swipe-card-terms">
              {flags.map((f) => <span key={f} className="badge danger">{f}</span>)}
            </div>
          )}
          {row.cover_letter && (
            <>
              <div className="detail-panel-heading">
                <h4>Cover letter</h4>
                <CopyButton text={row.cover_letter} />
              </div>
              <pre className="code-block">{row.cover_letter}</pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}
