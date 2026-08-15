import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";

export default function Signup() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { signup } = useAuth();
  const navigate = useNavigate();

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await signup(email, password);
      navigate("/setup/about");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Create your account</h1>
      {error && <p className="error-banner">{error}</p>}
      <form onSubmit={submit}>
        <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} /></label>
        <div className="wizard-actions">
          <button type="submit" className="primary" disabled={busy}>{busy ? "Creating…" : "Create account"}</button>
        </div>
      </form>
      <p className="hint">Already have an account? <Link to="/login">Log in</Link></p>
    </>
  );
}
