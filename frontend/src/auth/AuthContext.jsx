import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, getToken, setToken } from "../api.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  // null = not yet checked, undefined-ish "unknown" state; false = checked, not logged in;
  // object = checked, logged in. Starts from whatever token localStorage already has (see
  // api.js's own module-level init) so a page refresh doesn't flash a logged-out state.
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      setReady(true);
      return;
    }
    api.me()
      .then(setUser)
      .catch(() => { setToken(""); setUser(null); })
      .finally(() => setReady(true));
  }, []);

  const login = useCallback(async (email, password) => {
    const { access_token } = await api.login(email, password);
    setToken(access_token);
    const me = await api.me();
    setUser(me);
    return me;
  }, []);

  const signup = useCallback(async (email, password, inviteCode) => {
    const { access_token } = await api.signup(email, password, inviteCode);
    setToken(access_token);
    const me = await api.me();
    setUser(me);
    return me;
  }, []);

  const logout = useCallback(() => {
    setToken("");
    setUser(null);
  }, []);

  // Re-fetches /api/me without touching the token -- used after an action that changes
  // something /api/me reports (e.g. Dashboard's run-now bumping manual_runs_used) so the
  // UI reflects it without a full page reload.
  const refreshUser = useCallback(async () => {
    const me = await api.me();
    setUser(me);
    return me;
  }, []);

  const resetPassword = useCallback(async (token, password) => {
    const { access_token } = await api.resetPassword(token, password);
    setToken(access_token);
    const me = await api.me();
    setUser(me);
    return me;
  }, []);

  return (
    <AuthContext.Provider value={{ user, ready, login, signup, logout, resetPassword, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
