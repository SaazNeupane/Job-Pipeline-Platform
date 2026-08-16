import { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../../api.js";
import Loading from "../../components/Loading.jsx";

function ReviewSummary({ profile, resumes }) {
  const laneNames = (profile.lanes || []).map((lane) => lane.name);
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>Summary</h2>
      <dl className="summary-list">
        <dt>Applying as</dt>
        <dd>{profile.applicant?.first_name} {profile.applicant?.last_name} ({profile.applicant?.country})</dd>

        <dt>Job types</dt>
        <dd>{laneNames.length ? laneNames.map((n) => n.replace(/_/g, " ")).join(", ") : "none yet"}</dd>

        <dt>Boards searched</dt>
        <dd>
          {(profile.greenhouse_boards?.length || 0)} Greenhouse, {(profile.lever_companies?.length || 0)} Lever, {(profile.ashby_boards?.length || 0)} Ashby
          {" "}(blank fields use our default lists)
        </dd>

        <dt>Countries accepted</dt>
        <dd>{profile.target_countries?.length ? profile.target_countries.join(", ") : "any"}</dd>

        <dt>Daily queue limit</dt>
        <dd>{profile.apply_daily_cap} new postings per lane, per day</dd>

        <dt>Run time</dt>
        <dd>{String(profile.run_hour_utc ?? 14).padStart(2, "0")}:00 UTC</dd>

        <dt>Connected Google account</dt>
        <dd>{profile.gmail_address}</dd>

        <dt>Resumes</dt>
        <dd>
          {Object.entries(resumes || {}).map(([laneName, resume]) => {
            const relevant = resume.experience?.relevant?.length || 0;
            const additional = resume.experience?.additional?.length || 0;
            const projects = resume.projects?.length || 0;
            return (
              <div key={laneName}>
                {laneName.replace(/_/g, " ")}: {relevant + additional} experience entr{relevant + additional === 1 ? "y" : "ies"}, {projects} project{projects === 1 ? "" : "s"}, {resume.education?.length || 0} education entr{(resume.education?.length || 0) === 1 ? "y" : "ies"}
              </div>
            );
          })}
        </dd>
      </dl>
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
          <ReviewSummary profile={preview.profile_yaml} resumes={preview.resumes} />
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
