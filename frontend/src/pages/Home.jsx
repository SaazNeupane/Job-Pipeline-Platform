import { Link } from "react-router-dom";
import FlowRail from "../components/FlowRail.jsx";
import { useAuth } from "../auth/AuthContext.jsx";

const PROCESS = [
  { key: "search", label: "Search real postings" },
  { key: "filter", label: "Filter to real fits" },
  { key: "swipe", label: "Swipe to pick favorites" },
  { key: "tailor", label: "Tailor resume + letter" },
  { key: "apply", label: "Apply yourself" },
];

export default function Home() {
  const { user, ready } = useAuth();

  return (
    <>
      <div className="hero">
        <p className="eyebrow">Runs itself, every day</p>
        <h1>Your job search, running itself</h1>
        <p className="lede">
          It searches real postings every day and filters them down to ones worth your time. You swipe
          through to pick the jobs you actually want, and it tailors a resume and cover letter for each
          one you like. You apply yourself, from your own dashboard. Everything runs under your own
          accounts, and it never invents anything about you.
        </p>
        <div className="hero-actions">
          {ready && user ? (
            <Link className="button primary" to="/dashboard">Go to your dashboard</Link>
          ) : (
            <Link className="button primary" to="/signup">Get started</Link>
          )}
          <Link className="button secondary" to="/guide">Read the guide first</Link>
        </div>
      </div>

      <div className="process-strip">
        <FlowRail horizontal steps={PROCESS.map((p) => ({ ...p, state: "static" }))} />
      </div>
    </>
  );
}
