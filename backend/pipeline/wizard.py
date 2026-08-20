"""Pure wizard business logic, ported from the old webapp/wizard.py. Deliberately drops
every filesystem-touching function from the original (profile_dir_for, profile_exists,
valid_username-as-slug-check, save_github_repo, write_profile_files) -- in the hosted
version "user" is a real DB user_id from a JWT-authenticated session, not a filesystem slug
someone types into a URL, and profile/resume data is written to Postgres (see
app/routes/wizard.py) instead of profile.yaml/resume_<lane>.json files. Everything below is
unchanged pure logic: lane presets, lane-dict assembly, profile-dict assembly, resume
splitting, and the PDF-import LLM structuring step."""

from __future__ import annotations

import json
import re
from datetime import date
from io import BytesIO

SOURCE_OPTIONS = [
    "adzuna", "hiring_cafe", "greenhouse", "lever", "ashby",
    "workday", "smartrecruiters", "workable", "recruitee", "breezy", "company_site",
]
REMOTE_TYPE_OPTIONS = ["remote", "hybrid", "onsite"]
EMPLOYMENT_TYPE_OPTIONS = ["full_time", "part_time", "contract"]

LANE_TEMPLATES = {
    "it_tech": {
        "name": "it_tech",
        "label": "IT / Tech Support",
        "resume": "resume_it_tech.json",
        "keywords": ["entry level", "junior", "IT support", "helpdesk", "QA", "backend"],
        "required_keywords": ["IT support", "helpdesk", "QA", "backend"],
        "seniority_max": "entry",
        "sources": ["adzuna", "hiring_cafe", "greenhouse", "lever", "ashby"],
        "synonym_groups": [["entry level", "junior"]],
        "relabel_titles_to_posting": True,
        "industries": [],
        "radius_km": None,
        "remote_types": [],
        "employment_types": [],
        "salary_min": None,
        "salary_max": None,
    },
    "ops_supervisor": {
        "name": "ops_supervisor",
        "label": "Retail / Food Service Supervisor",
        "resume": "resume_ops_supervisor.json",
        "keywords": ["shift lead", "supervisor", "assistant manager", "team lead"],
        "required_keywords": None,
        "seniority_max": None,
        "sources": ["adzuna", "hiring_cafe", "greenhouse"],
        "synonym_groups": [["shift lead", "supervisor", "assistant manager", "team lead"]],
        "relabel_titles_to_posting": False,
        "industries": ["retail", "food service", "hospitality"],
        "radius_km": 25.0,
        "remote_types": [],
        "employment_types": [],
        "salary_min": None,
        "salary_max": None,
    },
    "warehouse_logistics": {
        "name": "warehouse_logistics", "label": "Warehouse / Logistics", "resume": "resume_warehouse_logistics.json",
        "keywords": ["warehouse associate", "forklift", "picker", "packer", "logistics", "shipping and receiving", "material handler", "order picker", "inventory associate"],
        "required_keywords": None, "seniority_max": None, "sources": ["adzuna", "hiring_cafe", "greenhouse"],
        "industries": [], "radius_km": 25.0, "remote_types": [], "employment_types": [], "salary_min": None, "salary_max": None,
    },
    "retail_sales": {
        "name": "retail_sales", "label": "Retail / Sales Associate", "resume": "resume_retail_sales.json",
        "keywords": ["retail associate", "sales associate", "cashier", "sales representative", "store associate", "merchandiser"],
        "required_keywords": None, "seniority_max": None, "sources": ["adzuna", "hiring_cafe", "greenhouse"],
        "industries": ["retail"], "radius_km": 25.0, "remote_types": [], "employment_types": [], "salary_min": None, "salary_max": None,
    },
    "food_service": {
        "name": "food_service", "label": "Food Service / Hospitality", "resume": "resume_food_service.json",
        "keywords": ["cook", "server", "barista", "dishwasher", "line cook", "food service worker", "baker", "pastry chef", "prep cook"],
        "required_keywords": None, "seniority_max": None, "sources": ["adzuna", "hiring_cafe", "greenhouse"],
        "industries": ["food service", "hospitality"], "radius_km": 25.0, "remote_types": [], "employment_types": [], "salary_min": None, "salary_max": None,
    },
    "customer_service": {
        "name": "customer_service", "label": "Customer Service / Call Center", "resume": "resume_customer_service.json",
        "keywords": ["customer service representative", "call center", "customer support", "client services"],
        "required_keywords": None, "seniority_max": None, "sources": ["adzuna", "hiring_cafe", "greenhouse"],
        "industries": [], "radius_km": None, "remote_types": [], "employment_types": [], "salary_min": None, "salary_max": None,
    },
    "administrative": {
        "name": "administrative", "label": "Administrative / Office", "resume": "resume_administrative.json",
        "keywords": ["administrative assistant", "office assistant", "data entry", "receptionist", "office coordinator", "executive assistant", "office manager"],
        "required_keywords": None, "seniority_max": None, "sources": ["adzuna", "hiring_cafe", "greenhouse"],
        "industries": [], "radius_km": None, "remote_types": [], "employment_types": [], "salary_min": None, "salary_max": None,
    },
    "healthcare_support": {
        "name": "healthcare_support", "label": "Healthcare Support", "resume": "resume_healthcare_support.json",
        "keywords": ["personal support worker", "healthcare aide", "home care worker", "care aide", "nursing assistant", "caregiver", "medical assistant"],
        "required_keywords": None, "seniority_max": None, "sources": ["adzuna", "hiring_cafe", "greenhouse"],
        "industries": ["healthcare"], "radius_km": 25.0, "remote_types": [], "employment_types": [], "salary_min": None, "salary_max": None,
    },
    "skilled_trades": {
        "name": "skilled_trades", "label": "Skilled Trades", "resume": "resume_skilled_trades.json",
        "keywords": ["electrician", "plumber", "hvac technician", "welder", "mechanic", "carpenter", "painter", "roofer", "machinist"],
        "required_keywords": None, "seniority_max": None, "sources": ["adzuna", "hiring_cafe", "greenhouse"],
        "industries": [], "radius_km": 25.0, "remote_types": [], "employment_types": [], "salary_min": None, "salary_max": None,
    },
    "education_childcare": {
        "name": "education_childcare", "label": "Education / Childcare", "resume": "resume_education_childcare.json",
        "keywords": ["teacher", "teaching assistant", "early childhood educator", "tutor", "daycare", "nanny", "childcare worker", "substitute teacher"],
        "required_keywords": None, "seniority_max": None, "sources": ["adzuna", "hiring_cafe", "greenhouse"],
        "industries": ["education"], "radius_km": 25.0, "remote_types": [], "employment_types": [], "salary_min": None, "salary_max": None,
    },
    "general_labor": {
        "name": "general_labor", "label": "General Labor / Construction", "resume": "resume_general_labor.json",
        "keywords": ["general labourer", "construction worker", "landscaping", "groundskeeper", "laborer"],
        "required_keywords": None, "seniority_max": None, "sources": ["adzuna", "hiring_cafe", "greenhouse"],
        "industries": ["construction"], "radius_km": 25.0, "remote_types": [], "employment_types": [], "salary_min": None, "salary_max": None,
    },
    "delivery_driver": {
        "name": "delivery_driver", "label": "Delivery / Driver", "resume": "resume_delivery_driver.json",
        "keywords": ["delivery driver", "courier", "truck driver", "dispatcher", "delivery associate", "rideshare driver"],
        "required_keywords": None, "seniority_max": None, "sources": ["adzuna", "hiring_cafe", "greenhouse"],
        "industries": [], "radius_km": 25.0, "remote_types": [], "employment_types": [], "salary_min": None, "salary_max": None,
    },
    "manufacturing": {
        "name": "manufacturing", "label": "Manufacturing / Production", "resume": "resume_manufacturing.json",
        "keywords": ["production worker", "machine operator", "assembly line", "quality control inspector", "manufacturing technician"],
        "required_keywords": None, "seniority_max": None, "sources": ["adzuna", "hiring_cafe", "greenhouse"],
        "industries": ["manufacturing"], "radius_km": 25.0, "remote_types": [], "employment_types": [], "salary_min": None, "salary_max": None,
    },
    "accounting_finance": {
        "name": "accounting_finance", "label": "Accounting / Finance", "resume": "resume_accounting_finance.json",
        "keywords": ["accounting clerk", "bookkeeper", "accounts payable", "accounts receivable", "financial analyst", "accountant"],
        "required_keywords": None, "seniority_max": None, "sources": ["adzuna", "hiring_cafe", "greenhouse"],
        "industries": [], "radius_km": None, "remote_types": [], "employment_types": [], "salary_min": None, "salary_max": None,
    },
    "marketing_creative": {
        "name": "marketing_creative", "label": "Marketing / Creative", "resume": "resume_marketing_creative.json",
        "keywords": ["marketing coordinator", "social media", "graphic designer", "content writer", "marketing assistant", "copywriter", "digital marketing"],
        "required_keywords": None, "seniority_max": None, "sources": ["adzuna", "hiring_cafe", "greenhouse"],
        "industries": [], "radius_km": None, "remote_types": [], "employment_types": [], "salary_min": None, "salary_max": None,
    },
    "cleaning_janitorial": {
        "name": "cleaning_janitorial", "label": "Cleaning / Janitorial", "resume": "resume_cleaning_janitorial.json",
        "keywords": ["janitor", "custodian", "cleaner", "housekeeping", "maintenance worker", "porter"],
        "required_keywords": None, "seniority_max": None, "sources": ["adzuna", "hiring_cafe", "greenhouse"],
        "industries": [], "radius_km": 25.0, "remote_types": [], "employment_types": [], "salary_min": None, "salary_max": None,
    },
    "new_grad_coop": {
        "name": "new_grad_coop", "label": "New Grad / Co-op / Internship", "resume": "resume_new_grad_coop.json",
        "keywords": ["intern", "internship", "co-op", "coop", "new grad", "new graduate", "graduate program", "entry level"],
        "required_keywords": None, "seniority_max": "intern", "max_years_experience": 1,
        "sources": ["adzuna", "hiring_cafe", "greenhouse", "lever", "ashby"],
        "synonym_groups": [["co-op", "coop"], ["new grad", "new graduate"]],
        "relabel_titles_to_posting": True,
        "industries": [], "radius_km": None, "remote_types": [], "employment_types": [], "salary_min": None, "salary_max": None,
    },
}

LANE_TEMPLATE_BLURBS = {
    "it_tech": "Help desk, tech support, QA, and junior/entry-level software roles.",
    "ops_supervisor": "Shift lead, supervisor, and assistant manager roles in retail or food service.",
    "warehouse_logistics": "Warehouse, forklift, picking/packing, and shipping & receiving.",
    "retail_sales": "Store associate, cashier, and sales representative roles.",
    "food_service": "Cooks, servers, baristas, and other restaurant/food service roles.",
    "customer_service": "Phone/chat support, call center, and client service roles.",
    "administrative": "Office assistant, data entry, receptionist, and coordinator roles.",
    "healthcare_support": "Personal support worker, home care, and healthcare aide roles.",
    "skilled_trades": "Electrician, plumber, HVAC, welding, and mechanic roles.",
    "education_childcare": "Teaching, tutoring, and early childhood education roles.",
    "general_labor": "Construction, landscaping, and general labor roles.",
    "delivery_driver": "Delivery driver, courier, and truck driving roles.",
    "manufacturing": "Production, machine operator, and assembly line roles.",
    "accounting_finance": "Bookkeeping, accounts payable/receivable, and financial analyst roles.",
    "marketing_creative": "Marketing, social media, design, and content roles.",
    "cleaning_janitorial": "Janitorial, custodial, and housekeeping roles.",
    "new_grad_coop": "Internships, co-ops, and new-grad roles across any field, capped at 1 year of required experience.",
}

DEFAULT_GREENHOUSE_BOARDS = ["gitlab", "doordashusa", "robinhood", "figma", "faire", "stripe", "discord", "airbnb"]
DEFAULT_LEVER_COMPANIES = ["palantir", "plaid"]
DEFAULT_ASHBY_BOARDS = ["ramp", "linear", "notion", "openai", "substack"]


class WizardError(ValueError):
    """Raised when submitted wizard data fails validation."""


def _slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    return slug or "custom"


def _finalize_lane_dict(base: dict) -> dict:
    lane_dict = {
        "name": base["name"],
        "resume": base["resume"],
        "keywords": base["keywords"],
        "sources": base["sources"],
    }
    for optional_key in (
        "seniority_max", "max_years_experience", "industries", "synonym_groups", "required_keywords",
        "radius_km", "remote_types", "employment_types", "salary_min", "salary_max", "min_match_score",
    ):
        if base.get(optional_key):
            lane_dict[optional_key] = base[optional_key]
    if base.get("relabel_titles_to_posting"):
        lane_dict["relabel_titles_to_posting"] = True
    return lane_dict


def resolve_preset_lane(lane_name: str, overrides: dict | None = None) -> dict:
    if lane_name not in LANE_TEMPLATES:
        raise WizardError(f"Unknown lane preset: {lane_name!r}")
    base = dict(LANE_TEMPLATES[lane_name])
    base.update(overrides or {})
    return _finalize_lane_dict(base)


def build_custom_lane(
    label: str,
    keywords: list[str],
    radius_km: float | None = None,
    sources: list[str] | None = None,
    remote_types: list[str] | None = None,
    employment_types: list[str] | None = None,
    salary_min: float | None = None,
    salary_max: float | None = None,
    required_keywords: list[str] | None = None,
    seniority_max: str | None = None,
    max_years_experience: int | None = None,
    industries: list[str] | None = None,
    min_match_score: float | None = None,
) -> dict:
    if not label.strip():
        raise WizardError("Custom job type needs a name.")
    if not keywords:
        raise WizardError(f"Custom job type {label!r} needs at least one keyword.")
    name = _slugify(label)
    base = {
        "name": name,
        "resume": f"resume_{name}.json",
        "keywords": keywords,
        "sources": sources or list(SOURCE_OPTIONS),
        "radius_km": radius_km,
        "remote_types": remote_types or [],
        "employment_types": employment_types or [],
        "salary_min": salary_min,
        "salary_max": salary_max,
        "required_keywords": required_keywords,
        "seniority_max": seniority_max,
        "max_years_experience": max_years_experience,
        "industries": industries or [],
        "min_match_score": min_match_score,
    }
    return _finalize_lane_dict(base)


def build_profile_yaml_dict(
    *,
    user: str,
    applicant: dict,
    lanes: list[dict],
    greenhouse_boards: list[str],
    adzuna_country: str,
    sheet_id: str,
    gmail_address: str,
    report_email: str,
    lever_companies: list[str] | None = None,
    ashby_boards: list[str] | None = None,
    workday_boards: list[str] | None = None,
    smartrecruiters_companies: list[str] | None = None,
    workable_accounts: list[str] | None = None,
    recruitee_companies: list[str] | None = None,
    breezy_companies: list[str] | None = None,
    company_site_trackers: list[str] | None = None,
    target_countries: list[str] | None = None,
    target_regions: list[str] | None = None,
    apply_daily_cap: int = 15,
    cold_email_week1: int = 5,
    cold_email_week3plus: int = 12,
) -> dict:
    if not lanes:
        raise WizardError("Pick at least one lane.")

    return {
        "user": user,
        "sheet_id": sheet_id,
        "gmail_address": gmail_address,
        "report_email": report_email,
        "applicant": applicant,
        "lanes": lanes,
        "greenhouse_boards": greenhouse_boards or list(DEFAULT_GREENHOUSE_BOARDS),
        "lever_companies": lever_companies or list(DEFAULT_LEVER_COMPANIES),
        "ashby_boards": ashby_boards or list(DEFAULT_ASHBY_BOARDS),
        # No lane preset ships a default company for these -- unlike greenhouse/lever/
        # ashby, they're opt-in board lists a user has to actually type in, empty until
        # then (run_pipeline.py skips a source with no boards configured, same as
        # before promotion).
        "workday_boards": workday_boards or [],
        "smartrecruiters_companies": smartrecruiters_companies or [],
        "workable_accounts": workable_accounts or [],
        "recruitee_companies": recruitee_companies or [],
        "breezy_companies": breezy_companies or [],
        "company_site_trackers": company_site_trackers or [],
        "adzuna_country": adzuna_country or "ca",
        "target_countries": target_countries or [adzuna_country or "ca"],
        "target_regions": target_regions or [],
        "cold_email": {
            "daily_cap_week1": cold_email_week1,
            "daily_cap_week3plus": cold_email_week3plus,
            "ramp_start_date": date.today().isoformat(),
        },
        "apply_daily_cap": apply_daily_cap,
    }


def build_resume_json(shared: dict, lane_name: str, all_lane_names: list[str]) -> dict:
    other_lanes = set(all_lane_names) - {lane_name}

    def _strip(entry: dict) -> dict:
        return {k: v for k, v in entry.items() if k != "lanes"}

    experience = shared.get("experience", [])
    relevant = [_strip(e) for e in experience if lane_name in e.get("lanes", [])]
    additional = [
        _strip(e) for e in experience
        if lane_name not in e.get("lanes", []) and not (set(e.get("lanes", [])) & other_lanes)
    ]

    skills = {
        cat["name"]: cat["items"]
        for cat in shared.get("skills", [])
        if not cat.get("lanes") or lane_name in cat["lanes"]
    }
    projects = [
        _strip(p) for p in shared.get("projects", [])
        if not p.get("lanes") or lane_name in p["lanes"]
    ]

    resume = {
        "name": shared["name"],
        "contact": shared["contact"],
        "education": shared.get("education", []),
        "experience": {"relevant": relevant, "additional": additional},
        "skills": skills,
        "interests": shared.get("interests", []),
    }
    if projects:
        resume["projects"] = projects
    return resume


RESUME_IMPORT_SYSTEM_PROMPT = """You extract structured data from raw resume text pasted \
from a PDF. Output STRICT JSON only -- no markdown, no code fences, no commentary -- matching \
exactly this shape:

{
  "name": "", "phone": "", "email": "", "website": "",
  "education": [{"institution": "", "location": "", "credential": "", "gpa": "", "dates": "", "highlights": []}],
  "experience": [{"company": "", "title": "", "location": "", "dates": "", "bullets": []}],
  "skills": [{"name": "", "items": []}],
  "projects": [{"name": "", "description": "", "bullets": []}],
  "interests": []
}

Hard rules:
- Extract only what is actually present in the text. Never invent a company, title, date, \
bullet, skill, or number that isn't there.
- "bullets"/"highlights" are one entry per actual bullet/line in the source, not merged or split.
- If a section (education, projects, interests, gpa, etc.) isn't present in the text, use an \
empty list/string for it rather than guessing.
- "skills" groups related skills under a short category name (e.g. "Languages", "Tools") the \
way the source resume already groups them; if the source has one flat skills list with no \
categories, use a single category named "Skills".
- Preserve the person's own wording for bullets/descriptions verbatim -- do not reword, \
summarize, or improve anything."""


def extract_pdf_text(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def structure_resume_with_llm(api_key: str, raw_text: str) -> dict:
    from pipeline.writing_style import DEFAULT_MODEL_FALLBACKS, generate_with_gemini

    if not raw_text.strip():
        raise ValueError("Couldn't read any text from that PDF -- it may be a scanned image rather than real text.")

    raw = generate_with_gemini(
        api_key, DEFAULT_MODEL_FALLBACKS, RESUME_IMPORT_SYSTEM_PROMPT, raw_text, max_output_tokens=4096,
    )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Couldn't understand the extracted resume data -- try filling it in by hand instead.") from exc

    for entry in parsed.get("experience", []):
        entry["lanes"] = []
    for entry in parsed.get("skills", []):
        entry["lanes"] = []
    for entry in parsed.get("projects", []):
        entry["lanes"] = []
    return parsed
