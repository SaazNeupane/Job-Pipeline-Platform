import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api.js";
import Loading from "../components/Loading.jsx";
import LaneSection from "../components/LaneSection.jsx";
import { useApiData } from "../hooks/useApiData.js";

function ColdEmailCard({ row }) {
  return (
    <div className="posting-card posting-card--cold-email">
      <div className="posting-card-top">
        <div className="posting-main">
          <div className="posting-company">{row.company}</div>
          <div className="posting-role">{row.contact_name}{row.contact_email ? ` <${row.contact_email}>` : ""}</div>
          <div className="posting-meta">
            {row.location && <span className="badge">{row.location}</span>}
            {row.replied === "Y" && <span className="badge pine">Replied</span>}
            {row.bounced === "Y" && <span className="badge danger">Bounced</span>}
            <span className="hint">sent {(row.sent_at || row.date || "").slice(0, 10)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ColdEmail() {
  const { user } = useParams();
  const { data, error } = useApiData(() => api.dashboard(user), [user]);
  const [runStatus, setRunStatus] = useState("");
  const [running, setRunning] = useState(false);

  if (error) return <p className="error-banner">{error}</p>;
  if (!data) return <Loading />;

  const latestSummary = data.summary.length ? data.summary[data.summary.length - 1] : null;

  async function runNow() {
    setRunning(true);
    const res = await api.runNow(user, { cold_email_only: true });
    setRunning(false);
    setRunStatus(res.status);
    if (res.status === "triggered") setTimeout(() => setRunStatus(""), 6000);
  }

  return (
    <>
      <div className="dash-head">
        <div>
          <h1>Cold email</h1>
          <p className="lede">
            Searches Adzuna and hiring.cafe on its own, separate from the job matches on the dashboard. It looks for
            postings with a real, published contact email.
          </p>
        </div>
        <div className="dash-head-links">
          {data.github_repo && (
            <button type="button" onClick={runNow} disabled={running}>{running ? "Triggering…" : "Run cold email now"}</button>
          )}
          <Link className="button secondary" to={`/dashboard/${user}`}>Back to dashboard</Link>
        </div>
      </div>

      {runStatus === "triggered" && <div className="banner info">Triggered. Check GitHub Actions in a minute or two.</div>}
      {runStatus === "failed" && <div className="banner">Couldn't trigger the run. Make sure the GitHub CLI is installed and logged in (<code>gh auth login</code>), then try again.</div>}
      {!data.github_repo && <div className="banner info">No repo on file yet. Set one on the dashboard first to enable manual runs.</div>}

      {latestSummary && (
        <div className="stat-strip">
          <div className="stat-item">
            <div className="eyebrow">Scanned</div>
            <div className="stat-num">{latestSummary.cold_email_scanned || 0}</div>
          </div>
          <div className="stat-item">
            <div className="eyebrow">Eligible</div>
            <div className="stat-num">{latestSummary.cold_email_eligible || 0}</div>
          </div>
          <div className="stat-item">
            <div className="eyebrow">Relevant to your resume</div>
            <div className="stat-num">{latestSummary.cold_email_matched || 0}</div>
          </div>
          <div className="stat-item">
            <div className="eyebrow">Contacts found</div>
            <div className="stat-num signal">{latestSummary.cold_email_contacts_found || 0}</div>
          </div>
          <div className="stat-item">
            <div className="eyebrow">Sent</div>
            <div className="stat-num pine">{data.cold_emails.length}</div>
          </div>
        </div>
      )}

      <h2>Sent</h2>
      {data.cold_emails.length ? (
        data.cold_emails_by_lane.map((section) => section.rows.length > 0 && (
          <LaneSection key={section.slug} section={section}>
            <div className="posting-list">
              {section.rows.map((row) => <ColdEmailCard key={row.posting_key} row={row} />)}
            </div>
          </LaneSection>
        ))
      ) : (
        <div className="empty-state">No cold emails sent yet.</div>
      )}
    </>
  );
}
