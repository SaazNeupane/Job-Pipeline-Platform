import { Navigate, Outlet, useLocation, useParams } from "react-router-dom";
import { api } from "../api.js";
import FlowRail from "../components/FlowRail.jsx";
import Loading from "../components/Loading.jsx";
import { useApiData } from "../hooks/useApiData.js";

const STEPS = [
  ["about", "About You"],
  ["lanes", "Job Types"],
  ["resume", "Resume"],
  ["keys", "API Keys"],
  ["google", "Connect Google"],
  ["review", "Review"],
  ["push", "Push to GitHub"],
  ["done", "Done"],
];

export default function WizardLayout() {
  const { user } = useParams();
  const location = useLocation();
  const { data: draft, error, setError, reload: refreshDraft } = useApiData(() => api.wizardDraft(user), [user]);

  if (!user) return <Navigate to="/setup/start" replace />;

  const currentKey = location.pathname.split("/").filter(Boolean).pop();
  const currentIndex = STEPS.findIndex(([key]) => key === currentKey);
  const steps = STEPS.map(([key, label], i) => ({
    key,
    label,
    index: i + 1,
    state: i < currentIndex ? "done" : i === currentIndex ? "current" : "upcoming",
  }));

  return (
    <div className="wizard-shell">
      <div className="wizard-rail">
        <FlowRail steps={steps} />
      </div>
      <div>
        {error && <p className="error-banner">{error}</p>}
        {draft ? (
          <Outlet context={{ user, draft, refreshDraft, setError }} />
        ) : (
          <Loading />
        )}
      </div>
    </div>
  );
}
