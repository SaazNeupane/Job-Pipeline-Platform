import { useState } from "react";
import { Link, useNavigate, useOutletContext } from "react-router-dom";
import { api } from "../../api.js";
import { useApiData } from "../../hooks/useApiData.js";

export default function Push() {
  const { user } = useOutletContext();
  const navigate = useNavigate();
  const { data: preview, error, setError } = useApiData(() => api.pushCommands(user), [user]);
  const [repo, setRepo] = useState("");
  const [result, setResult] = useState(null);
  const [pushing, setPushing] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setPushing(true);
    setError("");
    try {
      const res = await api.push(user, repo);
      setResult(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setPushing(false);
    }
  }

  return (
    <>
      <h1>Push to GitHub</h1>
      <p className="lede">Your profile is saved locally. Now the daily automated run needs to know about it, and that happens through your own copy of the repo on GitHub.</p>

      <div className="card">
        <ol className="steps-list" style={{ marginTop: 0 }}>
          <li>If you haven't already: open the Job Pipeline repo on GitHub and click <strong>"Use this template"</strong> to create your own copy under your own account.</li>
          <li>Clone your new repo locally, and copy your <code>profiles/{user}/</code> folder into it (or just run this wizard again from inside your cloned copy next time).</li>
        </ol>
      </div>

      {error && <p className="error-banner">{error}</p>}
      {preview && !preview.gh_available && (
        <p className="error-banner">
          GitHub CLI (<code>gh</code>) isn't installed or you're not logged in. Install it from{" "}
          <a href="https://cli.github.com/" target="_blank" rel="noopener">cli.github.com</a> and run <code>gh auth login</code>.
          If you just installed it while this app was already open, reloading this page alone won't pick it up.
          Fully quit and reopen the app (Exit above, then relaunch) so it sees the newly installed <code>gh</code>.
          Or just run the commands below yourself.
        </p>
      )}

      {result ? (
        <>
          <p>
            <span className={`badge ${result.ok ? "pine" : "amber"}`}>{result.ok ? "done" : "check log"}</span>{" "}
            {result.ok ? `Secrets and variable pushed to ${result.repo}.` : "Something failed: see the log below."}
          </p>
          <div className="card"><pre className="code-block">{result.log.join("\n")}</pre></div>
          <Link className="button primary" to={`/setup/${user}/done`}>Continue</Link>
        </>
      ) : (
        <>
          <div className="wizard-actions">
            <button type="button" className="ghost" onClick={() => navigate(`/setup/${user}/review`)}>Back</button>
          </div>
          <fieldset>
            <legend>Option A: let this wizard push them for you</legend>
            <form onSubmit={submit}>
              <label>
                Your GitHub repo (owner/name)
                <input value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="yourusername/Job-Pipeline" required disabled={preview && !preview.gh_available} />
              </label>
              <div className="wizard-actions">
                <button type="submit" className="primary" disabled={pushing || (preview && !preview.gh_available)}>
                  {pushing ? "Pushing…" : "Push secrets now"}
                </button>
              </div>
            </form>
          </fieldset>

          <fieldset>
            <legend>Option B: run these yourself</legend>
            <p className="hint">Replace <code>&lt;owner&gt;/&lt;repo&gt;</code> with your repo. Run in a terminal from your cloned copy.</p>
            {preview && <pre className="code-block">{preview.commands.join("\n")}</pre>}
            <Link className="button secondary" to={`/setup/${user}/done`}>I've done this myself, continue</Link>
          </fieldset>
        </>
      )}
    </>
  );
}
