import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.forgotPassword(email);
      setSent(true);
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <>
        <h1>Check your email</h1>
        <p>If an account exists for {email}, a password reset link is on its way. It expires in 30 minutes.</p>
        <p className="hint"><Link to="/login">Back to log in</Link></p>
      </>
    );
  }

  return (
    <>
      <h1>Forgot password</h1>
      <p>Enter your email and we'll send you a link to reset your password.</p>
      <form onSubmit={submit}>
        <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus /></label>
        <div className="wizard-actions">
          <button type="submit" className="primary" disabled={busy}>{busy ? "Sending…" : "Send reset link"}</button>
        </div>
      </form>
      <p className="hint"><Link to="/login">Back to log in</Link></p>
    </>
  );
}
