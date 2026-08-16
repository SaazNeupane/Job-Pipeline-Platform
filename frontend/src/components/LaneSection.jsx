import { useState } from "react";

// Auto-collapsed past this count so a lane with dozens of rows doesn't
// dominate the page by default -- still one click away, never hidden data.
const AUTO_COLLAPSE_THRESHOLD = 5;

export default function LaneSection({ section, tone, children }) {
  const [collapsed, setCollapsed] = useState(section.rows.length > AUTO_COLLAPSE_THRESHOLD);

  return (
    <div className={`lane-section${tone === "pine" ? " pine-dot" : ""}`}>
      <button type="button" className="lane-section-head lane-section-toggle" onClick={() => setCollapsed(!collapsed)}>
        <span className="lane-dot" />
        <h3>{section.label}</h3>
        <span className="lane-count">{section.rows.length}</span>
        <span className={`lane-chevron${collapsed ? " collapsed" : ""}`}>▾</span>
      </button>
      <div className={`lane-section-body${collapsed ? "" : " open"}`}>
        <div className="lane-section-body-inner">{children}</div>
      </div>
    </div>
  );
}
