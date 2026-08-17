import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import PasswordField from "../components/PasswordField.jsx";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(email, password);
      navigate("/dashboard");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Log in</h1>
      {error && <p className="error-banner">{error}</p>}
      <form onSubmit={submit}>
        <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus /></label>
        <PasswordField label="Password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <div className="wizard-actions">
          <button type="submit" className="primary" disabled={busy}>{busy ? "Logging in…" : "Log in"}</button>
        </div>
      </form>
      <p className="hint">No account yet? <Link to="/signup">Sign up</Link></p>
    </>
  );
}
