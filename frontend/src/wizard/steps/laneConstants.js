export const emptyCustomLane = () => ({
  id: crypto.randomUUID(),
  label: "", keywords: "", required_keywords: "", seniority_max: "", max_years_experience: "", industries: "",
  inPerson: false, radius_km: "",
  sources: null, // null = all real sources (backend default)
  remote_types: [], employment_types: [],
  salary_min: "", salary_max: "", min_match_score: "",
});

export function csv(s) {
  return s.split(",").map((v) => v.trim()).filter(Boolean);
}

export function toggleInArray(arr, value) {
  return arr.includes(value) ? arr.filter((v) => v !== value) : [...arr, value];
}

// Plain names for the raw source ids the backend uses -- "hiring_cafe"/
// "greenhouse" mean nothing to a non-technical user filling this in.
export const SOURCE_LABELS = {
  adzuna: "Adzuna (general job search)",
  hiring_cafe: "Hiring Cafe (general job search)",
  greenhouse: "Greenhouse (startup/tech company job boards)",
  lever: "Lever (startup/tech company job boards)",
  ashby: "Ashby (startup/tech company job boards)",
  workday: "Workday (enterprise company job boards)",
  smartrecruiters: "SmartRecruiters (company job boards)",
  workable: "Workable (company job boards)",
  recruitee: "Recruitee (company job boards)",
  breezy: "Breezy (company job boards)",
  company_site: "Company career pages (sitemap-discovered, no ATS needed)",
};

// One small icon per built-in preset, purely decorative -- breaks up what
// was a plain stacked checkbox list into something that reads faster at a
// glance. A lane not in this map (shouldn't happen for a built-in preset,
// but stay safe) just gets a generic briefcase.
export const LANE_ICONS = {
  it_tech: "💻", ops_supervisor: "🧑‍💼", warehouse_logistics: "📦", retail_sales: "🛍️",
  food_service: "🍳", customer_service: "🎧", administrative: "🗂️", healthcare_support: "🩺",
  skilled_trades: "🔧", education_childcare: "🎓", general_labor: "🏗️", delivery_driver: "🚚",
  manufacturing: "⚙️", accounting_finance: "💰", marketing_creative: "🎨", cleaning_janitorial: "🧹",
  new_grad_coop: "🎓",
};

// Only the countries pipeline/filter.py's COUNTRY_LOCATION_ALIASES actually curates
// province/state-level matching for -- picking anything outside this list falls back to
// "Other" (a plain free-text country name/code), same fail-open-to-freetext behavior the
// old all-free-text inputs always had. Region `value`s are exactly what
// COUNTRY_LOCATION_ALIASES matches against (lowercase abbreviation or full name) -- GB has
// no abbreviation tier for its four nations, so those use their full name as the value.
export const CURATED_COUNTRIES = [
  {
    code: "ca", label: "Canada",
    regions: [
      { value: "on", label: "Ontario" }, { value: "bc", label: "British Columbia" },
      { value: "ab", label: "Alberta" }, { value: "qc", label: "Quebec" },
      { value: "mb", label: "Manitoba" }, { value: "sk", label: "Saskatchewan" },
      { value: "ns", label: "Nova Scotia" }, { value: "nb", label: "New Brunswick" },
      { value: "nl", label: "Newfoundland and Labrador" }, { value: "pe", label: "Prince Edward Island" },
      { value: "yt", label: "Yukon" }, { value: "nt", label: "Northwest Territories" },
      { value: "nu", label: "Nunavut" },
    ],
  },
  {
    code: "us", label: "United States",
    regions: [
      { value: "al", label: "Alabama" }, { value: "ak", label: "Alaska" }, { value: "az", label: "Arizona" },
      { value: "ar", label: "Arkansas" }, { value: "ca", label: "California" }, { value: "co", label: "Colorado" },
      { value: "ct", label: "Connecticut" }, { value: "de", label: "Delaware" }, { value: "dc", label: "District of Columbia" },
      { value: "fl", label: "Florida" }, { value: "ga", label: "Georgia" }, { value: "hi", label: "Hawaii" },
      { value: "id", label: "Idaho" }, { value: "il", label: "Illinois" }, { value: "in", label: "Indiana" },
      { value: "ia", label: "Iowa" }, { value: "ks", label: "Kansas" }, { value: "ky", label: "Kentucky" },
      { value: "la", label: "Louisiana" }, { value: "me", label: "Maine" }, { value: "md", label: "Maryland" },
      { value: "ma", label: "Massachusetts" }, { value: "mi", label: "Michigan" }, { value: "mn", label: "Minnesota" },
      { value: "ms", label: "Mississippi" }, { value: "mo", label: "Missouri" }, { value: "mt", label: "Montana" },
      { value: "ne", label: "Nebraska" }, { value: "nv", label: "Nevada" }, { value: "nh", label: "New Hampshire" },
      { value: "nj", label: "New Jersey" }, { value: "nm", label: "New Mexico" }, { value: "ny", label: "New York" },
      { value: "nc", label: "North Carolina" }, { value: "nd", label: "North Dakota" }, { value: "oh", label: "Ohio" },
      { value: "ok", label: "Oklahoma" }, { value: "or", label: "Oregon" }, { value: "pa", label: "Pennsylvania" },
      { value: "ri", label: "Rhode Island" }, { value: "sc", label: "South Carolina" }, { value: "sd", label: "South Dakota" },
      { value: "tn", label: "Tennessee" }, { value: "tx", label: "Texas" }, { value: "ut", label: "Utah" },
      { value: "vt", label: "Vermont" }, { value: "va", label: "Virginia" }, { value: "wa", label: "Washington" },
      { value: "wv", label: "West Virginia" }, { value: "wi", label: "Wisconsin" }, { value: "wy", label: "Wyoming" },
    ],
  },
  {
    code: "gb", label: "United Kingdom",
    regions: [
      { value: "england", label: "England" }, { value: "scotland", label: "Scotland" },
      { value: "wales", label: "Wales" }, { value: "northern ireland", label: "Northern Ireland" },
    ],
  },
  {
    code: "au", label: "Australia",
    regions: [
      { value: "nsw", label: "New South Wales" }, { value: "vic", label: "Victoria" },
      { value: "qld", label: "Queensland" }, { value: "wa", label: "Western Australia" },
      { value: "sa", label: "South Australia" }, { value: "tas", label: "Tasmania" },
      { value: "act", label: "Australian Capital Territory" }, { value: "nt", label: "Northern Territory" },
    ],
  },
];
export const CURATED_COUNTRY_CODES = new Set(CURATED_COUNTRIES.map((c) => c.code));

export const SENIORITY_LABELS = {
  intern: "Internship only",
  entry: "Entry-level only",
  intermediate: "Up to intermediate/mid-level",
  senior: "Up to senior (no cap in practice)",
};
