import { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../../api.js";
import Loading from "../../components/Loading.jsx";

const SENIORITY_LABELS = { intern: "internships only", entry: "entry-level only", intermediate: "up to intermediate", senior: "up to senior" };

// Short, scannable facts about what a lane will actually search for -- the settings
// most likely to be wrong (and most annoying to discover only after finalize creates
// the Google Sheet), pulled from the same lane config that drives real search/filter
// logic, not restated from the wizard form state.
function laneSearchFacts(lane) {
  if (!lane) return [];
  const facts = [`${lane.keywords?.length || 0} keyword${(lane.keywords?.length || 0) === 1 ? "" : "s"}`];
  if (lane.seniority_max) facts.push(SENIORITY_LABELS[lane.seniority_max] || lane.seniority_max);
  if (lane.remote_types?.length) facts.push(lane.remote_types.join("/"));
  if (lane.employment_types?.length) facts.push(lane.employment_types.join("/").replace(/_/g, " "));
  if (lane.salary_min || lane.salary_max) {
    facts.push(lane.salary_min && lane.salary_max ? `$${lane.salary_min}–$${lane.salary_max}` : `$${lane.salary_min || lane.salary_max}+`);
  }
  if (lane.radius_km) facts.push(`within ${lane.radius_km}km`);
  return facts;
}

async function previewResumePdf(laneName, setError) {
  try {
    const blob = await api.previewResume(laneName);
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (e) {
    setError(e.message);
  }
}

function ReviewSummary({ profile, resumes, setError }) {
  const laneNames = (profile.lanes || []).map((lane) => lane.name);
  const tiles = [
    {
      label: "Applying as",
      value: `${profile.applicant?.first_name || ""} ${profile.applicant?.last_name || ""} (${profile.applicant?.country || ""})`,
    },
    {
      label: "Job types",
      value: laneNames.length ? laneNames.map((n) => n.replace(/_/g, " ")).join(", ") : "none yet",
    },
    {
      label: "Boards searched",
      value: `${profile.greenhouse_boards?.length || 0} Greenhouse, ${profile.lever_companies?.length || 0} Lever, ${profile.ashby_boards?.length || 0} Ashby`,
    },
    { label: "Countries accepted", value: profile.target_countries?.length ? profile.target_countries.join(", ") : "any" },
    { label: "Provinces/states accepted", value: profile.target_regions?.length ? profile.target_regions.join(", ") : "any" },
    { label: "Daily queue limit", value: `${profile.apply_daily_cap} per lane, per day` },
    { label: "Run time", value: `${String(profile.run_hour_utc ?? 14).padStart(2, "0")}:00 UTC` },
    { label: "Connected Google account", value: profile.gmail_address },
  ];

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>Summary</h2>
      <div className="summary-grid">
        {tiles.map((tile) => (
          <div className="summary-tile" key={tile.label}>
            <div className="eyebrow">{tile.label}</div>
            <div className="summary-value">{tile.value}</div>
          </div>
        ))}
      </div>
      <p className="hint" style={{ marginTop: "0.6rem" }}>Blank board fields above use our default lists.</p>

      <div className="resume-breakdown">
        <span className="eyebrow">Resumes</span>
        <div className="resume-lane-grid">
          {Object.entries(resumes || {}).map(([laneName, resume]) => {
            const relevant = resume.experience?.relevant?.length || 0;
            const additional = resume.experience?.additional?.length || 0;
            const skillCount = Object.values(resume.skills || {}).flat().length;
            const stats = [
              { label: "Experience", value: relevant + additional },
              { label: "Skills", value: skillCount },
              { label: "Projects", value: resume.projects?.length || 0 },
              { label: "Education", value: resume.education?.length || 0 },
            ];
            const lane = (profile.lanes || []).find((l) => l.name === laneName);
            const facts = laneSearchFacts(lane);
            return (
              <div className="resume-lane-card" key={laneName}>
                <div className="resume-lane-name">{laneName.replace(/_/g, " ")}</div>
                <div className="resume-lane-stats">
                  {stats.map((s) => (
                    <div className="resume-lane-stat" key={s.label}>
                      <span className="resume-lane-stat-num">{s.value}</span>
                      <span className="resume-lane-stat-label">{s.label}</span>
                    </div>
                  ))}
                </div>
                {facts.length > 0 && <div className="resume-lane-facts">Searching: {facts.join(" · ")}</div>}
                <button type="button" className="ghost" onClick={() => previewResumePdf(laneName, setError)}>Preview PDF</button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default function Review() {
  const navigate = useNavigate();
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");
  const [needsGoogle, setNeedsGoogle] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.review()
      .then(setPreview)
      .catch((e) => {
        if (e.message.toLowerCase().includes("connect google")) setNeedsGoogle(true);
        else setError(e.message);
      });
  }, []);

  if (needsGoogle) return <Navigate to="/setup/google" replace />;

  async function save() {
    setSaving(true);
    setError("");
    try {
      await api.finalize();
      navigate("/setup/done");
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  }

  return (
    <>
      <h1>Review</h1>
      <p className="lede">This is what will be saved. Continuing also creates and formats your Google Sheet.</p>
      {error && <p className="error-banner">{error}</p>}

      {preview ? (
        <>
          <ReviewSummary profile={preview.profile_yaml} resumes={preview.resumes} setError={setError} />
          <details className="advanced">
            <summary>View raw data</summary>
            <div className="card">
              <h2 style={{ marginTop: 0 }}>Profile</h2>
              <pre className="code-block">{JSON.stringify(preview.profile_yaml, null, 2)}</pre>
            </div>
            {Object.entries(preview.resumes).map(([laneName, resume]) => (
              <div className="card" key={laneName}>
                <h2 style={{ marginTop: 0 }}>Resume: {laneName}</h2>
                <pre className="code-block">{JSON.stringify(resume, null, 2)}</pre>
              </div>
            ))}
          </details>
          <div className="wizard-actions">
            <button type="button" className="ghost" onClick={() => navigate("/setup/google")} disabled={saving}>Back</button>
            <button className="primary" onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Save and create my Google Sheet"}
            </button>
          </div>
        </>
      ) : (
        !error && <Loading />
      )}
    </>
  );
}
