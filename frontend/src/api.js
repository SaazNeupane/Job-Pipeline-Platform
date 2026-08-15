// Thin fetch wrapper for the Flask JSON API (webapp/app.py). Every helper
// resolves to the parsed JSON body on success and throws an Error whose
// message is the backend's own {"error": "..."} text on failure, so
// callers can just `catch (e) { setError(e.message) }` without re-deriving
// what went wrong.
//
// Every failure ALSO fires a global toast (see toast.js/ToastHost.jsx) --
// components still get the thrown Error for their own inline
// error-banner/field-level context, but a toast is always visible
// regardless of how far down the page that banner would render, which an
// inline banner alone can't guarantee on a long form.

import { showToast } from "./toast.js";

async function handle(resp) {
  let body = null;
  try {
    body = await resp.json();
  } catch {
    // no body (e.g. a 503 plain-text "frontend not built" response)
  }
  if (!resp.ok) {
    const message = (body && body.error) || `Request failed (${resp.status})`;
    showToast(message);
    const err = new Error(message);
    err.code = body && body.code;
    throw err;
  }
  return body;
}

function get(path) {
  return fetch(path).then(handle);
}

function del(path) {
  return fetch(path, { method: "DELETE" }).then(handle);
}

function post(path, body) {
  return fetch(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  }).then(handle);
}

function patch(path, body) {
  return fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(handle);
}

function upload(path, file, fieldName, extraFields) {
  const form = new FormData();
  form.append(fieldName, file);
  for (const [k, v] of Object.entries(extraFields || {})) form.append(k, v);
  return fetch(path, { method: "POST", body: form }).then(handle);
}

export const api = {
  profiles: () => get("/api/profiles"),
  deleteProfile: (user) => del(`/api/profiles/${user}`),
  lanePresets: () => get("/api/lane-presets"),

  wizardStart: (user, confirmOverwrite) => post("/api/wizard/start", { user, confirm_overwrite: confirmOverwrite }),
  wizardDraft: (user) => get(`/api/wizard/${user}/draft`),
  patchDraft: (user, body) => patch(`/api/wizard/${user}/draft`, body),
  submitLanes: (user, body) => post(`/api/wizard/${user}/lanes`, body),
  importResume: (user, file, geminiApiKey) => upload(`/api/wizard/${user}/resume/import`, file, "resume_pdf", { gemini_api_key: geminiApiKey }),
  googleState: (user) => get(`/api/wizard/${user}/google`),
  uploadClientSecret: (user, file) => upload(`/api/wizard/${user}/google/client-secret`, file, "client_secret"),
  connectGoogle: (user) => post(`/api/wizard/${user}/google/connect`),
  googleStatus: (user) => get(`/api/wizard/${user}/google/status`),
  review: (user) => get(`/api/wizard/${user}/review`),
  finalize: (user) => post(`/api/wizard/${user}/finalize`),
  pushCommands: (user) => get(`/api/wizard/${user}/push`),
  push: (user, repo) => post(`/api/wizard/${user}/push`, { repo }),

  swipeQueue: (user) => get(`/api/swipe/${user}/queue`),
  swipeLike: (user, postingKey) => post(`/api/swipe/${user}/${encodeURIComponent(postingKey)}/like`),
  swipeReject: (user, postingKey) => post(`/api/swipe/${user}/${encodeURIComponent(postingKey)}/reject`),

  dashboard: (user) => get(`/api/dashboard/${user}`),
  dashboardGoogleReconnect: (user) => post(`/api/dashboard/${user}/google/reconnect`),
  dashboardGoogleReconnectStatus: (user) => get(`/api/dashboard/${user}/google/reconnect/status`),
  promote: (user, postingKey) => post(`/api/dashboard/${user}/promote/${encodeURIComponent(postingKey)}`),
  dismiss: (user, postingKey) => post(`/api/dashboard/${user}/dismiss/${encodeURIComponent(postingKey)}`),
  retry: (user, postingKey) => post(`/api/dashboard/${user}/retry/${encodeURIComponent(postingKey)}`),
  dismissBulk: (user, postingKeys) => post(`/api/dashboard/${user}/dismiss-bulk`, { posting_keys: postingKeys }),
  setRepo: (user, repo) => post(`/api/dashboard/${user}/set-repo`, { repo }),
  runNow: (user, options) => post(`/api/dashboard/${user}/run-now`, options),

  shutdown: () => post("/api/shutdown"),
};
