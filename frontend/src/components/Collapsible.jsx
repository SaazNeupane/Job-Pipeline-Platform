import { useState } from "react";

// Generic collapsible section wrapper for a plain <h2> heading (e.g. "Recent
// runs") -- LaneSection.jsx is the equivalent for per-lane subsections with
// their own dot/count styling.
export default function Collapsible({ title, defaultCollapsed = false, children }) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  return (
    <div className="collapsible">
      <button type="button" className="collapsible-head" onClick={() => setCollapsed(!collapsed)}>
        <h2>{title}</h2>
        <span className={`lane-chevron${collapsed ? " collapsed" : ""}`}>▾</span>
      </button>
      <div className={`collapsible-body${collapsed ? "" : " open"}`}>
        <div className="collapsible-body-inner">{children}</div>
      </div>
    </div>
  );
}
