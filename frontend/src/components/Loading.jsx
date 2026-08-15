// Small spinner + label, used everywhere the app is waiting on a fetch.
// Respects prefers-reduced-motion via index.css's global animation-duration
// override, so it doesn't need its own reduced-motion handling.
export default function Loading({ label = "Loading…" }) {
  return (
    <div className="loading-row">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  );
}
