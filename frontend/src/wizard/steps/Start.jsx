import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api.js";

export default function Start() {
  const [user, setUser] = useState("");
  const [error, setError] = useState("");
  const [collision, setCollision] = useState("");
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();

  async function go(confirmOverwrite = false) {
    setError("");
    setCreating(true);
    try {
      const resp = await api.wizardStart(user, confirmOverwrite);
      if (resp.collision) {
        setCollision(resp.user);
        return;
      }
      navigate(`/setup/${resp.user}/about`);
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <h1>Let's set up your job pipeline</h1>
      <p>
        First, pick a short id for yourself. This becomes the name of your local profile folder.
        Lowercase letters, numbers, <code>-</code> or <code>_</code> only (e.g. your first name).
      </p>
      {error && <p className="error-banner">{error}</p>}
      {collision ? (
        <>
          <p className="error-banner">A profile called "{collision}" already exists on this machine.</p>
          <div className="wizard-actions">
            <button className="primary" onClick={() => go(true)} disabled={creating}>{creating ? "Creating…" : "Continue anyway (overwrite when I save)"}</button>
            <button className="ghost" onClick={() => setCollision("")} disabled={creating}>Pick a different id</button>
          </div>
        </>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); go(); }}>
          <label>
            Your id
            <input
              type="text" value={user} onChange={(e) => setUser(e.target.value)}
              placeholder="e.g. alex" required pattern="[a-z0-9_-]+" disabled={creating}
            />
          </label>
          <div className="wizard-actions">
            <button type="submit" className="primary" disabled={creating}>{creating ? "Creating…" : "Continue"}</button>
          </div>
        </form>
      )}
    </>
  );
}
