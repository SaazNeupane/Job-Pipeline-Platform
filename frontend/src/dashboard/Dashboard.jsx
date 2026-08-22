import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useAuth } from "../auth/AuthContext.jsx";
import ConfirmDialog from "../components/ConfirmDialog.jsx";
import Loading from "../components/Loading.jsx";
import LaneSection from "../components/LaneSection.jsx";
import { CheckCircleIcon, InboxIcon, MailIcon, RunsIcon } from "../components/icons.jsx";
import StatItem from "../components/StatItem.jsx";
import { useApiData } from "../hooks/useApiData.js";
import { sourceLabel } from "../sourceLabels.js";
import { showToast } from "../toast.js";
import AddManualPosting from "./AddManualPosting.jsx";
import GoogleReconnectBanner from "./GoogleReconnectBanner.jsx";
import PostingCard from "./PostingCard.jsx";

export default function Dashboard() {
  const { user, refreshUser } = useAuth();
  const { data, error, errorCode, setError, reload: load } = useApiData(() => api.dashboard(), []);
  const [selected, setSelected] = useState(new Set());
  const [openDetail, setOpenDetail] = useState(null);
  const [laneFilter, setLaneFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [busyRows, setBusyRows] = useState({}); // posting_key -> "promote" | "dismiss"
  const [bulkBusy, setBulkBusy] = useState(false);
  const [confirmTarget, setConfirmTarget] = useState(null); // { type: "single", key } | { type: "bulk" }
  const [runState, setRunState] = useState("idle"); // idle | pending | started
  const [runLane, setRunLane] = useState("all");
  const [runMaxAgeDays, setRunMaxAgeDays] = useState("");
  const [runColdEmailOnly, setRunColdEmailOnly] = useState(false);
  const [tab, setTab] = useState("review"); // overview | review | applied | runs
  const quotaExhausted = !!user && user.manual_runs_used >= user.manual_runs_limit;

  useEffect(() => {
    // Picks up plan/quota changes made elsewhere (e.g. an admin plan flip) without a
    // re-login. Compares against the plan already in context (set at login/last refresh)
    // rather than a ref, since the point is exactly "did it change since last time we knew."
    const priorPlan = user?.plan;
    refreshUser().then((me) => {
      if (priorPlan && priorPlan !== "paid" && me.plan === "paid") {
        showToast("You're on Pro now.", "pine");
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function runNow() {
    setRunState("pending");
    try {
      await api.runNow({
        lane_filter: runLane === "all" ? null : runLane,
        max_age_days: runMaxAgeDays ? Number(runMaxAgeDays) : null,
        cold_email_only: runColdEmailOnly,
      });
      setRunState("started");
      refreshUser(); // picks up the just-incremented manual_runs_used for the counter below
    } catch {
      // api.js's handle() already fired a toast with the real reason (e.g. "Already
      // ran today. Try again tomorrow.") -- just reset the button, nothing else to show.
      setRunState("idle");
    }
  }

  // A right-swipe writes its pending_approval row immediately
  // (reason_held="generating") and fills in the resume/cover letter a few
  // seconds later in a background thread (see swipe_actions.py). Poll while
  // any row is still in that state so the "Generating..." badge clears on
  // its own instead of needing a manual page reload.
  const stillGenerating = data?.pending.some((r) => r.reason_held === "generating");
  useEffect(() => {
    if (!stillGenerating) return;
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [stillGenerating, load]);

  const matchesFilters = (row) => {
    if (laneFilter !== "all" && row.lane !== laneFilter) return false;
    if (sourceFilter !== "all" && row.source !== sourceFilter) return false;
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      const haystack = `${row.company} ${row.role} ${row.location}`.toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  };

  const filteredPendingByLane = useMemo(() => {
    if (!data) return [];
    return data.pending_by_lane
      .map((section) => ({ ...section, rows: section.rows.filter(matchesFilters) }))
      .filter((section) => section.rows.length);
  }, [data, laneFilter, sourceFilter, search]);

  const filteredAppliedByLane = useMemo(() => {
    if (!data) return [];
    return data.applied_by_lane
      .map((section) => ({ ...section, rows: section.rows.filter(matchesFilters) }))
      .filter((section) => section.rows.length);
  }, [data, laneFilter, sourceFilter, search]);

  const sources = useMemo(() => {
    if (!data) return [];
    return [...new Set([...data.pending, ...data.applied].map((r) => r.source).filter(Boolean))];
  }, [data]);

  function toggleSelect(key, checked) {
    setSelected((prev) => {
      const next = new Set(prev);
      checked ? next.add(key) : next.delete(key);
      return next;
    });
  }

  async function promote(key) {
    setBusyRows((prev) => ({ ...prev, [key]: "promote" }));
    try {
      await api.promote(key);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyRows((prev) => { const next = { ...prev }; delete next[key]; return next; });
    }
  }
  async function retry(key) {
    setBusyRows((prev) => ({ ...prev, [key]: "retry" }));
    try {
      await api.retry(key);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyRows((prev) => { const next = { ...prev }; delete next[key]; return next; });
    }
  }
  async function setOutcome(key, outcome) {
    setBusyRows((prev) => ({ ...prev, [key]: "outcome" }));
    try {
      await api.setOutcome(key, outcome);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyRows((prev) => { const next = { ...prev }; delete next[key]; return next; });
    }
  }
  async function doDismiss(key) {
    setBusyRows((prev) => ({ ...prev, [key]: "dismiss" }));
    try {
      await api.dismiss(key);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyRows((prev) => { const next = { ...prev }; delete next[key]; return next; });
    }
  }
  async function doDismissSelected() {
    if (!selected.size || bulkBusy) return;
    setBulkBusy(true);
    try {
      await api.dismissBulk([...selected]);
      setSelected(new Set());
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBulkBusy(false);
    }
  }

  function confirmDismiss() {
    if (!confirmTarget) return;
    if (confirmTarget.type === "single") doDismiss(confirmTarget.key);
    else doDismissSelected();
    setConfirmTarget(null);
  }

  if (errorCode === "google_reauth_required") return <GoogleReconnectBanner onReconnected={load} />;
  if (errorCode === "profile_missing") return <p className="error-banner">{error} <Link to="/setup/about">Finish setup</Link></p>;
  if (error) return <p className="error-banner">{error}</p>;
  if (!data) return <Loading />;

  return (
    <>
      <div className="dash-head">
        <div>
          <h1>Your dashboard</h1>
          <p className="lede">Everything here lives in your account's own database, and mirrors out to your Google Sheet as a readable backup.</p>
        </div>
        <div className="dash-head-links">
          <Link className="button secondary" to="/setup/about">Edit setup</Link>
          <Link className="button secondary" to="/cold-email">Cold email</Link>
          <Link className="button primary" to="/swipe">
            Swipe queue{data.swipe_queue_count ? ` (${data.swipe_queue_count})` : ""}
          </Link>
        </div>
      </div>

      {(data.keys_missing?.adzuna || data.keys_missing?.gemini) && (
        <div className="banner">
          <p>
            {data.keys_missing.adzuna && data.keys_missing.gemini
              ? "Add your Adzuna and Gemini keys to start finding and tailoring jobs."
              : data.keys_missing.adzuna
              ? "Add your Adzuna key to start finding jobs."
              : "Add your Gemini key so cover letters and resume tailoring can run."}{" "}
            <Link to="/setup/keys">Add keys</Link>
          </p>
        </div>
      )}

      <div className="section-tabs">
        <button type="button" className={`section-tab${tab === "overview" ? " active" : ""}`} onClick={() => setTab("overview")}>Overview</button>
        <button type="button" className={`section-tab${tab === "review" ? " active" : ""}`} onClick={() => setTab("review")}>
          Needs review{data.pending.length ? ` (${data.pending.length})` : ""}
        </button>
        <button type="button" className={`section-tab${tab === "applied" ? " active" : ""}`} onClick={() => setTab("applied")}>
          Applied{data.applied.length ? ` (${data.applied.length})` : ""}
        </button>
        <button type="button" className={`section-tab${tab === "runs" ? " active" : ""}`} onClick={() => setTab("runs")}>Runs</button>
      </div>

      {tab === "overview" && (
        <>
          <div className="run-bar">
            <div>
              {data.apply_daily_cap != null && (
                <p className="lede" style={{ marginBottom: runState === "started" ? "0.3rem" : 0 }}>
                  Up to {data.apply_daily_cap} new postings per lane get queued for you to swipe on each day. Nothing gets applied to without you.
                </p>
              )}
              {runState === "started" && <p className="hint" style={{ margin: 0 }}>Run started. Check back in a few minutes.</p>}
              {user && (
                <p className="hint run-quota-line" style={{ margin: 0 }}>
                  <span className={`badge${user.plan === "paid" ? " pine" : ""}`}>{user.plan === "paid" ? "Pro" : "Free"}</span>
                  {user.manual_runs_used}/{user.manual_runs_limit} manual runs used this month
                  {user.plan === "free" && quotaExhausted && " -- upgrade for more."}
                </p>
              )}
            </div>
            <button
              type="button"
              className="primary"
              onClick={runNow}
              disabled={runState === "pending" || runState === "started" || quotaExhausted}
              title={quotaExhausted ? "Manual run limit reached for this month" : undefined}
            >
              {runState === "pending" ? "Starting…" : runState === "started" ? "Run started" : quotaExhausted ? "Limit reached" : "Run now"}
            </button>

            <details className="advanced" style={{ flexBasis: "100%" }}>
              <summary>Advanced: run just one lane, widen the date window, or cold email only</summary>
              <div className="run-override">
                <label>
                  Lane
                  <select value={runLane} onChange={(e) => setRunLane(e.target.value)} disabled={runColdEmailOnly}>
                    <option value="all">All lanes</option>
                    {data.lane_names.map((n) => (
                      <option key={n} value={n}>{data.lane_labels[n] || n.replace(/_/g, " ")}</option>
                    ))}
                  </select>
                </label>
                <div className="run-override-days">
                  <label>
                    Recency window
                    <input
                      type="number" min="1" placeholder="default"
                      value={runMaxAgeDays} onChange={(e) => setRunMaxAgeDays(e.target.value)}
                    />
                  </label>
                  <span>days</span>
                </div>
                <label className="checkbox-row">
                  <input
                    type="checkbox" checked={runColdEmailOnly}
                    onChange={(e) => setRunColdEmailOnly(e.target.checked)}
                  />
                  Cold email only, skip job search
                </label>
                <p className="hint">
                  A scoped run like this doesn't count against today's one-run limit. Only a full
                  default run does.
                </p>
              </div>
            </details>
          </div>

          <div className="stat-strip">
            <StatItem icon={<InboxIcon />} label="Needs review" value={data.pending.length} tone="signal" />
            <StatItem icon={<CheckCircleIcon />} label="Applied" value={data.applied.length} tone="pine" />
            <StatItem
              icon={<CheckCircleIcon />}
              label="Interview rate"
              value={
                data.outcome_stats?.overall?.applied
                  ? `${Math.round((data.outcome_stats.overall.interview / data.outcome_stats.overall.applied) * 100)}%`
                  : "—"
              }
              tone="signal"
            />
            <StatItem icon={<MailIcon />} label="Cold emails" value={data.cold_emails.length} to="/cold-email" />
            <StatItem icon={<RunsIcon />} label="Runs logged" value={data.summary.length} />
          </div>

          <AddManualPosting laneNames={data.lane_names} laneLabels={data.lane_labels} onAdded={load} />
        </>
      )}

      {tab === "review" && (
        <>
          {data.pending.length > 0 && (
            <div className="filter-bar">
              <button type="button" className={`filter-pill${laneFilter === "all" ? " active" : ""}`} onClick={() => setLaneFilter("all")}>All lanes</button>
              {data.lane_names.map((n) => (
                <button key={n} type="button" className={`filter-pill${laneFilter === n ? " active" : ""}`} onClick={() => setLaneFilter(n)}>
                  {data.lane_labels[n] || n.replace(/_/g, " ")}
                </button>
              ))}
              <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
                <option value="all">All sources</option>
                {sources.map((s) => <option key={s} value={s}>{sourceLabel(s)}</option>)}
              </select>
              <input placeholder="Search company, role, location" value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
          )}

          {selected.size > 0 && (
            <div className="bulk-bar">
              <span>{selected.size} selected</span>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button type="button" className="secondary" onClick={() => setSelected(new Set())} disabled={bulkBusy}>Clear</button>
                <button type="button" className="danger" onClick={() => setConfirmTarget({ type: "bulk" })} disabled={bulkBusy}>{bulkBusy ? "Dismissing…" : "Dismiss selected"}</button>
              </div>
            </div>
          )}

          {filteredPendingByLane.length ? (
            filteredPendingByLane.map((section) => (
              <LaneSection key={section.slug} section={section}>
                <div className="posting-list">
                  {section.rows.map((row) => (
                    <PostingCard
                      key={row.posting_key} row={row}
                      selected={selected.has(row.posting_key)}
                      onToggleSelect={(checked) => toggleSelect(row.posting_key, checked)}
                      onPromote={() => promote(row.posting_key)}
                      onDismiss={() => setConfirmTarget({ type: "single", key: row.posting_key })}
                      onRetry={() => retry(row.posting_key)}
                      open={openDetail === row.posting_key}
                      onToggleOpen={() => setOpenDetail(openDetail === row.posting_key ? null : row.posting_key)}
                      busy={busyRows[row.posting_key]}
                    />
                  ))}
                </div>
              </LaneSection>
            ))
          ) : (
            <div className="empty-state">
              {!data.pending.length && <CheckCircleIcon />}
              {data.pending.length ? "No postings match these filters." : "Nothing waiting on you right now."}
            </div>
          )}
        </>
      )}

      {tab === "applied" && (
        <>
          {data.applied.length > 0 && (
            <div className="filter-bar">
              <button type="button" className={`filter-pill${laneFilter === "all" ? " active" : ""}`} onClick={() => setLaneFilter("all")}>All lanes</button>
              {data.lane_names.map((n) => (
                <button key={n} type="button" className={`filter-pill${laneFilter === n ? " active" : ""}`} onClick={() => setLaneFilter(n)}>
                  {data.lane_labels[n] || n.replace(/_/g, " ")}
                </button>
              ))}
              <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
                <option value="all">All sources</option>
                {sources.map((s) => <option key={s} value={s}>{sourceLabel(s)}</option>)}
              </select>
              <input placeholder="Search company, role, location" value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
          )}

          {filteredAppliedByLane.length ? (
            filteredAppliedByLane.map((section) => (
              <LaneSection key={section.slug} section={section} tone="pine">
                <div className="posting-list">
                  {section.rows.map((row) => (
                    <PostingCard
                      key={row.posting_key} row={row} applied
                      open={openDetail === row.posting_key}
                      onToggleOpen={() => setOpenDetail(openDetail === row.posting_key ? null : row.posting_key)}
                      onSetOutcome={(outcome) => setOutcome(row.posting_key, outcome)}
                      busy={busyRows[row.posting_key]}
                    />
                  ))}
                </div>
              </LaneSection>
            ))
          ) : (
            <div className="empty-state">
              {data.applied.length ? "No applications match these filters." : "No applications yet."}
            </div>
          )}
        </>
      )}

      {tab === "runs" && (
        data.summary.length ? (
          <div className="runs-table">
            <table>
              <thead><tr><th>Date</th><th>New to swipe</th><th>Ready to apply</th><th>Applied</th><th>Emails</th><th>Errors</th></tr></thead>
              <tbody>
                {[...data.summary].slice(-14).reverse().map((row, i) => {
                  // row.errors is always a numeric string ("0", "1", ...) -- build_daily_summary
                  // (backend/pipeline/daily_report.py) writes str(len(errors)), never "". A plain
                  // truthiness check on the string treats "0" the same as "3", so it has to be
                  // compared numerically here, not just checked for emptiness.
                  const errorCount = Number(row.errors) || 0;
                  const isEmpty = !errorCount && !row.queued_count && !row.awaiting_apply_count && !row.applied_count && !row.emails_sent;
                  const emptyReason = !row.total_postings_found
                    ? "no postings found"
                    : !row.total_matched
                      ? "found postings, none matched your lane filters"
                      : "no activity";
                  return (
                    <tr key={i} className={isEmpty ? "runs-row-empty" : ""}>
                      <td>{row.date}</td>
                      <td>{row.queued_count !== "" ? row.queued_count : "n/a"}</td>
                      <td>{row.awaiting_apply_count !== "" ? row.awaiting_apply_count : "n/a"}</td>
                      <td>{row.applied_count}</td>
                      <td>{row.emails_sent}</td>
                      <td>
                        {errorCount
                          ? <span className="badge amber">{errorCount}</span>
                          : isEmpty
                            ? <span className="badge danger" title={emptyReason}>{emptyReason}</span>
                            : <span className="hint">none</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">No runs yet.</div>
        )
      )}

      <ConfirmDialog
        open={!!confirmTarget}
        title={confirmTarget?.type === "bulk" ? `Dismiss ${selected.size} job${selected.size === 1 ? "" : "s"}?` : "Dismiss this job?"}
        body="It won't show up here again, but it's not deleted. It's still in your account (and your Google Sheet) marked dismissed, if you change your mind."
        confirmLabel="Dismiss"
        onConfirm={confirmDismiss}
        onCancel={() => setConfirmTarget(null)}
      />
    </>
  );
}
