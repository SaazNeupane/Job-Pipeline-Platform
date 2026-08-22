import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function GoogleReconnectBanner({ onReconnected }) {
  const [status, setStatus] = useState("idle"); // idle | pending | error

  useEffect(() => {
    if (status !== "pending") return;
    const id = setInterval(async () => {
      const res = await api.googleOAuthStatus();
      if (res.connected) {
        clearInterval(id);
        onReconnected();
      }
    }, 1500);
    return () => clearInterval(id);
  }, [status, onReconnected]);

  async function reconnect() {
    setStatus("pending");
    try {
      const { authorization_url } = await api.googleOAuthStart();
      window.location.href = authorization_url;
    } catch {
      setStatus("error");
    }
  }

  return (
    <div className="error-banner">
      <p>Your Google connection expired -- Sheets/Gmail/Drive calls can't go through until you reconnect.</p>
      <button type="button" onClick={reconnect}>Reconnect Google</button>
      {status === "error" && <p>Reconnect didn't finish. Try again.</p>}
    </div>
  );
}
