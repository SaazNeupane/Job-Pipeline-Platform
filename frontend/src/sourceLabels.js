// Plain names for the raw source ids the backend logs -- "hiring_cafe" means
// nothing to a non-technical user reading a badge on a job card. Shared by
// Dashboard and Swipe (both show the same compact per-card badge); Lanes'
// own picker uses longer descriptive labels for a different purpose
// (choosing where to search, not just labeling a result).
export const SOURCE_LABELS = {
  adzuna: "Adzuna", hiring_cafe: "Hiring Cafe", greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby",
  workday: "Workday", smartrecruiters: "SmartRecruiters", workable: "Workable", recruitee: "Recruitee",
  breezy: "Breezy", company_site: "Company site",
};
export const sourceLabel = (s) => SOURCE_LABELS[s] || s;
