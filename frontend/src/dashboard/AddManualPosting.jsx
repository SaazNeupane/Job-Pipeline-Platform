import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";

export default function AddManualPosting({ laneNames, laneLabels, onAdded }) {
  const [open, setOpen] = useState(false);
  const [lane, setLane] = useState(laneNames[0] || "");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api.addManualPosting(lane, text, url);
      setText("");
      setUrl("");
      setOpen(false);
      onAdded(result.row);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!laneNames.length) {
    return (
      <details className="advanced manual-posting">
        <summary>Found one yourself? Paste a posting in</summary>
        <p className="hint">
          This needs at least one job type set up first, since tailoring a resume for a
          posting means pulling from one of your lane's resumes. <Link to="/setup/lanes">Add a job type</Link>,
          then come back here.
        </p>
      </details>
    );
  }

  return (
    <details className="advanced manual-posting" open={open} onToggle={(e) => setOpen(e.target.open)}>
      <summary>Found one yourself? Paste a posting in</summary>
      <form onSubmit={submit}>
        <p className="hint">
          Paste the full text of a posting from anywhere, Indeed, LinkedIn, a company site,
          and it goes straight to tailoring a resume and cover letter for it, same as a
          right-swipe would. No need to send it through the swipe queue first.
        </p>
        {error && <p className="error-banner">{error}</p>}
        <label>
          Job type
          <select value={lane} onChange={(e) => setLane(e.target.value)}>
            {laneNames.map((name) => (
              <option key={name} value={name}>{laneLabels[name] || name.replace(/_/g, " ")}</option>
            ))}
          </select>
        </label>
        {laneNames.length > 1 && (
          <p className="hint">
            Nothing here quite fits? Pick whichever's closest, it tailors against that lane's resume.
            {" "}<Link to="/setup/lanes">Add a new job type</Link> if you'd rather build one for this instead.
          </p>
        )}
        <label>
          Posting link (optional)
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." />
        </label>
        <label>
          Job posting text
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={8}
            placeholder="Paste the whole posting here -- title, company, location, description"
          />
        </label>
        <button type="submit" className="primary" disabled={busy || !text.trim()}>
          {busy ? "Reading it…" : "Add it"}
        </button>
      </form>
    </details>
  );
}
