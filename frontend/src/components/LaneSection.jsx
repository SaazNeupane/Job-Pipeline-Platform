// No collapse/expand -- that was covering for the dashboard rendering every
// section on one long page; now that pending/applied/runs are already split
// into their own tabs, a lane heading doesn't need to hide its own rows too.
export default function LaneSection({ section, tone, children }) {
  return (
    <div className={`lane-section${tone === "pine" ? " pine-dot" : ""}`}>
      <div className="lane-section-head">
        <span className="lane-dot" />
        <h3>{section.label}</h3>
        <span className="lane-count">{section.rows.length}</span>
      </div>
      {children}
    </div>
  );
}
