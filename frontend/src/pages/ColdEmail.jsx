import { Link } from "react-router-dom";
import { api } from "../api.js";
import Loading from "../components/Loading.jsx";
import LaneSection from "../components/LaneSection.jsx";
import { CheckCircleIcon, FilterIcon, MailIcon, SearchIcon, TailorIcon } from "../components/icons.jsx";
import StatItem from "../components/StatItem.jsx";
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
  const { data, error } = useApiData(() => api.dashboard(), []);

  if (error) return <p className="error-banner">{error}</p>;
  if (!data) return <Loading />;

  const latestSummary = data.summary.length ? data.summary[data.summary.length - 1] : null;

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
          <Link className="button secondary" to="/dashboard">Back to dashboard</Link>
        </div>
      </div>

      {latestSummary && (
        <div className="stat-strip">
          <StatItem icon={<SearchIcon />} label="Scanned" value={latestSummary.cold_email_scanned || 0} />
          <StatItem icon={<FilterIcon />} label="Eligible" value={latestSummary.cold_email_eligible || 0} />
          <StatItem icon={<TailorIcon />} label="Relevant to your resume" value={latestSummary.cold_email_matched || 0} />
          <StatItem icon={<CheckCircleIcon />} label="Contacts found" value={latestSummary.cold_email_contacts_found || 0} tone="signal" />
          <StatItem icon={<MailIcon />} label="Sent" value={data.cold_emails.length} tone="pine" />
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
