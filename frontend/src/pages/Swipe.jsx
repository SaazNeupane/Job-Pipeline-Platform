import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import Loading from "../components/Loading.jsx";
import { useApiData } from "../hooks/useApiData.js";
import { sourceLabel } from "../sourceLabels.js";

function money(min, max) {
  const fmt = (n) => `$${Math.round(Number(n)).toLocaleString()}`;
  if (min && max) return `${fmt(min)}-${fmt(max)}`;
  if (min) return `${fmt(min)}+`;
  if (max) return `Up to ${fmt(max)}`;
  return "";
}

function SwipeCard({ row, laneLabels, exiting, entering }) {
  const terms = (row.matched_terms || "").split(",").filter(Boolean);
  const salary = money(row.salary_min, row.salary_max);
  const stateClass = exiting ? ` exit-${exiting}` : entering ? " entering" : "";
  return (
    <div className={`swipe-card${stateClass}`}>
      <div className="swipe-card-lane">{laneLabels[row.lane] || row.lane.replace(/_/g, " ")}</div>
      <h2>{row.role}</h2>
      <div className="swipe-card-company">{row.company}</div>
      <div className="posting-meta">
        {row.location && <span className="badge">{row.location}</span>}
        {row.remote_type && <span className="badge">{row.remote_type}</span>}
        {row.employment_type && <span className="badge">{row.employment_type}</span>}
        {row.source && <span className="badge">{sourceLabel(row.source)}</span>}
      </div>
      <div className="swipe-card-facts">
        {row.posted_date && <div><span className="eyebrow">Posted</span>{row.posted_date.slice(0, 10)}</div>}
        {salary && <div><span className="eyebrow">Salary</span>{salary}</div>}
        {row.required_years && <div><span className="eyebrow">Experience</span>{row.required_years}+ years</div>}
      </div>
      {terms.length > 0 && (
        <div className="swipe-card-terms">
          {terms.map((t) => <span key={t} className="badge amber">{t}</span>)}
        </div>
      )}
      {row.description_text && (
        <p className="swipe-card-desc">{row.description_text.slice(0, 600)}{row.description_text.length > 600 ? "…" : ""}</p>
      )}
      {row.application_url && (
        <a className="button secondary" href={row.application_url} target="_blank" rel="noopener">View full posting</a>
      )}
    </div>
  );
}

// Bare header/company only -- the sliver of the next card peeking out
// behind the current one, just enough to read as "there's more in the
// deck" without duplicating the full card's cost or detail.
function SwipeCardPeek({ row, laneLabels }) {
  return (
    <div className="swipe-card swipe-card-peek">
      <div className="swipe-card-lane">{laneLabels[row.lane] || row.lane.replace(/_/g, " ")}</div>
      <h2>{row.role}</h2>
      <div className="swipe-card-company">{row.company}</div>
    </div>
  );
}

const EXIT_ANIMATION_MS = 260;

export default function Swipe() {
  const { data, error, errorCode, setError, setData } = useApiData(() => api.swipeQueue(), []);
  const queue = data?.queue;
  const laneLabels = data?.lane_labels || {};
  const [busy, setBusy] = useState(false);
  const [exiting, setExiting] = useState(null); // null | "like" | "reject"
  const [entering, setEntering] = useState(false);
  const [lastLiked, setLastLiked] = useState(null);

  const current = queue && queue.length ? queue[0] : null;
  const next = queue && queue.length > 1 ? queue[1] : null;

  // The API call itself no longer gates the swipe animation -- the backend
  // now records a like/reject and (for likes) kicks off resume/cover-letter
  // generation in a background thread rather than doing that work inline,
  // so the request resolves fast, but the deck advances purely on its own
  // animation timer regardless of network latency. This is what actually
  // fixes the "stuck on Working…" lag: the click was never really waiting
  // on the animation, it was waiting on the slow request underneath it.
  function decide(direction) {
    if (!current || busy) return;
    setBusy(true);
    setError("");
    setExiting(direction);

    const request = direction === "like" ? api.swipeLike(current.posting_key) : api.swipeReject(current.posting_key);
    request
      .then((result) => { if (direction === "like") setLastLiked(result.row); })
      .catch((e) => setError(e.message));

    setTimeout(() => {
      setData((prev) => ({ ...prev, queue: prev.queue.slice(1) }));
      setExiting(null);
      // Next card starts painted in the "peek" pose (small/faded/behind)
      // then, one frame later, the "entering" class is dropped -- the
      // existing .swipe-card transition animates it from that pose up to
      // full size/opacity, so the next card visibly grows from the back
      // of the deck into the front slot instead of popping in place.
      setEntering(true);
      requestAnimationFrame(() => requestAnimationFrame(() => setEntering(false)));
      setBusy(false);
    }, EXIT_ANIMATION_MS);
  }
  const like = () => decide("like");
  const reject = () => decide("reject");

  useEffect(() => {
    function onKey(e) {
      if (busy || !current) return;
      if (e.key === "ArrowRight") like();
      if (e.key === "ArrowLeft") reject();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (errorCode === "profile_missing") return <p className="error-banner">{error} <Link to="/setup/about">Finish setup</Link></p>;
  if (error && !data) return <p className="error-banner">{error}</p>;
  if (!data) return <Loading />;

  return (
    <>
      <div className="dash-head">
        <div>
          <h1>Your swipe queue</h1>
          <p className="lede">New postings land here. Swipe right to tailor a resume and cover letter you can apply with by hand, or left to set one aside for good.</p>
        </div>
        <Link className="button secondary" to="/dashboard">Dashboard</Link>
      </div>

      {error && <div className="banner">{error}</div>}
      {lastLiked && (
        <div className="banner info">
          Tailoring resume/cover letter for <strong>{lastLiked.company}</strong> in the background.
          {" "}Check your <Link to="/dashboard">dashboard</Link> in a moment.
        </div>
      )}

      <div className="swipe-stage">
        {current ? (
          <>
            <div className="swipe-deck">
              {next && <SwipeCardPeek row={next} laneLabels={laneLabels} />}
              <SwipeCard row={current} laneLabels={laneLabels} exiting={exiting} entering={entering} />
            </div>
            <div className="swipe-actions">
              <button type="button" className="danger swipe-btn" onClick={reject} disabled={busy}>← Skip</button>
              <button type="button" className="primary swipe-btn" onClick={like} disabled={busy}>{busy ? "Working…" : "Like →"}</button>
            </div>
            <p className="hint swipe-hint">{queue.length - 1} more after this · arrow keys work too</p>
          </>
        ) : (
          <div className="empty-state">Nothing waiting for a swipe right now. Check back after the next run.</div>
        )}
      </div>
    </>
  );
}
