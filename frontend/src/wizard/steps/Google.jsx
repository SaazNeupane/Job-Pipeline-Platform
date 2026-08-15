import { useEffect } from "react";
import { useNavigate, useOutletContext, useSearchParams } from "react-router-dom";
import { api } from "../../api.js";
import Loading from "../../components/Loading.jsx";
import { useApiData } from "../../hooks/useApiData.js";

const ERROR_MESSAGES = {
  expired_state: "That connection attempt expired. Try again.",
  exchange_failed: "Google didn't confirm the connection. Try again.",
  access_denied: "You didn't finish granting access. Try again when ready.",
};

export default function Google() {
  const { refreshDraft } = useOutletContext();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { data: state, error, setError, reload } = useApiData(() => api.googleOAuthStatus(), []);

  // Google redirects the BROWSER back to the backend's /api/oauth/google/callback, which
  // then redirects here with ?connected=1 or ?error=... on the query string -- re-check the
  // real status against the backend rather than trusting the query string alone (a stale
  // bookmark/refresh shouldn't show a false "connected").
  useEffect(() => {
    if (searchParams.get("connected") || searchParams.get("error")) {
      reload();
    }
  }, [searchParams, reload]);

  async function connect() {
    setError("");
    try {
      const { authorization_url } = await api.googleOAuthStart();
      window.location.href = authorization_url;
    } catch (err) {
      setError(err.message);
    }
  }

  async function continueToReview() {
    await refreshDraft();
    navigate("/setup/review");
  }

  if (!state) return <Loading />;

  const oauthError = searchParams.get("error");

  return (
    <>
      <h1>Connect your Google account</h1>
      <p className="lede">The pipeline reads and writes a Google Sheet, sends application emails from your Gmail, and stores held resumes on your Drive, all under your own account, never anyone else's.</p>

      {error && <p className="error-banner">{error}</p>}
      {oauthError && <p className="error-banner">{ERROR_MESSAGES[oauthError] || "Couldn't connect. Try again."}</p>}

      {state.connected ? (
        <fieldset>
          <legend>✓ Connected as {state.email}</legend>
          <div className="wizard-actions">
            <button type="button" onClick={connect}>Reconnect a different account</button>
            <button type="button" className="primary" onClick={continueToReview}>Continue</button>
          </div>
        </fieldset>
      ) : (
        <fieldset>
          <legend>Connect your Google account</legend>
          <p className="hint">Clicking below takes you to Google's own sign-in and consent screen, then brings you back here.</p>
          <div className="wizard-actions">
            <button type="button" className="ghost" onClick={() => navigate("/setup/keys")}>Back</button>
            <button type="button" className="primary" onClick={connect}>Connect Google Account</button>
          </div>
        </fieldset>
      )}
    </>
  );
}
