import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import FlowRail from "../components/FlowRail.jsx";
import Loading from "../components/Loading.jsx";
import { useApiData } from "../hooks/useApiData.js";

const PROCESS = [
  { key: "search", label: "Search real postings" },
  { key: "filter", label: "Filter to real fits" },
  { key: "swipe", label: "Swipe to pick favorites" },
  { key: "tailor", label: "Tailor resume + letter" },
  { key: "apply", label: "Apply yourself" },
];

function initials(name) {
  return name.slice(0, 2).toUpperCase();
}

export default function Home() {
  const { data: profiles, reload } = useApiData(() => api.profiles().then((r) => r.profiles).catch(() => []), []);
  const [deleting, setDeleting] = useState("");

  async function deleteProfile(e, name) {
    e.preventDefault();
    e.stopPropagation();
    if (!window.confirm(`Delete the "${name}" profile? This permanently removes its resume, secrets, and settings from this machine so you can set it up again from scratch. This can't be undone.`)) return;
    setDeleting(name);
    try {
      await api.deleteProfile(name);
      await reload();
    } catch (err) {
      window.alert(err.message);
    } finally {
      setDeleting("");
    }
  }

  return (
    <>
      <div className="hero">
        <p className="eyebrow">Local &amp; self-hosted</p>
        <h1>Your job search, running itself</h1>
        <p className="lede">
          It searches real postings every day and filters them down to ones worth your time. You swipe
          through to pick the jobs you actually want, and it tailors a resume and cover letter for each
          one you like. You apply yourself, from your own dashboard. Everything runs under your own
          accounts, and it never invents anything about you.
        </p>
        <div className="hero-actions">
          <Link className="button primary" to="/setup/start">Set up a new profile</Link>
          <Link className="button secondary" to="/guide">Read the guide first</Link>
        </div>
      </div>

      <div className="process-strip">
        <FlowRail horizontal steps={PROCESS.map((p) => ({ ...p, state: "static" }))} />
      </div>

      <div className="section-heading">
        <h2>Your profiles</h2>
      </div>
      {profiles === null ? (
        <Loading />
      ) : profiles.length ? (
        <div className="profile-grid">
          {profiles.map((p) => (
            <Link key={p} to={`/dashboard/${p}`} className="profile-card">
              <span className="profile-avatar">{initials(p)}</span>
              <span style={{ flex: 1 }}>
                <div className="profile-card-name">{p}</div>
                <div className="profile-card-sub">Open dashboard →</div>
              </span>
              <button
                type="button" className="ghost profile-card-delete"
                onClick={(e) => deleteProfile(e, p)} disabled={deleting === p}
                title={`Delete ${p}`}
              >
                {deleting === p ? "…" : "Delete"}
              </button>
            </Link>
          ))}
        </div>
      ) : (
        <div className="empty-state">No profiles set up on this machine yet. Set one up above.</div>
      )}
    </>
  );
}
