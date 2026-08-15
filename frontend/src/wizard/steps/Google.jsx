import { useEffect, useRef, useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { api } from "../../api.js";
import Loading from "../../components/Loading.jsx";
import { useApiData } from "../../hooks/useApiData.js";

export default function Google() {
  const { user, refreshDraft } = useOutletContext();
  const { data: state, error, setError, setData: setState } = useApiData(() => api.googleState(user), [user]);
  const [status, setStatus] = useState("");
  const navigate = useNavigate();
  const pollRef = useRef(null);

  useEffect(() => {
    return () => clearTimeout(pollRef.current);
  }, []);

  async function uploadFile(e) {
    e.preventDefault();
    setError("");
    const file = e.target.elements.client_secret.files[0];
    if (!file) return;
    try {
      await api.uploadClientSecret(user, file);
      setState((prev) => ({ ...prev, has_client_secret: true }));
    } catch (err) {
      setError(err.message);
    }
  }

  async function connect() {
    setStatus("Opening your browser to sign in. If no tab opens within a few seconds, check the terminal window running this app for a link to open manually. Finish the consent screen there, then come back to this tab. This will time out after 1 minute if nothing happens, so you can retry.");
    try {
      await api.connectGoogle(user);
      poll();
    } catch (err) {
      setError(err.message);
    }
  }

  function poll() {
    api.googleStatus(user).then(async (data) => {
      if (data.status === "done") {
        setStatus(`Connected as ${data.email}. Continuing…`);
        await refreshDraft();
        navigate(`/setup/${user}/review`);
      } else if (data.status === "error") {
        setStatus(`${data.error} Click "Connect Google Account" to try again.`);
      } else {
        pollRef.current = setTimeout(poll, 2000);
      }
    });
  }

  if (!state) return <Loading />;

  return (
    <>
      <h1>Connect your Google account</h1>
      <p className="lede">The pipeline reads and writes a Google Sheet, sends application emails from your Gmail, and stores held resumes on your Drive, all under your own account, never anyone else's.</p>

      <div className="card">
        <ol className="steps-list" style={{ marginTop: 0 }}>
          <li>Go to <a href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noopener">Google Cloud Console → New Project</a> and create one (any name).</li>
          <li>
            With that project selected, enable these three APIs (click each, then "Enable"):
            <ul>
              <li><a href="https://console.cloud.google.com/apis/library/sheets.googleapis.com" target="_blank" rel="noopener">Google Sheets API</a></li>
              <li><a href="https://console.cloud.google.com/apis/library/gmail.googleapis.com" target="_blank" rel="noopener">Gmail API</a></li>
              <li><a href="https://console.cloud.google.com/apis/library/drive.googleapis.com" target="_blank" rel="noopener">Google Drive API</a></li>
            </ul>
          </li>
          <li>Go to <a href="https://console.cloud.google.com/apis/credentials/consent" target="_blank" rel="noopener">OAuth consent screen</a>, choose "External", fill in the required fields, and under "Test users" click "Add users" and enter the exact Google account email you'll use to click "Connect Google Account" below. Without this step, Google will reject the connection with an "access blocked" error, since the app stays unpublished/"Testing" the whole time you use this pipeline.</li>
          <li>Go to <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener">Credentials → Create Credentials → OAuth client ID</a>, application type <strong>Desktop app</strong>, then click "Download JSON" on the client you created.</li>
          <li>Upload that downloaded file below.</li>
        </ol>
      </div>

      {error && <p className="error-banner">{error}</p>}

      <fieldset>
        <legend>Upload client_secret.json</legend>
        <form onSubmit={uploadFile}>
          <label>File<input type="file" name="client_secret" accept=".json" required /></label>
          <div className="wizard-actions"><button type="submit">Upload</button></div>
        </form>
      </fieldset>

      {state.has_client_secret && (
        <fieldset>
          <legend>✓ File uploaded: connect your account</legend>
          <div className="wizard-actions"><button type="button" className="primary" onClick={connect}>Connect Google Account</button></div>
          {status && <p className="hint">{status}</p>}
        </fieldset>
      )}

      <div className="wizard-actions">
        <button type="button" className="ghost" onClick={() => navigate(`/setup/${user}/keys`)}>Back</button>
      </div>
    </>
  );
}
