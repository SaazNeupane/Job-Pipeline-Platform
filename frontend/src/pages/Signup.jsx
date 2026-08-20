import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import PasswordField from "../components/PasswordField.jsx";

export default function Signup() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { user, signup } = useAuth();
  const navigate = useNavigate();

  if (user) return <Navigate to="/dashboard" replace />;

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await signup(email, password, inviteCode);
      navigate("/setup/about");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-form">
      <h1>Create your account</h1>
      {error && <p className="error-banner">{error}</p>}
      <form onSubmit={submit}>
        <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus /></label>
        <PasswordField label="Password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
        <label>Invite code<input type="text" value={inviteCode} onChange={(e) => setInviteCode(e.target.value)} required /></label>
        <div className="wizard-actions">
          <button type="submit" className="primary" disabled={busy}>{busy ? "Creating…" : "Create account"}</button>
        </div>
      </form>
      <p className="hint">
        By creating an account you agree to the <Link to="/terms">Terms</Link> and{" "}
        <Link to="/privacy">Privacy Policy</Link>.
      </p>
      <p className="hint">Already have an account? <Link to="/login">Log in</Link></p>
    </div>
  );
}
