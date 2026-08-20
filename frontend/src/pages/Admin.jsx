import { Fragment, useState } from "react";
import { api } from "../api.js";
import Loading from "../components/Loading.jsx";
import { CheckCircleIcon, InboxIcon } from "../components/icons.jsx";
import StatItem from "../components/StatItem.jsx";
import { useApiData } from "../hooks/useApiData.js";

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button" className="ghost copy-btn"
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1200); }}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function InvitesPanel() {
  const { data: invites, error, reload } = useApiData(() => api.adminInvites(), []);
  const [minting, setMinting] = useState(false);
  const [revokingId, setRevokingId] = useState("");

  async function mint() {
    setMinting(true);
    try {
      await api.adminMintInvite();
      await reload();
    } finally {
      setMinting(false);
    }
  }

  async function revoke(id) {
    setRevokingId(id);
    try {
      await api.adminRevokeInvite(id);
      await reload();
    } finally {
      setRevokingId("");
    }
  }

  if (error) return <p className="error-banner">{error}</p>;
  if (!invites) return <Loading />;

  const unused = invites.filter((i) => !i.used_at);

  return (
    <>
      <div className="stat-strip">
        <StatItem icon={<InboxIcon />} label="Unused codes" value={unused.length} tone="signal" />
        <StatItem icon={<CheckCircleIcon />} label="Redeemed" value={invites.length - unused.length} tone="pine" />
      </div>

      <div className="run-bar">
        <div>
          <h2 style={{ marginTop: 0, marginBottom: "0.2rem" }}>Invite codes</h2>
          <p className="hint">Single-use. Hand one out, it works once, then it's marked redeemed here.</p>
        </div>
        <button type="button" className="primary" onClick={mint} disabled={minting}>
          {minting ? "Generating…" : "Generate code"}
        </button>
      </div>

      {invites.length ? (
        <div className="runs-table">
          <table>
            <thead>
              <tr><th>Code</th><th>Created</th><th>Status</th><th /></tr>
            </thead>
            <tbody>
              {invites.map((inv) => (
                <tr key={inv.id}>
                  <td><code>{inv.code}</code></td>
                  <td>{inv.created_at.slice(0, 10)}</td>
                  <td>
                    {inv.used_at
                      ? <span className="badge pine">Redeemed{inv.used_by_email ? ` by ${inv.used_by_email}` : ""}</span>
                      : <span className="badge signal">Unused</span>}
                  </td>
                  <td>
                    <CopyButton text={inv.code} />
                    {!inv.used_at && (
                      <button
                        type="button" className="ghost badge-retry" disabled={revokingId === inv.id}
                        onClick={() => revoke(inv.id)}
                      >
                        {revokingId === inv.id ? "Revoking…" : "Revoke"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-state">No invite codes yet. Generate the first one above.</div>
      )}
    </>
  );
}

function UserDetailRow({ user, onChanged }) {
  const { data: detail, error, reload } = useApiData(() => api.adminUserDetail(user.id), [user.id]);
  const [busy, setBusy] = useState(false);

  async function toggleActive() {
    setBusy(true);
    try {
      await api.adminSetUserActive(user.id, !detail.active);
      await reload();
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  if (error) return <tr><td colSpan={6}><p className="error-banner">{error}</p></td></tr>;
  if (!detail) return <tr><td colSpan={6}><Loading /></td></tr>;

  const postingLabels = { queued: "Queued", pending: "Ready to apply", applied: "Applied", dismissed: "Dismissed" };

  return (
    <tr>
      <td colSpan={6}>
        <div className="detail-panel">
          {detail.profile ? (
            <div className="grid2">
              <div>
                <p className="eyebrow">Lanes</p>
                <p>{detail.profile.lanes.map((l) => l.name.replace(/_/g, " ")).join(", ") || "none"}</p>
                <p className="eyebrow">Location targeting</p>
                <p>
                  Countries: {detail.profile.target_countries.join(", ") || "any"}
                  {detail.profile.target_regions.length > 0 && <>, provinces/states: {detail.profile.target_regions.join(", ")}</>}
                </p>
                <p className="eyebrow">Schedule</p>
                <p>{detail.profile.apply_daily_cap} per lane/day, runs at {String(detail.profile.run_hour_utc).padStart(2, "0")}:00 UTC</p>
              </div>
              <div>
                <p className="eyebrow">Google</p>
                <p>{detail.google_connected ? `Connected (${detail.google_email})` : "Not connected"}</p>
                <p className="eyebrow">Postings</p>
                <p>
                  {Object.keys(detail.postings_by_status).length
                    ? Object.entries(detail.postings_by_status).map(([s, n]) => `${postingLabels[s] || s}: ${n}`).join(", ")
                    : "none yet"}
                </p>
                <p className="eyebrow">Cold emails sent</p>
                <p>{detail.cold_emails_sent}</p>
              </div>
            </div>
          ) : (
            <p className="hint">Hasn't finished the setup wizard yet.</p>
          )}

          {detail.recent_runs.length > 0 && (
            <>
              <p className="eyebrow" style={{ marginTop: "1rem" }}>Recent runs</p>
              <div className="runs-table">
                <table>
                  <thead><tr><th>Date</th><th>Queued</th><th>Applied</th><th>Emails</th><th>Errors</th></tr></thead>
                  <tbody>
                    {detail.recent_runs.map((r, i) => {
                      // r.errors is always a numeric string ("0", "1", ...), never "" -- see
                      // Dashboard.jsx's own Runs tab for the same fix and why.
                      const errorCount = Number(r.errors) || 0;
                      return (
                        <tr key={i}>
                          <td>{r.date}</td>
                          <td>{r.queued}</td>
                          <td>{r.applied}</td>
                          <td>{r.emails_sent}</td>
                          <td>{errorCount ? <span className="badge amber">{errorCount}</span> : <span className="hint">none</span>}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <button type="button" className="ghost badge-retry" style={{ marginTop: "1rem" }} disabled={busy} onClick={toggleActive}>
            {busy ? "Saving…" : detail.active ? "Deactivate account" : "Reactivate account"}
          </button>
        </div>
      </td>
    </tr>
  );
}

function UsersPanel() {
  const { data: users, error, reload } = useApiData(() => api.adminUsers(), []);
  const [expandedId, setExpandedId] = useState("");

  if (error) return <p className="error-banner">{error}</p>;
  if (!users) return <Loading />;

  return (
    <>
      <h2>Users</h2>
      <p className="hint">Click a row for their setup, location targeting, Google connection, posting funnel, and recent runs.</p>
      {users.length ? (
        <div className="runs-table">
          <table>
            <thead>
              <tr><th>Email</th><th>Joined</th><th>Verified</th><th>Setup</th><th>Lanes</th><th>Active</th></tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <Fragment key={u.id}>
                  <tr onClick={() => setExpandedId(expandedId === u.id ? "" : u.id)} style={{ cursor: "pointer" }}>
                    <td>{u.email}{u.is_admin && <span className="badge" style={{ marginLeft: "0.4rem" }}>Admin</span>}</td>
                    <td>{u.created_at.slice(0, 10)}</td>
                    <td>{u.email_verified ? <span className="badge pine">Yes</span> : <span className="hint">No</span>}</td>
                    <td>{u.has_profile ? <span className="badge pine">Done</span> : <span className="hint">In progress</span>}</td>
                    <td>{u.lane_count}</td>
                    <td>{u.active ? <span className="hint">Yes</span> : <span className="badge danger">No</span>}</td>
                  </tr>
                  {expandedId === u.id && <UserDetailRow user={u} onChanged={reload} />}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-state">No users yet.</div>
      )}
    </>
  );
}

export default function Admin() {
  return (
    <>
      <div className="dash-head">
        <div>
          <h1>Admin</h1>
          <p className="lede">Invite codes and a read-only look at who's signed up.</p>
        </div>
      </div>

      <InvitesPanel />
      <div style={{ marginTop: "3rem" }}>
        <UsersPanel />
      </div>
    </>
  );
}
