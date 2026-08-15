// The app's one signature connective device (see app.css's .flow-rail
// block): a dashed wire linking stage nodes. Two uses: real step progress
// (state: "done" | "current" | "upcoming", numbered/checked) for the
// wizard rail, and "static" -- a plain uniform dot with no progress
// meaning -- for illustrating the pipeline's real stages on the landing
// page, where nothing is "in progress" yet.
// step.icon (optional): a small inline SVG rendered inside the dot instead of the
// checkmark/number/blank -- used on the landing page's static process strip; the
// wizard's real-progress rail never sets it, so ✓/number/blank stays the default.
export default function FlowRail({ steps, horizontal = false }) {
  return (
    <ol className={`flow-rail${horizontal ? " horizontal" : ""}`}>
      {steps.map((step) => (
        <li key={step.key} className={`flow-node ${step.state}`}>
          <span className="flow-dot">
            {step.icon || (step.state === "done" ? "✓" : step.state === "static" ? "" : step.index)}
          </span>
          <span className="flow-label">{step.label}</span>
        </li>
      ))}
    </ol>
  );
}
