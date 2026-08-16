import { Link } from "react-router-dom";
import { useCountUp } from "../hooks/useCountUp.js";

// One tile in a stat-strip: icon + eyebrow label + a number that counts up from 0 on
// mount. Shared by Dashboard.jsx and ColdEmail.jsx so both stat strips look and behave
// the same way.
export default function StatItem({ icon, label, value, tone, to }) {
  const display = useCountUp(value);
  const body = (
    <>
      <div className={`stat-item-icon${tone ? ` ${tone}` : ""}`}>{icon}</div>
      <div>
        <div className="eyebrow">{label}</div>
        <div className={`stat-num${tone ? ` ${tone}` : ""}`}>{display}</div>
      </div>
    </>
  );
  return to ? (
    <Link className="stat-item stat-item-link" to={to}>{body}</Link>
  ) : (
    <div className="stat-item">{body}</div>
  );
}
