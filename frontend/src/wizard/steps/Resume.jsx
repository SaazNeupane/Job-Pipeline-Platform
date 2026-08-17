import { useRef, useState } from "react";
import { Navigate, useNavigate, useOutletContext } from "react-router-dom";
import { api } from "../../api.js";

// No <form> of its own -- this renders inside the Resume step's per-section
// <form> (Back/Next), and nested <form> elements are invalid HTML (the
// browser silently drops the inner one, so its own submit button would fire
// the OUTER form instead). Plain button + refs instead.
function ImportFromPdf({ laneNames, laneLabels, importedLanes, onImported }) {
  const fileRef = useRef(null);
  const keyRef = useRef(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");
  // Multi-lane accounts (e.g. one resume for "ops", one for "it") need a
  // separate PDF per lane -- default to the first lane not yet imported so
  // re-running this after the first import doesn't require re-picking it.
  const [taggedLane, setTaggedLane] = useState(() => laneNames.find((l) => !importedLanes.includes(l)) || laneNames[0] || "");

  async function doImport() {
    const file = fileRef.current?.files[0];
    const geminiKey = keyRef.current?.value.trim();
    setError("");
    if (!file) return setError("Choose a resume PDF first.");
    if (!geminiKey) return setError("A Gemini API key is needed to read the PDF.");
    setImporting(true);
    try {
      const resume = await api.importResume(file, geminiKey);
      onImported(resume, laneNames.length > 1 ? taggedLane : null);
      if (fileRef.current) fileRef.current.value = "";
    } catch (err) {
      setError(err.message);
    } finally {
      setImporting(false);
    }
  }

  return (
    <fieldset>
      <legend>Optional: import from an existing resume PDF</legend>
      <p className="hint">
        Pulls your info out of a PDF you already have instead of retyping it all. Uses a free{" "}
        <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Gemini API key</a> just for this
        one-time read (you'll enter it again, to keep, on the Keys step next). Nothing is invented: only what's
        actually in the PDF gets pulled in, and it fills the form below for you to review and edit, not saved as-is.
        {laneNames.length > 1 && " Have a different resume per job type? Import each one separately below — later imports add to what's already here instead of replacing it."}
      </p>
      {error && <p className="error-banner">{error}</p>}
      {laneNames.length > 1 && (
        <label>
          Tag this resume's entries as relevant to
          <select value={taggedLane} onChange={(e) => setTaggedLane(e.target.value)} disabled={importing}>
            {laneNames.map((name) => (
              <option key={name} value={name}>
                {(laneLabels[name] || name)}{importedLanes.includes(name) ? " (already imported)" : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="grid2">
        <label>Gemini API key<input ref={keyRef} disabled={importing} /></label>
        <label>Resume PDF<input ref={fileRef} type="file" accept=".pdf" disabled={importing} /></label>
      </div>
      <div className="wizard-actions">
        <button type="button" className="secondary" onClick={doImport} disabled={importing}>{importing ? "Reading…" : "Import"}</button>
      </div>
    </fieldset>
  );
}

// Pasted bulleted lists carry their own bullet/dash/numbering marker on
// each line (•, -, *, –, "1.", ...) -- strip it so it doesn't ride along
// into the generated resume text as a literal character.
const BULLET_MARKER_RE = /^[\s]*(?:[•◦▪‣∙·*-]|\d+[.)])\s+/;
const lines = (s) => s.split("\n").map((v) => v.trim().replace(BULLET_MARKER_RE, "")).filter(Boolean);
const csv = (s) => s.split(",").map((v) => v.trim()).filter(Boolean);
const uid = () => crypto.randomUUID();

// Mirrors webapp/wizard.py's build_resume_json: an entry tagged to a
// DIFFERENT selected lane is hidden from this one; untagged is neutral and
// shows everywhere. A lane with 0 total (relevant + neutral) entries would
// get a resume with no work experience on it at all -- catch that before
// finalize instead of after.
function laneExperienceCounts(experience, laneNames) {
  const counts = {};
  for (const lane of laneNames) {
    const others = new Set(laneNames.filter((l) => l !== lane));
    const relevant = experience.filter((e) => e.lanes.includes(lane)).length;
    const neutral = experience.filter((e) => !e.lanes.includes(lane) && !e.lanes.some((l) => others.has(l))).length;
    counts[lane] = relevant + neutral;
  }
  return counts;
}

function fromInitial(resume, applicant) {
  const r = resume || {};
  const a = applicant || {};
  const applicantName = `${a.first_name || ""} ${a.last_name || ""}`.trim();
  return {
    name: r.name || applicantName,
    phone: (r.contact || {}).phone || "",
    email: (r.contact || {}).email || "",
    website: (r.contact || {}).website || "",
    education: (r.education || []).map((e) => ({ id: uid(), institution: e.institution || "", location: e.location || "", credential: e.credential || "", gpa: e.gpa || "", dates: e.dates || "", highlights: (e.highlights || []).join("\n") })),
    experience: (r.experience || []).map((e) => ({ id: uid(), company: e.company || "", title: e.title || "", location: e.location || "", dates: e.dates || "", bullets: (e.bullets || []).join("\n"), lanes: e.lanes || [] })),
    skills: (r.skills || []).map((s) => ({ id: uid(), name: s.name || "", items: (s.items || []).join(", "), lanes: s.lanes || [] })),
    projects: (r.projects || []).map((p) => ({ id: uid(), name: p.name || "", description: p.description || "", bullets: (p.bullets || []).join("\n"), lanes: p.lanes || [] })),
    interests: (r.interests || []).join(", "),
  };
}

// Second (and later) PDF import for a multi-lane account adds to the resume
// built so far instead of replacing it -- otherwise importing a second
// lane's PDF would wipe out the first lane's freshly-imported entries.
// Contact/name/interests only fill in if still blank (first import wins;
// a second resume's contact info is normally the same person anyway).
function mergeImportedResume(prev, resume, applicant, taggedLane) {
  const incoming = fromInitial(resume, applicant);
  const tag = (list) => (taggedLane ? list.map((item) => ({ ...item, lanes: [...new Set([...(item.lanes || []), taggedLane])] })) : list);
  return {
    name: prev.name || incoming.name,
    phone: prev.phone || incoming.phone,
    email: prev.email || incoming.email,
    website: prev.website || incoming.website,
    education: [...prev.education, ...incoming.education],
    experience: [...prev.experience, ...tag(incoming.experience)],
    skills: [...prev.skills, ...tag(incoming.skills)],
    projects: [...prev.projects, ...tag(incoming.projects)],
    interests: prev.interests || incoming.interests,
  };
}

function LaneChecks({ laneNames, laneLabels, value, onChange }) {
  return (
    <div className="chip-input">
      {laneNames.map((name) => (
        <label key={name} className="checkbox-row">
          <input
            type="checkbox" checked={value.includes(name)}
            onChange={() => onChange(value.includes(name) ? value.filter((v) => v !== name) : [...value, name])}
          />
          {laneLabels[name] || name}
        </label>
      ))}
    </div>
  );
}

const SECTIONS = [
  { key: "import", label: "Import (optional)" },
  { key: "contact", label: "Contact" },
  { key: "education", label: "Education" },
  { key: "experience", label: "Work experience" },
  { key: "skills", label: "Skills" },
  { key: "projects", label: "Projects (optional)" },
  { key: "interests", label: "Interests (optional)" },
];

export default function Resume() {
  const { draft, refreshDraft } = useOutletContext();
  const navigate = useNavigate();
  const laneNames = draft.lane_names || [];
  const laneLabels = draft.lane_labels || {};
  const [r, setR] = useState(() => fromInitial(draft.shared_resume, draft.applicant));
  const [importedLanes, setImportedLanes] = useState([]);
  const [error, setError] = useState("");
  // One section on screen at a time -- the old single-page form (contact +
  // education + experience + skills + projects + interests, all at once)
  // read as overwhelming to a non-technical first-time user (real feedback:
  // "the UI looks too much"). Same data/state/validation as before, just
  // shown a section at a time with its own Back/Continue.
  const [section, setSection] = useState(0);

  if (!laneNames.length) return <Navigate to="/setup/lanes" replace />;

  const update = (patch) => setR((prev) => ({ ...prev, ...patch }));
  const updateList = (key, id, patch) => setR((prev) => ({ ...prev, [key]: prev[key].map((x) => (x.id === id ? { ...x, ...patch } : x)) }));
  const addTo = (key, item) => setR((prev) => ({ ...prev, [key]: [...prev[key], item] }));
  const removeFrom = (key, id) => setR((prev) => ({ ...prev, [key]: prev[key].filter((x) => x.id !== id) }));

  function nextSection(e) {
    e.preventDefault();
    setError("");
    if (SECTIONS[section].key === "experience" && !r.experience.some((exp) => exp.company.trim() || exp.title.trim())) {
      setError("Add at least one job before continuing.");
      return;
    }
    setSection((s) => Math.min(s + 1, SECTIONS.length - 1));
  }

  function prevSection() {
    setError("");
    if (section === 0) navigate("/setup/lanes");
    else setSection((s) => s - 1);
  }

  async function submit(e) {
    e.preventDefault();
    setError("");
    const shared_resume = {
      name: r.name,
      contact: { phone: r.phone, email: r.email, website: r.website },
      education: r.education.map((e) => ({ institution: e.institution, location: e.location, credential: e.credential, gpa: e.gpa, dates: e.dates, highlights: lines(e.highlights) })),
      experience: r.experience.map((e) => ({ company: e.company, title: e.title, location: e.location, dates: e.dates, bullets: lines(e.bullets), lanes: e.lanes })),
      skills: r.skills.map((s) => ({ name: s.name, items: csv(s.items), lanes: s.lanes })),
      projects: r.projects.map((p) => ({ name: p.name, description: p.description, bullets: lines(p.bullets), lanes: p.lanes })),
      interests: csv(r.interests),
    };

    const counts = laneExperienceCounts(shared_resume.experience, laneNames);
    const empty = laneNames.filter((name) => counts[name] === 0);
    if (empty.length) {
      setError(
        `${empty.map((n) => laneLabels[n] || n).join(", ")} would get a resume with no work experience on it. ` +
        `Either add a job for it, or leave that job's "Relevant to" boxes unchecked so it shows up on every resume.`
      );
      return;
    }

    try {
      await api.patchDraft({ shared_resume });
      await refreshDraft();
      navigate("/setup/keys");
    } catch (err) {
      setError(err.message);
    }
  }

  const isLast = section === SECTIONS.length - 1;
  const sectionKey = SECTIONS[section].key;

  return (
    <>
      <h1>Build your resume</h1>
      <p className="hint">
        Step {section + 1} of {SECTIONS.length}: {SECTIONS[section].label}. Bullets and highlights: one per line.
        Nothing here is invented for you; this is exactly what the pipeline will use, tailored to each posting.
      </p>
      {error && <p className="error-banner">{error}</p>}

      <form onSubmit={isLast ? submit : nextSection}>
        {sectionKey === "import" && (
          <>
            <p>
              Enter your real work history once. On later steps you'll tick which job type(s) each entry applies to.
              An entry only tagged to one job type won't show up on another job type's resume.
            </p>
            <ImportFromPdf
              laneNames={laneNames}
              laneLabels={laneLabels}
              importedLanes={importedLanes}
              onImported={(resume, taggedLane) => {
                setR((prev) => mergeImportedResume(prev, resume, draft.applicant, taggedLane));
                const nextImported = taggedLane ? [...new Set([...importedLanes, taggedLane])] : importedLanes;
                setImportedLanes(nextImported);
                // Auto-advance once every lane has its own imported resume (or there's
                // only one lane); otherwise stay put so the next lane's PDF can go in.
                if (laneNames.length <= 1 || laneNames.every((l) => nextImported.includes(l))) setSection((s) => s + 1);
              }}
            />
            <p className="hint">Or skip this and fill it in by hand on the next steps.</p>
          </>
        )}

        {sectionKey === "contact" && (
          <fieldset>
            <legend>Contact</legend>
            <label>Full name<input value={r.name} onChange={(e) => update({ name: e.target.value })} required /></label>
            <div className="grid3">
              <label>Phone<input value={r.phone} onChange={(e) => update({ phone: e.target.value })} /></label>
              <label>Email<input type="email" value={r.email} onChange={(e) => update({ email: e.target.value })} /></label>
              <label>Website<input value={r.website} onChange={(e) => update({ website: e.target.value })} /></label>
            </div>
          </fieldset>
        )}

        {sectionKey === "education" && (
          <fieldset>
            <legend>Education</legend>
            {r.education.map((e) => (
              <div className="entry-block" key={e.id}>
                <label>Institution<input value={e.institution} onChange={(ev) => updateList("education", e.id, { institution: ev.target.value })} /></label>
                <div className="grid3">
                  <label>Location<input value={e.location} onChange={(ev) => updateList("education", e.id, { location: ev.target.value })} /></label>
                  <label>Credential<input value={e.credential} onChange={(ev) => updateList("education", e.id, { credential: ev.target.value })} placeholder="e.g. Diploma in ..." /></label>
                  <label>Dates<input value={e.dates} onChange={(ev) => updateList("education", e.id, { dates: ev.target.value })} placeholder="e.g. 2024" /></label>
                </div>
                <label>GPA (optional)<input value={e.gpa} onChange={(ev) => updateList("education", e.id, { gpa: ev.target.value })} /></label>
                <label>Highlights (one per line, optional)<textarea rows={3} value={e.highlights} onChange={(ev) => updateList("education", e.id, { highlights: ev.target.value })} /></label>
                <button type="button" className="ghost" onClick={() => removeFrom("education", e.id)}>Remove</button>
              </div>
            ))}
            <button type="button" className="secondary" onClick={() => addTo("education", { id: uid(), institution: "", location: "", credential: "", gpa: "", dates: "", highlights: "" })}>+ Add education</button>
          </fieldset>
        )}

        {sectionKey === "experience" && (
          <fieldset>
            <legend>Work experience</legend>
            {r.experience.map((e) => (
              <div className="entry-block" key={e.id}>
                <div className="grid2">
                  <label>Company<input value={e.company} onChange={(ev) => updateList("experience", e.id, { company: ev.target.value })} /></label>
                  <label>Job title<input value={e.title} onChange={(ev) => updateList("experience", e.id, { title: ev.target.value })} /></label>
                </div>
                <div className="grid2">
                  <label>Location<input value={e.location} onChange={(ev) => updateList("experience", e.id, { location: ev.target.value })} /></label>
                  <label>Dates<input value={e.dates} onChange={(ev) => updateList("experience", e.id, { dates: ev.target.value })} placeholder="e.g. 2023 - Present" /></label>
                </div>
                <label>What you did (one bullet per line)<textarea rows={4} value={e.bullets} onChange={(ev) => updateList("experience", e.id, { bullets: ev.target.value })} /></label>
                <div>
                  <span className="hint">Relevant to (leave unchecked = show on every resume; checking one hides it from the others)</span>
                  <LaneChecks laneNames={laneNames} laneLabels={laneLabels} value={e.lanes} onChange={(v) => updateList("experience", e.id, { lanes: v })} />
                </div>
                <button type="button" className="ghost" onClick={() => removeFrom("experience", e.id)}>Remove</button>
              </div>
            ))}
            <button type="button" className="secondary" onClick={() => addTo("experience", { id: uid(), company: "", title: "", location: "", dates: "", bullets: "", lanes: [] })}>+ Add job</button>
          </fieldset>
        )}

        {sectionKey === "skills" && (
          <fieldset>
            <legend>Skills</legend>
            <p className="hint">Group skills into categories, e.g. "Languages: Python, JavaScript".</p>
            {r.skills.map((s) => (
              <div className="entry-block" key={s.id}>
                <div className="grid2">
                  <label>Category name<input value={s.name} onChange={(ev) => updateList("skills", s.id, { name: ev.target.value })} placeholder="e.g. Languages" /></label>
                  <label>Skills (comma-separated)<input value={s.items} onChange={(ev) => updateList("skills", s.id, { items: ev.target.value })} /></label>
                </div>
                <div>
                  <span className="hint">Relevant to (leave unchecked = show on every resume)</span>
                  <LaneChecks laneNames={laneNames} laneLabels={laneLabels} value={s.lanes} onChange={(v) => updateList("skills", s.id, { lanes: v })} />
                </div>
                <button type="button" className="ghost" onClick={() => removeFrom("skills", s.id)}>Remove</button>
              </div>
            ))}
            <button type="button" className="secondary" onClick={() => addTo("skills", { id: uid(), name: "", items: "", lanes: [] })}>+ Add skill category</button>
          </fieldset>
        )}

        {sectionKey === "projects" && (
          <fieldset>
            <legend>Projects (optional)</legend>
            {r.projects.map((p) => (
              <div className="entry-block" key={p.id}>
                <label>Project name<input value={p.name} onChange={(ev) => updateList("projects", p.id, { name: ev.target.value })} /></label>
                <label>One-line description<input value={p.description} onChange={(ev) => updateList("projects", p.id, { description: ev.target.value })} /></label>
                <label>Details (one bullet per line)<textarea rows={3} value={p.bullets} onChange={(ev) => updateList("projects", p.id, { bullets: ev.target.value })} /></label>
                <div>
                  <span className="hint">Relevant to (leave unchecked = show on every resume)</span>
                  <LaneChecks laneNames={laneNames} laneLabels={laneLabels} value={p.lanes} onChange={(v) => updateList("projects", p.id, { lanes: v })} />
                </div>
                <button type="button" className="ghost" onClick={() => removeFrom("projects", p.id)}>Remove</button>
              </div>
            ))}
            <button type="button" className="secondary" onClick={() => addTo("projects", { id: uid(), name: "", description: "", bullets: "", lanes: [] })}>+ Add project</button>
          </fieldset>
        )}

        {sectionKey === "interests" && (
          <fieldset>
            <legend>Interests (optional)</legend>
            <label>Comma-separated<input value={r.interests} onChange={(e) => update({ interests: e.target.value })} /></label>
          </fieldset>
        )}

        <div className="wizard-actions">
          <button type="button" className="ghost" onClick={prevSection}>Back</button>
          <button type="submit" className="primary">{isLast ? "Continue" : "Next"}</button>
        </div>
      </form>
    </>
  );
}
