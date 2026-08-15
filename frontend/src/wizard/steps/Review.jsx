import { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../../api.js";
import Loading from "../../components/Loading.jsx";

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
