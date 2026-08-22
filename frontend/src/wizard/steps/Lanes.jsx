import { Fragment, useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { api } from "../../api.js";
import Loading from "../../components/Loading.jsx";
import { useApiData } from "../../hooks/useApiData.js";
import CustomLaneEditor from "./CustomLaneEditor.jsx";
import {
  CURATED_COUNTRIES, CURATED_COUNTRY_CODES, LANE_ICONS, SENIORITY_LABELS,
  csv, emptyCustomLane,
} from "./laneConstants.js";

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
  const [workdayBoards, setWorkdayBoards] = useState((draft.workday_boards || []).join(", "));
  const [smartrecruitersCompanies, setSmartrecruitersCompanies] = useState((draft.smartrecruiters_companies || []).join(", "));
  const [workableAccounts, setWorkableAccounts] = useState((draft.workable_accounts || []).join(", "));
  const [recruiteeCompanies, setRecruiteeCompanies] = useState((draft.recruitee_companies || []).join(", "));
  const [breezyCompanies, setBreezyCompanies] = useState((draft.breezy_companies || []).join(", "));
  const [companySiteTrackers, setCompanySiteTrackers] = useState((draft.company_site_trackers || []).join(", "));
  const [adzunaCountry, setAdzunaCountry] = useState(draft.adzuna_country || "ca");
  // Curated countries (see CURATED_COUNTRIES) get real checkboxes with a linked
  // province/state list; anything else falls back into otherCountries as free text, same
  // as the old all-free-text input's behavior for uncurated countries. Seeded from the
  // draft's saved target_countries/target_regions by splitting on which codes are curated.
  const draftCountries = draft.target_countries || [];
  const draftRegions = new Set(draft.target_regions || []);
  const [selectedCountries, setSelectedCountries] = useState(
    new Set(draftCountries.filter((c) => CURATED_COUNTRY_CODES.has(c)))
  );
  const [otherCountries, setOtherCountries] = useState(
    draftCountries.filter((c) => !CURATED_COUNTRY_CODES.has(c)).join(", ")
  );
  const [selectedRegions, setSelectedRegions] = useState(() => {
    const initial = {};
    for (const country of CURATED_COUNTRIES) {
      initial[country.code] = new Set(country.regions.filter((r) => draftRegions.has(r.value)).map((r) => r.value));
    }
    return initial;
  });
  const [runHourUtc, setRunHourUtc] = useState(draft.run_hour_utc ?? 14);

  function toggleCountry(code) {
    setSelectedCountries((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code); else next.add(code);
      return next;
    });
  }

  function toggleRegion(countryCode, value) {
    setSelectedRegions((prev) => {
      const current = new Set(prev[countryCode] || []);
      if (current.has(value)) current.delete(value); else current.add(value);
      return { ...prev, [countryCode]: current };
    });
  }

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
        workday_boards: csv(workdayBoards),
        smartrecruiters_companies: csv(smartrecruitersCompanies),
        workable_accounts: csv(workableAccounts),
        recruitee_companies: csv(recruiteeCompanies),
        breezy_companies: csv(breezyCompanies),
        company_site_trackers: csv(companySiteTrackers),
        adzuna_country: adzunaCountry.trim().toLowerCase(),
        target_countries: [...selectedCountries, ...csv(otherCountries).map((c) => c.toLowerCase())],
        target_regions: [...selectedCountries].flatMap((code) => [...(selectedRegions[code] || [])]),
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
        <fieldset>
          <legend>Where you'll accept jobs</legend>
          <p className="hint">Pick every country you're open to. Leave provinces/states unchecked within a country to accept postings anywhere in it.</p>
          <div className="chip-input">
            {CURATED_COUNTRIES.map((country) => {
              const on = selectedCountries.has(country.code);
              return (
                <button
                  type="button" key={country.code}
                  className={`keyword-chip${on ? " on" : ""}`}
                  aria-pressed={on}
                  onClick={() => toggleCountry(country.code)}
                >
                  {on ? "✓ " : ""}{country.label}
                </button>
              );
            })}
          </div>
          {[...selectedCountries].map((code) => {
            const country = CURATED_COUNTRIES.find((c) => c.code === code);
            const picked = selectedRegions[code] || new Set();
            return (
              <details className="advanced" key={code}>
                <summary>
                  Narrow {country.label} down to specific provinces/states (optional)
                  {picked.size > 0 ? ` -- ${picked.size} selected` : ""}
                </summary>
                <div className="chip-input">
                  {country.regions.map((region) => {
                    const on = picked.has(region.value);
                    return (
                      <button
                        type="button" key={region.value}
                        className={`keyword-chip${on ? " on" : ""}`}
                        aria-pressed={on}
                        onClick={() => toggleRegion(code, region.value)}
                      >
                        {on ? "✓ " : ""}{region.label}
                      </button>
                    );
                  })}
                </div>
              </details>
            );
          })}
          <label>
            Other countries not listed above (optional, comma-separated country names)
            <input value={otherCountries} onChange={(e) => setOtherCountries(e.target.value)} placeholder="e.g. germany, ireland" />
          </label>
        </fieldset>

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
          {filteredPresets.map(([name, lane]) => {
            const selected = selectedPresets.has(name);
            const excluded = presetExcluded[name] || new Set();
            const total = meta.presets[name].keywords.length;
            const kept = total - excluded.size;
            return (
              <Fragment key={name}>
                <label className="lane-card">
                  <input type="checkbox" className="sr-only" checked={selected} onChange={() => togglePreset(name)} />
                  <span className="lane-card-check" aria-hidden="true">✓</span>
                  <span className="lane-card-icon">{LANE_ICONS[name] || "💼"}</span>
                  <div>
                    <div className="lane-card-title">{lane.label}</div>
                    <div className="lane-card-hint">{(meta.preset_blurbs || {})[name] || lane.keywords.join(", ")}</div>
                  </div>
                </label>
                {selected && (
                  <details className="advanced lane-card-details">
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
                )}
              </Fragment>
            );
          })}
        </div>

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
            Workday boards to search (comma-separated "host/tenant/site" entries, e.g. "workday.wd5.myworkdayjobs.com/workday/Workday")
            <input value={workdayBoards} onChange={(e) => setWorkdayBoards(e.target.value)} placeholder="Blank = source skipped" />
          </label>
          <label>
            SmartRecruiters companies to search (comma-separated, e.g. "Visa")
            <input value={smartrecruitersCompanies} onChange={(e) => setSmartrecruitersCompanies(e.target.value)} placeholder="Blank = source skipped" />
          </label>
          <label>
            Workable accounts to search (comma-separated subdomains)
            <input value={workableAccounts} onChange={(e) => setWorkableAccounts(e.target.value)} placeholder="Blank = source skipped" />
          </label>
          <label>
            Recruitee companies to search (comma-separated subdomains, e.g. "spreadgroup" for spreadgroup.recruitee.com)
            <input value={recruiteeCompanies} onChange={(e) => setRecruiteeCompanies(e.target.value)} placeholder="Blank = source skipped" />
          </label>
          <label>
            Breezy companies to search (comma-separated subdomains)
            <input value={breezyCompanies} onChange={(e) => setBreezyCompanies(e.target.value)} placeholder="Blank = source skipped" />
          </label>
          <label>
            Company career pages to track, no ATS needed (comma-separated "company name|https://company.com" entries -- discovers job pages via the company's own sitemap)
            <input value={companySiteTrackers} onChange={(e) => setCompanySiteTrackers(e.target.value)} placeholder='e.g. "Acme Inc|https://acme.com"' />
          </label>
          <label>
            Adzuna country code (2 letters, e.g. "ca" for Canada, "us" for United States)
            <input value={adzunaCountry} onChange={(e) => setAdzunaCountry(e.target.value)} maxLength={2} />
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
