// Thin fetch wrapper for the hosted FastAPI backend (backend/app/main.py +
// app/routers/*). Every helper resolves to the parsed JSON body on success and throws an
// Error whose message is the backend's own {"detail": "..."} (or legacy {"error": "..."})
// text on failure, so callers can just `catch (e) { setError(e.message) }`.
//
// Every failure ALSO fires a global toast (see toast.js/ToastHost.jsx) -- components still
// get the thrown Error for their own inline error-banner/field-level context, but a toast is
// always visible regardless of how far down the page that banner would render.
//
// Auth: the backend is multi-tenant now -- every route (except signup/login/lane-presets)
// requires a JWT in an Authorization header instead of a `<user>` URL segment. The token is
// held here in memory + localStorage (see auth/AuthContext.jsx, which owns the React-visible
// login/logout state and calls setToken/clearToken below to keep this module in sync).

import { showToast } from "./toast.js";

// Empty string, not a localhost fallback: in production this frontend is served by the
// same FastAPI process it talks to (backend/app/main.py's StaticFiles mount), so a relative
// path already resolves correctly. Local dev overrides via frontend/.env (gitignored, not
// present in a fresh clone or a Render build), which is the only place localhost:8000
// belongs.
export const API_BASE = import.meta.env.VITE_API_BASE || "";

const TOKEN_STORAGE_KEY = "job_pipeline_token";
let token = localStorage.getItem(TOKEN_STORAGE_KEY) || "";

export function setToken(next) {
  token = next || "";
  if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
  else localStorage.removeItem(TOKEN_STORAGE_KEY);
}

export function getToken() {
  return token;
}

// Fallback wording for failures that never reached a route handler (network drop, backend
// down, an unhandled 500) -- these never carry a hand-written detail string, so body.detail
// is empty and we'd otherwise show "Request failed (500)" verbatim.
function fallbackMessage(status) {
  if (status === 0) return "Can't reach the server. Check your connection and try again.";
  if (status >= 500) return "Something went wrong on our end. Try again in a moment.";
  return "Something went wrong. Try again.";
}

async function handle(resp) {
  let body = null;
  try {
    body = await resp.json();
  } catch {
    // no body
  }
  if (!resp.ok) {
    const message = (body && (body.error || body.detail)) || fallbackMessage(resp.status);
    showToast(message);
    const err = new Error(message);
    err.code = body && body.code;
    err.status = resp.status;
    throw err;
  }
  return body;
}

function authHeaders(extra) {
  return { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...extra };
}

function get(path) {
  return fetch(`${API_BASE}${path}`, { headers: authHeaders() }).then(handle);
}

function post(path, body) {
  return fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: authHeaders(body ? { "Content-Type": "application/json" } : undefined),
    body: body ? JSON.stringify(body) : undefined,
  }).then(handle);
}

function patch(path, body) {
  return fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  }).then(handle);
}

async function getBlob(path) {
  const resp = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  if (!resp.ok) return handle(resp);
  return resp.blob();
}

function upload(path, file, fieldName, extraFields) {
  const form = new FormData();
  form.append(fieldName, file);
  for (const [k, v] of Object.entries(extraFields || {})) form.append(k, v);
  return fetch(`${API_BASE}${path}`, { method: "POST", headers: authHeaders(), body: form }).then(handle);
}

export const api = {
  // -- auth (app account, not Google) --
  signup: (email, password, inviteCode) => post("/api/auth/signup", { email, password, invite_code: inviteCode }),
  login: (email, password) => post("/api/auth/login", { email, password }),
  me: () => get("/api/me"),
  resendVerification: () => post("/api/auth/resend-verification"),

  // -- google connect (Sheets/Gmail/Drive scopes) --
  googleOAuthStart: () => get("/api/oauth/google/start"),
  googleOAuthStatus: () => get("/api/oauth/google/status"),

  // -- wizard --
  lanePresets: () => get("/api/wizard/lane-presets"),
  wizardDraft: () => get("/api/wizard/draft"),
  patchDraft: (body) => patch("/api/wizard/draft", body),
  geocode: (address) => post("/api/wizard/geocode", { address }),
  submitLanes: (body) => post("/api/wizard/lanes", body),
  importResume: (file, geminiApiKey) => upload("/api/wizard/resume/import", file, "resume_pdf", { gemini_api_key: geminiApiKey }),
  review: () => get("/api/wizard/review"),
  previewResume: (lane) => getBlob(`/api/wizard/resume/preview${lane ? `?lane=${encodeURIComponent(lane)}` : ""}`),
  finalize: () => post("/api/wizard/finalize"),

  // -- swipe queue --
  swipeQueue: () => get("/api/swipe/queue"),
  swipeLike: (postingKey) => post(`/api/swipe/${encodeURIComponent(postingKey)}/like`),
  swipeReject: (postingKey) => post(`/api/swipe/${encodeURIComponent(postingKey)}/reject`),
  addManualPosting: (lane, text, url) => post("/api/swipe/manual", { lane, text, url }),
  cleanupQueue: (minScore) => post("/api/swipe/clean-up", { min_score: minScore }),

  // -- dashboard --
  dashboard: () => get("/api/dashboard"),
  promote: (postingKey) => post(`/api/dashboard/promote/${encodeURIComponent(postingKey)}`),
  dismiss: (postingKey) => post(`/api/dashboard/dismiss/${encodeURIComponent(postingKey)}`),
  retry: (postingKey) => post(`/api/dashboard/retry/${encodeURIComponent(postingKey)}`),
  dismissBulk: (postingKeys) => post("/api/dashboard/dismiss-bulk", { posting_keys: postingKeys }),
  runNow: (overrides) => post("/api/run-now", overrides || {}),
};
