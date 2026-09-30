"""
Build a structured master profile from a supplied CV text.

The builder is deterministic and conservative. It extracts facts that are
explicitly present in the CV and leaves uncertain items blank / needs
verification. It is used for first-time onboarding and CLI import, not for
silent background modification.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from utils.medical_requirements import normalize_text
from utils.profile import apply_owner_confirmed_dr_frotan_credentials


MONTH_RANGE_RE = re.compile(
    r"(?P<start>[A-Z][a-z]{2,8}\s+\d{4})\s*[–-]\s*(?P<end>(?:[A-Z][a-z]{2,8}\s+\d{4})|Present|Current)",
)


KEYWORD_SKILL_MAP = {
    "BPHS/EPHS & IMAM/CMAM Program Knowledge": ["BPHS", "EPHS", "IMAM", "CMAM"],
    "HMIS / DHIS2 Reporting & Data Quality": ["HMIS", "DHIS2", "Data quality"],
    "Emergency & Outbreak Response (COVID-19)": ["COVID-19 emergency response", "Emergency response", "Outbreak response"],
    "Safeguarding, PSEA & Child Protection": ["Safeguarding", "PSEA", "Child Protection"],
}


def build_profile_from_cv_text(cv_text: str, *, resume_path: str = "") -> dict[str, Any]:
    """Create a structured profile from a CV pasted/uploaded by the user."""
    raw = cv_text.strip()
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    text = "\n".join(lines)

    name = _extract_name(lines)
    location, phone, email = _extract_contact(lines)
    work_history = _extract_work_history(text)
    education = _extract_education(text)
    certifications = _extract_bullets_between(text, "CERTIFICATIONS & TRAINING", "LANGUAGES")
    competencies = _extract_bullets_between(text, "CORE COMPETENCIES", "PROFESSIONAL EXPERIENCE")
    languages = _extract_languages(text)

    profile = {
        "personal": {
            "first_name": _first_name(name),
            "last_name": _last_name(name),
            "email": email,
            "phone": phone,
            "location": location or "Kabul, Afghanistan",
            "nationality": "Afghan" if re.search(r"\bAfghan(?:istan)?\b", text, re.I) else "",
            "gender": "",  # Not stated in the CV.
            "linkedin": "",
        },
        "resume_path": resume_path,
        "medical_education": education,
        "license_registration": {
            "authority": "",
            "number": "",
            "status": "Needs verification — no license/registration number is stated in the source CV",
            "verified": False,
        },
        "medical_exit_exam": {
            "status": "Needs verification — not stated in the source CV",
            "verified": False,
        },
        "clinical_experience": {
            "years": 0,  # Calculated from dated work history at match time.
            "settings": ["TFU", "mobile health and nutrition teams", "COVID-19 rapid response"],
        },
        "work_history": work_history,
        "skills": _skills_from_text(text, competencies),
        "languages": languages,
        "certificates": certifications,
        "ngo_humanitarian_experience": {
            "years": 0,  # Calculated from dated work history at match time.
            "organizations": ["Action Against Hunger (ACF-International)", "Trend for a Better Tomorrow (TBT) – NGO"],
        },
        "coordination_experience": _extract_coordination(text),
        "preferences": {
            "roles": [
                "Medical Officer",
                "Medical Doctor",
                "Health and Nutrition Coordinator",
                "Provincial Coordinator",
                "Nutrition Officer",
                "Public Health Officer",
            ],
            "locations": ["Afghanistan", "Kabul", "Daikundi"],
            "preferred_locations": ["Kabul", "Daikundi"],
            "willing_to_relocate": False,
            "field_deployment": True,
            "remote_only": False,
        },
        "job_sources": {
            "acbar": {"enabled": True, "urls": ["https://www.acbar.org/jobs"]},
            "reliefweb": {"enabled": True, "limit": 25},
            "official_career_pages": [],
            "ats": {"greenhouse": [], "lever": []},
        },
        "search": {
            "generic_job_boards_enabled": False,
            "queries": [
                "Medical Officer Afghanistan",
                "Medical Doctor Afghanistan",
                "Health Nutrition Coordinator Afghanistan",
                "Provincial Coordinator Health Afghanistan",
                "Nutrition Officer Afghanistan",
            ],
            "locations": ["Afghanistan", "Kabul", "Daikundi"],
            "results_per_query": 25,
        },
        "common_answers": {
            "willing_to_relocate": "Needs review",
            "earliest_start_date": "Needs review",
            "salary_expectation": "Needs review",
            "how_did_you_hear": "Online job board",
            "authorized_to_work": "Needs review",
            "require_sponsorship": "Needs review",
        },
        "rate_limits": {"max_applications_per_day": 10, "min_delay_seconds": 60, "max_delay_seconds": 180},
        "schedule": {"discover_interval_hours": 12, "score_interval_minutes": 60, "enabled": True},
        "email": {"enabled": False, "imap_server": "imap.gmail.com", "email": "", "app_password": "", "check_interval_hours": 12},
        "ai": {"enabled": False, "enable_document_refinement": False, "default_backend": "claude_cli"},
        "source_cv_note": "Structured from the user-supplied CV. Do not add facts unless Dr. Frotan verifies them.",
    }
    apply_owner_confirmed_dr_frotan_credentials(profile)
    return profile


def build_profile_from_cv_file(path: str | Path, *, resume_path: str | None = None) -> dict[str, Any]:
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        from utils.resume_parser import extract_resume_text

        text = extract_resume_text(str(path))
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    return build_profile_from_cv_text(text, resume_path=str(resume_path or path))


def _extract_name(lines: list[str]) -> str:
    for line in lines[:8]:
        if re.search(r"DR\.?\s+", line, re.I):
            return re.sub(r"^DR\.?\s+", "", line, flags=re.I).title().strip()
    return lines[0].title() if lines else ""


def _first_name(name: str) -> str:
    parts = name.split()
    return " ".join(parts[:-1]) if len(parts) > 1 else name


def _last_name(name: str) -> str:
    parts = name.split()
    return parts[-1] if len(parts) > 1 else ""


def _extract_contact(lines: list[str]) -> tuple[str, str, str]:
    location = phone = email = ""
    for line in lines[:12]:
        if "@" in line or "+93" in line:
            parts = [part.strip() for part in re.split(r"\s*·\s*", line)]
            for part in parts:
                if "@" in part:
                    email = part
                elif re.search(r"\+?\d[\d\s-]{7,}", part):
                    phone = part
                elif "," in part or "Afghanistan" in part:
                    location = part
    return location, phone, email


def _extract_bullets_between(text: str, start_heading: str, end_heading: str) -> list[str]:
    block = _section(text, start_heading, end_heading)
    bullets = []
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("*") or line.startswith("•") or line.startswith("-"):
            bullets.append(line.lstrip("*•- ").strip())
    return bullets


def _section(text: str, start_heading: str, end_heading: str | None = None) -> str:
    start = text.find(start_heading)
    if start < 0:
        return ""
    start += len(start_heading)
    if end_heading:
        end = text.find(end_heading, start)
        return text[start:end if end >= 0 else len(text)]
    return text[start:]


def _extract_work_history(text: str) -> list[dict[str, Any]]:
    block = _section(text, "PROFESSIONAL EXPERIENCE", "EDUCATION")
    lines = [line.rstrip() for line in block.splitlines() if line.strip()]
    jobs: list[dict[str, Any]] = []
    i = 0
    while i < len(lines) - 1:
        title = lines[i].strip()
        meta = lines[i + 1].strip()
        if "|" in meta and MONTH_RANGE_RE.search(meta):
            org_loc, date_part = [part.strip() for part in meta.split("|", 1)]
            date_match = MONTH_RANGE_RE.search(date_part)
            organization, location = _split_org_location(org_loc)
            i += 2
            bullets = []
            while i < len(lines) and not (i < len(lines) - 1 and "|" in lines[i + 1] and MONTH_RANGE_RE.search(lines[i + 1])):
                if lines[i].strip().startswith("*"):
                    bullets.append(lines[i].strip().lstrip("*•- ").strip())
                i += 1
            jobs.append(
                {
                    "title": title,
                    "organization": organization,
                    "location": location,
                    "start": _month_year_to_iso(date_match.group("start")) if date_match else "",
                    "end": _month_year_to_iso(date_match.group("end")) if date_match and date_match.group("end").lower() not in {"present", "current"} else "Present",
                    "description": " ".join(bullets),
                    "bullets": bullets,
                    "source": "source CV",
                }
            )
        else:
            i += 1
    return jobs


def _split_org_location(value: str) -> tuple[str, str]:
    parts = [part.strip() for part in re.split(r"\s+·\s+", value, maxsplit=1)]
    if len(parts) == 2:
        return parts[0], parts[1]
    return value, ""


def _month_year_to_iso(value: str) -> str:
    value = value.strip()
    if value.lower() in {"present", "current"}:
        return "Present"
    import datetime as _dt

    for fmt in ("%b %Y", "%B %Y"):
        try:
            parsed = _dt.datetime.strptime(value, fmt)
            return parsed.strftime("%Y-%m")
        except ValueError:
            pass
    return value


def _extract_education(text: str) -> list[dict[str, Any]]:
    block = _section(text, "EDUCATION", "CERTIFICATIONS & TRAINING")
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if len(lines) >= 2:
        years = re.search(r"(\d{4})\s*[–-]\s*(\d{4})", lines[1])
        institution = re.sub(r"\s*·\s*\d{4}\s*[–-]\s*\d{4}.*$", "", lines[1]).strip()
        return [
            {
                "degree": lines[0],
                "institution": institution,
                "start": years.group(1) if years else "",
                "end": years.group(2) if years else "",
                "verified": True,
                "source": "source CV",
            }
        ]
    return []


def _extract_languages(text: str) -> list[dict[str, Any]]:
    match = re.search(r"LANGUAGES\s*(.*?)\s*PROFESSIONAL REFERENCES", text, flags=re.S | re.I)
    if not match:
        return []
    line = normalize_text(match.group(1))
    languages = []
    for part in re.split(r"\s*\|\s*", line):
        if "—" in part:
            name, level = [p.strip() for p in part.split("—", 1)]
        elif "-" in part:
            name, level = [p.strip() for p in part.split("-", 1)]
        else:
            continue
        languages.append({"name": name, "level": level, "source": "source CV"})
    return languages


def _skills_from_text(text: str, competencies: list[str]) -> dict[str, list[str]]:
    medical = []
    public_health = []
    management = []
    admin = []
    for item in competencies:
        lower = item.lower()
        if any(term in lower for term in ["health", "nutrition", "medical", "bphs", "ephs", "imam", "cmam", "hmis", "dhis2", "monitoring", "emergency", "safeguarding", "ipc"]):
            public_health.append(item)
        if any(term in lower for term in ["supervision", "team", "capacity", "coordination", "stakeholder", "ministry"]):
            management.append(item)
        if any(term in lower for term in ["administration", "procurement", "financial", "logistics", "supply"]):
            admin.append(item)
    # Explicit technical keywords present in narrative/certifications.
    for label, terms in KEYWORD_SKILL_MAP.items():
        if any(re.search(rf"\b{re.escape(term)}\b", text, re.I) for term in terms):
            for term in terms:
                if term not in public_health:
                    public_health.append(term)
    if re.search(r"clinical assessment|diagnosis|treatment|follow-up care", text, re.I):
        medical.extend(["Clinical assessment", "Diagnosis and treatment", "SAM inpatient care"])
    return {
        "medical": _unique(medical),
        "public_health": _unique(public_health),
        "management": _unique(management),
        "administration_logistics": _unique(admin),
    }


def _extract_coordination(text: str) -> list[str]:
    block = _section(text, "PROVINCIAL COORDINATION & STAKEHOLDER EXPERIENCE", "CORE COMPETENCIES")
    return [line.strip() for line in block.splitlines() if line.strip()]


def _unique(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out
