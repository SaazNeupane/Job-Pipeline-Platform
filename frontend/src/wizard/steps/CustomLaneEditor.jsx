import { SENIORITY_LABELS, SOURCE_LABELS, toggleInArray } from "./laneConstants.js";

export default function CustomLaneEditor({ lane, meta, onChange, onRemove }) {
  const sources = lane.sources ?? meta.source_options;

  return (
    <div className="entry-block">
      <div className="grid2">
        <label>Job type name<input value={lane.label} onChange={(e) => onChange({ label: e.target.value })} placeholder="e.g. Warehouse Associate" /></label>
        <label>Keywords, comma-separated<input value={lane.keywords} onChange={(e) => onChange({ keywords: e.target.value })} placeholder="warehouse, forklift, picker" /></label>
      </div>

      <details className="advanced">
        <summary>Fine-tune this job type (optional)</summary>
        <div className="grid2">
          <label>
            Must also mention (optional)
            <input value={lane.required_keywords} onChange={(e) => onChange({ required_keywords: e.target.value })} placeholder="e.g. helpdesk, QA" />
          </label>
          <label>
            Experience level
            <select value={lane.seniority_max} onChange={(e) => onChange({ seniority_max: e.target.value })}>
              <option value="">No limit</option>
              {(meta.seniority_levels || []).map((level) => (
                <option key={level} value={level}>{SENIORITY_LABELS[level] || level}</option>
              ))}
            </select>
          </label>
          <label>
            Max years of experience required (optional)
            <input
              type="number" min="0" value={lane.max_years_experience}
              onChange={(e) => onChange({ max_years_experience: e.target.value })}
              placeholder="e.g. 1 -- skips postings asking for more"
            />
          </label>
        </div>
        <p className="hint">"Must also mention" narrows matches down further: a posting has to include at least one of these words too, on top of the main keywords above.</p>
        <label>Industry (optional, checked against the job title only)<input value={lane.industries} onChange={(e) => onChange({ industries: e.target.value })} placeholder="retail, food service" /></label>

        <div>
          <span className="hint">Where to search (leave all checked for the widest search)</span>
          <div className="chip-input" style={{ marginTop: "0.4rem" }}>
            {meta.source_options.map((s) => (
              <label key={s} className="checkbox-row">
                <input type="checkbox" checked={sources.includes(s)} onChange={() => onChange({ sources: toggleInArray(sources, s) })} />
                {SOURCE_LABELS[s] || s.replace("_", " ")}
              </label>
            ))}
          </div>
        </div>

        <div>
          <span className="hint">Remote / onsite (leave all unchecked for no filter)</span>
          <div className="chip-input" style={{ marginTop: "0.4rem" }}>
            {meta.remote_type_options.map((r) => (
              <label key={r} className="checkbox-row">
                <input type="checkbox" checked={lane.remote_types.includes(r)} onChange={() => onChange({ remote_types: toggleInArray(lane.remote_types, r) })} />
                {r}
              </label>
            ))}
          </div>
        </div>

        <div>
          <span className="hint">Employment type (leave all unchecked for no filter)</span>
          <div className="chip-input" style={{ marginTop: "0.4rem" }}>
            {meta.employment_type_options.map((et) => (
              <label key={et} className="checkbox-row">
                <input type="checkbox" checked={lane.employment_types.includes(et)} onChange={() => onChange({ employment_types: toggleInArray(lane.employment_types, et) })} />
                {et.replace("_", " ")}
              </label>
            ))}
          </div>
        </div>

        <div className="grid2">
          <label>Salary min (optional)<input type="number" value={lane.salary_min} onChange={(e) => onChange({ salary_min: e.target.value })} /></label>
          <label>Salary max (optional)<input type="number" value={lane.salary_max} onChange={(e) => onChange({ salary_max: e.target.value })} /></label>
        </div>

        <label>Minimum match score (optional, 0-100%)
          <input type="number" min="0" max="100" value={lane.min_match_score} onChange={(e) => onChange({ min_match_score: e.target.value })} />
        </label>

        <label className="checkbox-row">
          <input type="checkbox" checked={lane.inPerson} onChange={(e) => onChange({ inPerson: e.target.checked })} />
          This is an in-person role near me (limit to a commute radius)
        </label>
        {lane.inPerson && (
          <label>Radius in km<input value={lane.radius_km} onChange={(e) => onChange({ radius_km: e.target.value })} placeholder="e.g. 25" /></label>
        )}
      </details>

      <button type="button" className="ghost" onClick={onRemove}>Remove</button>
    </div>
  );
}
