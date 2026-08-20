import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import PasswordField from "../components/PasswordField.jsx";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { resetPassword } = useAuth();
  const navigate = useNavigate();

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await resetPassword(token, password);
      navigate("/dashboard");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <div className="auth-form">
        <h1>Reset password</h1>
        <p className="error-banner">This link is missing its token. Request a new one.</p>
        <p className="hint"><Link to="/forgot-password">Request a new link</Link></p>
      </div>
    );
  }

  return (
    <div className="auth-form">
      <h1>Choose a new password</h1>
      {error && <p className="error-banner">{error}</p>}
      <form onSubmit={submit}>
        <PasswordField label="New password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
        <div className="wizard-actions">
          <button type="submit" className="primary" disabled={busy}>{busy ? "Saving…" : "Save new password"}</button>
        </div>
      </form>
    </div>
  );
}
