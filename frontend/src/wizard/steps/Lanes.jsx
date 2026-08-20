import { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { api } from "../../api.js";
import Loading from "../../components/Loading.jsx";
import { useApiData } from "../../hooks/useApiData.js";

const emptyCustomLane = () => ({
  id: crypto.randomUUID(),
  label: "", keywords: "", required_keywords: "", seniority_max: "", max_years_experience: "", industries: "",
  inPerson: false, radius_km: "",
  sources: null, // null = all real sources (backend default)
  remote_types: [], employment_types: [],
  salary_min: "", salary_max: "", min_match_score: "",
});

function csv(s) {
  return s.split(",").map((v) => v.trim()).filter(Boolean);
}

function toggleInArray(arr, value) {
  return arr.includes(value) ? arr.filter((v) => v !== value) : [...arr, value];
}

// Plain names for the raw source ids the backend uses -- "hiring_cafe"/
// "greenhouse" mean nothing to a non-technical user filling this in.
const SOURCE_LABELS = {
  adzuna: "Adzuna (general job search)",
  hiring_cafe: "Hiring Cafe (general job search)",
  greenhouse: "Greenhouse (startup/tech company job boards)",
  lever: "Lever (startup/tech company job boards)",
  ashby: "Ashby (startup/tech company job boards)",
};

// One small icon per built-in preset, purely decorative -- breaks up what
// was a plain stacked checkbox list into something that reads faster at a
// glance. A lane not in this map (shouldn't happen for a built-in preset,
// but stay safe) just gets a generic briefcase.
const LANE_ICONS = {
  it_tech: "💻", ops_supervisor: "🧑‍💼", warehouse_logistics: "📦", retail_sales: "🛍️",
  food_service: "🍳", customer_service: "🎧", administrative: "🗂️", healthcare_support: "🩺",
  skilled_trades: "🔧", education_childcare: "🎓", general_labor: "🏗️", delivery_driver: "🚚",
  manufacturing: "⚙️", accounting_finance: "💰", marketing_creative: "🎨", cleaning_janitorial: "🧹",
  new_grad_coop: "🎓",
};

const SENIORITY_LABELS = {
  intern: "Internship only",
  entry: "Entry-level only",
  intermediate: "Up to intermediate/mid-level",
  senior: "Up to senior (no cap in practice)",
};

export default function Lanes() {
  const { draft, refreshDraft } = useOutletContext();
  const navigate = useNavigate();

  const [selectedPresets, setSelectedPresets] = useState(new Set(draft.lane_names || []));
  const [presetExcluded, setPresetExcluded] = useState({}); // preset name -> Set of unchecked default keywords
  const [presetExtra, setPresetExtra] = useState({}); // preset name -> "add your own" text
  const [presetSeniority, setPresetSeniority] = useState({}); // preset name -> overridden level, "" = preset's own default
  const [presetMaxYears, setPresetMaxYears] = useState({}); // preset name -> overridden years-of-experience cap, "" = preset's own default
  const [customLanes, setCustomLanes] = useState([]);
  const [presetFilter, setPresetFilter] = useState("");
  const [greenhouseBoards, setGreenhouseBoards] = useState((draft.greenhouse_boards || []).join(", "));
  const [leverCompanies, setLeverCompanies] = useState((draft.lever_companies || []).join(", "));
  const [ashbyBoards, setAshbyBoards] = useState((draft.ashby_boards || []).join(", "));
  const [adzunaCountry, setAdzunaCountry] = useState(draft.adzuna_country || "ca");
  const [targetCountries, setTargetCountries] = useState((draft.target_countries || []).join(", "));
  const [targetRegions, setTargetRegions] = useState((draft.target_regions || []).join(", "));
  const [runHourUtc, setRunHourUtc] = useState(draft.run_hour_utc ?? 14);

  const { data: meta, error, setError } = useApiData(() => api.lanePresets(), []);

  function togglePreset(name) {
    setSelectedPresets((prev) => {
      const next = new Set(prev);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });
  }

  function updateCustomLane(id, patch) {
    setCustomLanes((prev) => prev.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  }

  function togglePresetKeyword(name, keyword) {
    setPresetExcluded((prev) => {
      const next = new Set(prev[name] || []);
      next.has(keyword) ? next.delete(keyword) : next.add(keyword);
      return { ...prev, [name]: next };
    });
  }

  function setAllPresetKeywords(name, checked) {
    setPresetExcluded((prev) => ({ ...prev, [name]: checked ? new Set() : new Set(meta.presets[name].keywords) }));
  }

  function presetKeywords(name) {
    const defaults = meta.presets[name].keywords;
    const excluded = presetExcluded[name] || new Set();
    return [...defaults.filter((k) => !excluded.has(k)), ...csv(presetExtra[name] || "")];
  }

  async function submit(e) {
    e.preventDefault();
    setError("");

    for (const name of selectedPresets) {
      if (!presetKeywords(name).length) {
        setError(`${meta.presets[name].label}: uncheck all the defaults and it has nothing left to search for -- keep at least one, or add your own.`);
        return;
      }
    }

    const presets = [...selectedPresets].map((name) => {
      const excluded = presetExcluded[name] || new Set();
      const extra = csv(presetExtra[name] || "");
      const keywordsChanged = excluded.size > 0 || extra.length > 0;
      const seniority = presetSeniority[name];
      const seniorityChanged = seniority !== undefined && seniority !== (meta.presets[name].seniority_max || "");
      const maxYears = presetMaxYears[name];
      const maxYearsChanged = maxYears !== undefined && maxYears !== String(meta.presets[name].max_years_experience ?? "");
      return {
        name,
        ...(keywordsChanged ? { keywords: presetKeywords(name) } : {}),
        ...(seniorityChanged ? { seniority_max: seniority || null } : {}),
        ...(maxYearsChanged ? { max_years_experience: maxYears ? parseInt(maxYears, 10) : null } : {}),
      };
    });
    const custom_lanes = customLanes
      .filter((c) => c.label.trim() || c.keywords.trim())
      .map((c) => ({
        label: c.label,
        keywords: csv(c.keywords),
        required_keywords: c.required_keywords ? csv(c.required_keywords) : null,
        seniority_max: c.seniority_max || null,
        max_years_experience: c.max_years_experience ? parseInt(c.max_years_experience, 10) : null,
        industries: c.industries ? csv(c.industries) : [],
        radius_km: c.inPerson && c.radius_km ? parseFloat(c.radius_km) : null,
        sources: c.sources,
        remote_types: c.remote_types,
        employment_types: c.employment_types,
        salary_min: c.salary_min ? parseFloat(c.salary_min) : null,
        salary_max: c.salary_max ? parseFloat(c.salary_max) : null,
        min_match_score: c.min_match_score ? parseFloat(c.min_match_score) / 100 : null,
      }));

    try {
      await api.submitLanes({
        presets, custom_lanes,
        greenhouse_boards: csv(greenhouseBoards),
        lever_companies: csv(leverCompanies),
        ashby_boards: csv(ashbyBoards),
        adzuna_country: adzunaCountry.trim().toLowerCase(),
        target_countries: csv(targetCountries).map((c) => c.toLowerCase()),
        target_regions: csv(targetRegions).map((r) => r.toLowerCase()),
        run_hour_utc: runHourUtc,
      });
      await refreshDraft();
      navigate("/setup/resume");
    } catch (err) {
      setError(err.message);
    }
  }

  if (!meta) return <Loading />;

  const filterText = presetFilter.trim().toLowerCase();
  const filteredPresets = Object.entries(meta.presets).filter(([name, lane]) => {
    if (!filterText) return true;
    const haystack = `${lane.label} ${(meta.preset_blurbs || {})[name] || ""} ${lane.keywords.join(" ")}`.toLowerCase();
    return haystack.includes(filterText);
  });

  return (
    <>
      <h1>What kind of jobs are you applying for?</h1>
      <p className="lede">Pick at least one, built-in or your own. Your resume gets tailored differently for each, and each lane can target its own countries, remote preference, salary range, and sources.</p>
      {error && <p className="error-banner">{error}</p>}

      <form onSubmit={submit}>
        <input
          className="lane-search"
          value={presetFilter}
          onChange={(e) => setPresetFilter(e.target.value)}
          placeholder="Search job types (e.g. warehouse, driver, admin)"
        />
        {filteredPresets.length === 0 && (
          <p className="hint">No built-in job type matches "{presetFilter}". Build your own further down instead.</p>
        )}
        <div className="lane-grid">
          {filteredPresets.map(([name, lane]) => (
            <label key={name} className="lane-card">
              <input type="checkbox" className="sr-only" checked={selectedPresets.has(name)} onChange={() => togglePreset(name)} />
              <span className="lane-card-check" aria-hidden="true">✓</span>
              <span className="lane-card-icon">{LANE_ICONS[name] || "💼"}</span>
              <div>
                <div className="lane-card-title">{lane.label}</div>
                <div className="lane-card-hint">{(meta.preset_blurbs || {})[name] || lane.keywords.join(", ")}</div>
              </div>
            </label>
          ))}
        </div>
        {[...selectedPresets].map((name) => {
          const excluded = presetExcluded[name] || new Set();
          const total = meta.presets[name].keywords.length;
          const kept = total - excluded.size;
          return (
            <details className="advanced" key={name}>
              <summary>Customize keywords for {meta.presets[name].label}</summary>
              <p className="hint">
                This preset searches every keyword lit up below. Want just part of it, like
                "baker" instead of every food-service role? Tap the rest off.
              </p>
              <div className="preset-keyword-head">
                <span className="hint">{kept} of {total} selected</span>
                <button type="button" className="ghost" onClick={() => setAllPresetKeywords(name, true)}>Select all</button>
                <button type="button" className="ghost" onClick={() => setAllPresetKeywords(name, false)}>Select none</button>
              </div>
              <div className="chip-input">
                {meta.presets[name].keywords.map((kw) => {
                  const on = !excluded.has(kw);
                  return (
                    <button
                      type="button" key={kw}
                      className={`keyword-chip${on ? " on" : ""}`}
                      aria-pressed={on}
                      onClick={() => togglePresetKeyword(name, kw)}
                    >
                      {on ? "✓ " : ""}{kw}
                    </button>
                  );
                })}
              </div>
              <label>
                Add your own, comma-separated (optional)
                <input
                  value={presetExtra[name] || ""}
                  onChange={(e) => setPresetExtra({ ...presetExtra, [name]: e.target.value })}
                  placeholder="e.g. pastry chef, line cook"
                />
              </label>
              <label>
                Experience level
                <select
                  value={presetSeniority[name] ?? (meta.presets[name].seniority_max || "")}
                  onChange={(e) => setPresetSeniority({ ...presetSeniority, [name]: e.target.value })}
                >
                  <option value="">No limit</option>
                  {(meta.seniority_levels || []).map((level) => (
                    <option key={level} value={level}>{SENIORITY_LABELS[level] || level}</option>
                  ))}
                </select>
              </label>
              <label>
                Max years of experience required (optional)
                <input
                  type="number" min="0"
                  value={presetMaxYears[name] ?? (meta.presets[name].max_years_experience ?? "")}
                  onChange={(e) => setPresetMaxYears({ ...presetMaxYears, [name]: e.target.value })}
                  placeholder="e.g. 1 -- skips postings asking for more"
                />
              </label>
            </details>
          );
        })}

        <fieldset>
          <legend>Your own job type (optional)</legend>
          <p className="hint">Not one of the presets above? Build your own, with full control over filters.</p>
          {customLanes.map((c) => (
            <CustomLaneEditor
              key={c.id} lane={c} meta={meta}
              onChange={(patch) => updateCustomLane(c.id, patch)}
              onRemove={() => setCustomLanes((prev) => prev.filter((x) => x.id !== c.id))}
            />
          ))}
          <button type="button" className="secondary" onClick={() => setCustomLanes((prev) => [...prev, emptyCustomLane()])}>
            + Add a job type
          </button>
        </fieldset>

        <details className="advanced">
          <summary>Advanced: search settings</summary>
          <p className="hint">Skip this unless you want to point the search at specific companies instead of the built-in default list.</p>
          <label>
            Greenhouse company boards to search (comma-separated)
            <input value={greenhouseBoards} onChange={(e) => setGreenhouseBoards(e.target.value)} placeholder="Leave blank to use our default list: gitlab, doordash, robinhood, figma, faire, stripe, discord, airbnb" />
          </label>
          <label>
            Lever companies to search (comma-separated, e.g. "palantir" for jobs.lever.co/palantir)
            <input value={leverCompanies} onChange={(e) => setLeverCompanies(e.target.value)} placeholder="Leave blank to use our default list: palantir, plaid" />
          </label>
          <label>
            Ashby boards to search (comma-separated, e.g. "linear" for jobs.ashbyhq.com/linear)
            <input value={ashbyBoards} onChange={(e) => setAshbyBoards(e.target.value)} placeholder="Leave blank to use our default list: ramp, linear, notion, openai, substack" />
          </label>
          <label>
            Adzuna country code (2 letters, e.g. "ca" for Canada, "us" for United States)
            <input value={adzunaCountry} onChange={(e) => setAdzunaCountry(e.target.value)} maxLength={2} />
          </label>
          <label>
            Countries you'll accept postings from (comma-separated; codes like "ca"/"us"/"gb"/"au" are matched precisely, anything else is matched as a plain country name)
            <input value={targetCountries} onChange={(e) => setTargetCountries(e.target.value)} placeholder="e.g. ca, us" />
          </label>
          <label>
            Provinces/states to narrow down to (optional, comma-separated; e.g. "on, bc" or "texas"). Leave blank to accept postings anywhere in the countries above
            <input value={targetRegions} onChange={(e) => setTargetRegions(e.target.value)} placeholder="e.g. on, bc, ab" />
          </label>
          <label>
            What hour your daily run happens (UTC)
            <select value={runHourUtc} onChange={(e) => setRunHourUtc(Number(e.target.value))}>
              {Array.from({ length: 24 }, (_, h) => (
                <option key={h} value={h}>{String(h).padStart(2, "0")}:00 UTC</option>
              ))}
            </select>
          </label>
          <p className="hint">Every user's run fires within a few minutes of this hour, not at a specific minute.</p>
        </details>

        <div className="wizard-actions">
          <button type="button" className="ghost" onClick={() => navigate("/setup/about")}>Back</button>
          <button type="submit" className="primary">Continue</button>
        </div>
      </form>
    </>
  );
}

function CustomLaneEditor({ lane, meta, onChange, onRemove }) {
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
