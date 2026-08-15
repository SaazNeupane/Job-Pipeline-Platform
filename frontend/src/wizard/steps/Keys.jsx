import { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { api } from "../../api.js";

export default function Keys() {
  const { user, draft, refreshDraft } = useOutletContext();
  const s = draft.secrets || {};
  const [form, setForm] = useState({
    adzuna_app_id: s.ADZUNA_APP_ID || "", adzuna_app_key: s.ADZUNA_APP_KEY || "", gemini_api_key: s.GEMINI_API_KEY || "",
  });
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setError("");
    try {
      await api.patchDraft(user, { secrets: form });
      await refreshDraft();
      navigate(`/setup/${user}/google`);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <>
      <h1>API keys</h1>
      <p>Both are free. Adzuna powers job search; Gemini writes your cover letters and helps reword resume bullets to match each posting.</p>
      {error && <p className="error-banner">{error}</p>}
      <form onSubmit={submit}>
        <fieldset>
          <legend>Adzuna</legend>
          <p className="hint">Sign up free at <a href="https://developer.adzuna.com/" target="_blank" rel="noopener">developer.adzuna.com</a>; you'll get an App ID and App Key.</p>
          <label>App ID<input value={form.adzuna_app_id} onChange={set("adzuna_app_id")} required /></label>
          <label>App Key<input value={form.adzuna_app_key} onChange={set("adzuna_app_key")} required /></label>
        </fieldset>
        <fieldset>
          <legend>Gemini (Google AI)</legend>
          <p className="hint">Get a free key at <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">aistudio.google.com/apikey</a> (sign in with the same Google account you'll connect next).</p>
          <label>API key<input value={form.gemini_api_key} onChange={set("gemini_api_key")} required /></label>
        </fieldset>
        <div className="wizard-actions">
          <button type="button" className="ghost" onClick={() => navigate(`/setup/${user}/resume`)}>Back</button>
          <button type="submit" className="primary">Continue</button>
        </div>
      </form>
    </>
  );
}
