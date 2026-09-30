"""
Profile loading and deterministic evidence extraction.

The profile YAML is the single source of truth for user-provided facts.  CV text
can add evidence for matching, but these helpers never write inferred facts back
to profile.yaml.  Missing information remains missing and is reported as
"Needs verification" by the matcher.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from utils.medical_requirements import MONTHS, NUMBER_WORDS, normalize_text


@dataclass
class EvidenceItem:
    key: str
    value: Any
    source: str
    quote: str = ""
    verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProfileEvidence:
    items: dict[str, list[EvidenceItem]] = field(default_factory=dict)
    raw_profile: dict[str, Any] = field(default_factory=dict)

    def add(self, key: str, value: Any, source: str, quote: str = "", verified: bool = False) -> None:
        if value in (None, "", [], {}):
            return
        evidence = EvidenceItem(key=key, value=value, source=source, quote=str(quote or value), verified=verified)
        bucket = self.items.setdefault(key, [])
        # Avoid exact duplicates.
        if not any(item.value == evidence.value and item.source == evidence.source for item in bucket):
            bucket.append(evidence)

    def has(self, key: str) -> bool:
        return bool(self.items.get(key))

    def values(self, key: str) -> list[Any]:
        return [item.value for item in self.items.get(key, [])]

    def first(self, key: str, default: Any = None) -> Any:
        values = self.values(key)
        return values[0] if values else default

    def evidence_text(self, key: str) -> list[str]:
        return [item.quote for item in self.items.get(key, []) if item.quote]

    def to_dict(self) -> dict[str, Any]:
        return {key: [item.to_dict() for item in items] for key, items in self.items.items()}


MEDICAL_TERM_KEYS = {
    "bphs": [r"\bBPHS\b", r"Basic Package of Health Services"],
    "ephs": [r"\bEPHS\b", r"Essential Package of Hospital Services"],
    "phc": [r"\bPHC\b", r"primary health\s*care"],
    "hmis": [r"\bHMIS\b", r"\bDHIS2\b", r"DHIS\s*2", r"health management information system"],
    "imnci": [r"\bIMNCI\b"],
    "imam": [r"\bIMAM\b", r"\bCMAM\b", r"integrated management of acute malnutrition", r"community(?:-based)? management of acute malnutrition"],
    "nutrition": [r"\bnutrition(?:al)?\b", r"\bmalnutrition\b", r"\bIYCF\b", r"\bSAM\b", r"\bMAM\b", r"\bOTP\b", r"\bTFU\b"],
    "srhr": [r"\bSRHR\b", r"sexual and reproductive health", r"reproductive health"],
    "ipc": [r"\bIPC\b", r"infection prevention", r"infection control"],
    "medical_exit_exam": [r"\bexit\s+exam(?:ination)?\b", r"\bmedical\s+council\s+exam(?:ination)?\b", r"ایگزیت\s*امتحان", r"امتحان\s+شورای\s+طبی"],
    "medical_specialist": [r"\binternal\s+medicine\s+specialist\b", r"\bgeneral\s+surgeon\b", r"\bsurgeon\s+specialist\b", r"\bdermatolog(?:y|ist)\b", r"\baesthetic\s+medicine\b"],
    "specialist_obgyn": [r"obstetrician[-/\s]*gynecologist", r"\bobgyn\b", r"\bgynecology\b"],
    "pharmacy_degree": [r"\bB\.?Sc\.?\s+in\s+Pharmacy\b", r"\bBachelor(?:'s)?\s+degree\s+in\s+pharmacy\b", r"\bPharm\s*D\b", r"\bpharmacy\s+degree\b"],
    "nursing_midwifery_certificate": [r"\bnursing\s*/\s*midwifery\s+certificate\b", r"\bnursing\s+certificate\b", r"\bmidwifery\s+certificate\b", r"\bdiploma\s+in\s+(?:nursing|midwifery)\b"],
    "pediatric_specialist": [r"\bspecial(?:ty|ist)\s+degree\s*\(?\s*pediatrics\s*\)?", r"\bpediatric(?:s)?\s+specialist\b", r"\bspeciali[sz]ation\s+in\s+pediatric(?:s)?\b"],
    "ngo_humanitarian": [r"\bNGO\b", r"\bINGO\b", r"humanitarian", r"emergency response"],
    "reporting": [r"\breporting\b", r"monthly reports", r"prepare reports"],
    "supervision_management": [r"\bsupervis(?:e|ion|ory)\b", r"\bmanage(?:ment|r| team)?\b", r"team lead"],
    "afghanistan_experience": [r"\bAfghanistan\b", r"\bAfghan\b", r"\bMoPH\b", r"Ministry of Public Health"],
    "moph_coordination": [r"\bMoPH\b", r"Ministry of Public Health", r"provincial public health", r"health authorit(?:y|ies)"],
    "safeguarding_psea": [r"\bsafeguarding\b", r"\bPSEA\b", r"protection from sexual exploitation", r"child protection"],
    "emergency_response": [r"emergency response", r"outbreak", r"COVID-?19", r"rapid response", r"contact tracing"],
    "supply_logistics": [r"medical supply", r"stock (?:management|monitoring)", r"forecasting", r"logistics", r"procurement"],
}

LANGUAGE_ALIASES = {
    "english": ["english"],
    "dari": ["dari"],
    "pashto": ["pashto", "pushto"],
}

OWNER_CONFIRMED_DR_FROTAN_CREDENTIAL_DATE = "2026-09-30"


def is_dr_frotan_profile(profile: dict[str, Any]) -> bool:
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    full_name = f"{personal.get('first_name', '')} {personal.get('last_name', '')}".strip().lower()
    return full_name == "allah yar frotan"


def apply_owner_confirmed_dr_frotan_credentials(profile: dict[str, Any]) -> dict[str, Any]:
    """Apply Dr. Frotan's owner-confirmed medical credentials in-place.

    This verifies completion/validity only. It deliberately does not add or
    fabricate license number, registration number, issue date, expiry date,
    certificate number, or document fields. Existing explicit number/document
    values are preserved if the user later adds them to the profile.
    """
    if not is_dr_frotan_profile(profile):
        return profile

    existing_license = profile.get("license_registration") if isinstance(profile.get("license_registration"), dict) else {}
    license_data = dict(existing_license or {})
    license_data["authority"] = license_data.get("authority") or "Afghan Medical Council / medical professional registration"
    license_data.setdefault("number", "")
    license_data["status"] = "Verified — holds valid medical professional registration/license"
    license_data["verified"] = True
    license_data["source"] = license_data.get("source") or f"owner-confirmed on {OWNER_CONFIRMED_DR_FROTAN_CREDENTIAL_DATE}"
    profile["license_registration"] = license_data

    existing_exam = profile.get("medical_exit_exam") if isinstance(profile.get("medical_exit_exam"), dict) else {}
    exam_data = dict(existing_exam or {})
    exam_data["status"] = "Verified — completed the required Medical Exit Exam"
    exam_data["verified"] = True
    exam_data["source"] = exam_data.get("source") or f"owner-confirmed on {OWNER_CONFIRMED_DR_FROTAN_CREDENTIAL_DATE}"
    profile["medical_exit_exam"] = exam_data

    note = profile.get("source_cv_note") or "Structured from the user-supplied CV."
    confirmation_note = (
        "Owner-confirmed Medical Exit Exam and valid medical professional registration/license added on "
        f"{OWNER_CONFIRMED_DR_FROTAN_CREDENTIAL_DATE}. No license/registration number, issue date, expiry date, "
        "certificate number, or document was provided."
    )
    if confirmation_note not in str(note):
        profile["source_cv_note"] = f"{note.rstrip()} {confirmation_note}"
    return profile


def profile_with_owner_confirmed_credentials(profile: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(profile)
    return apply_owner_confirmed_dr_frotan_credentials(updated)


# ---------------------------------------------------------------------------
# Profile I/O
# ---------------------------------------------------------------------------


def load_profile(path: str | Path = "profile.yaml") -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_profile(profile: dict[str, Any], path: str | Path = "profile.yaml") -> None:
    path = Path(path)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(profile, f, sort_keys=False, allow_unicode=True)


# ---------------------------------------------------------------------------
# Date and experience helpers
# ---------------------------------------------------------------------------


def parse_profile_date(value: Any, today: date | None = None) -> date | None:
    """Parse profile date formats such as 2022-05, May 2022, Present."""
    if value in (None, ""):
        return None
    today = today or date.today()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"present", "current", "now", "ongoing"}:
        return today
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y/%m", "%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date().replace(day=1) if fmt in {"%Y-%m", "%Y/%m", "%Y"} else parsed.date()
        except ValueError:
            pass
    match = re.search(r"(?P<mon>[A-Za-z]{3,9})\s+(?P<year>20\d{2}|19\d{2})", text)
    if match:
        month = MONTHS.get(match.group("mon").lower())
        if month:
            return date(int(match.group("year")), month, 1)
    match = re.search(r"(?P<year>20\d{2}|19\d{2})\s+(?P<mon>[A-Za-z]{3,9})", text)
    if match:
        month = MONTHS.get(match.group("mon").lower())
        if month:
            return date(int(match.group("year")), month, 1)
    return None


def months_between(start: date | None, end: date | None) -> int:
    if not start or not end or end < start:
        return 0
    return max(0, (end.year - start.year) * 12 + (end.month - start.month) + 1)


def _month_index(value: date) -> int:
    return value.year * 12 + value.month


def _merged_months(intervals: list[tuple[date, date]]) -> int:
    """Count months across intervals without double-counting overlaps."""
    if not intervals:
        return 0
    ranges = sorted((_month_index(start), _month_index(end)) for start, end in intervals if end >= start)
    merged: list[list[int]] = []
    for start, end in ranges:
        if not merged or start > merged[-1][1] + 1:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return sum(end - start + 1 for start, end in merged)


def infer_years_from_history(profile: dict[str, Any], *, kind: str = "clinical", today: date | None = None) -> float | None:
    """Infer years from work_history entries tagged or worded with a kind."""
    today = today or date.today()
    work = profile.get("work_history") or profile.get("experience") or []
    if not isinstance(work, list):
        return None
    intervals: list[tuple[date, date]] = []
    kind_terms = {
        "clinical": ["clinical", "doctor", "physician", "medical officer", "hospital", "clinic", "patient", "therapeutic feeding", "tfu", "sam", "mam", "otp", "mobile health"],
        "ngo": ["ngo", "ingo", "humanitarian", "donor", "emergency", "action against hunger", "acf", "tbt"],
        "management": ["manager", "management", "supervisor", "supervision", "lead", "coordinat", "advisor", "focal point", "capacity"],
        "public_health": ["public health", "moph", "health program", "hmis", "dhis2", "bphs", "ephs", "nutrition", "imam", "cmam", "covid"],
    }.get(kind, [kind])

    for entry in work:
        if not isinstance(entry, dict):
            continue
        haystack = " ".join(
            str(entry.get(field, ""))
            for field in ["title", "role", "organization", "employer", "sector", "description", "duties", "tags", "bullets"]
        ).lower()
        if not any(term in haystack for term in kind_terms):
            continue
        start = parse_profile_date(entry.get("start") or entry.get("start_date") or entry.get("from"), today=today)
        end = parse_profile_date(entry.get("end") or entry.get("end_date") or entry.get("to") or "present", today=today)
        if start and end and end >= start:
            intervals.append((start, end))
    total_months = _merged_months(intervals)
    if total_months == 0:
        return None
    return round(total_months / 12, 1)


# ---------------------------------------------------------------------------
# Evidence extraction
# ---------------------------------------------------------------------------


def _iter_strings(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(_iter_strings(item))
        return strings
    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(_iter_strings(item))
        return strings
    return [str(value)]


def _profile_text(profile: dict[str, Any]) -> str:
    include_keys = [
        "medical",
        "medical_education",
        "license_registration",
        "medical_exit_exam",
        "medical_credentials",
        "clinical_experience",
        "work_history",
        "skills",
        "languages",
        "certificates",
        "ngo_humanitarian_experience",
        "personal",
        "preferences",
    ]
    return "\n".join("\n".join(_iter_strings(profile.get(key))) for key in include_keys)


def _add_structured_education(evidence: ProfileEvidence, profile: dict[str, Any]) -> None:
    medical = profile.get("medical", {}) if isinstance(profile.get("medical"), dict) else {}
    education = []
    for key in ("medical_education", "education"):
        val = profile.get(key)
        if isinstance(val, list):
            education.extend(val)
    if isinstance(medical.get("education"), list):
        education.extend(medical["education"])
    if isinstance(medical.get("degrees"), list):
        education.extend(medical["degrees"])

    for item in education:
        text = " ".join(_iter_strings(item)) if isinstance(item, dict) else str(item)
        if re.search(r"\b(M\.?D\.?|MBBS|Medical Doctor|Doctor of Medicine|Physician)\b", text, flags=re.I):
            evidence.add("md_degree", True, "profile.medical_education", text, verified=True)
            evidence.add("medical_education", text, "profile.medical_education", text, verified=True)


def _add_license(evidence: ProfileEvidence, profile: dict[str, Any], profile_text: str) -> None:
    candidates = []
    medical = profile.get("medical", {}) if isinstance(profile.get("medical"), dict) else {}
    for key in ["license", "registration", "license_registration"]:
        if key in medical:
            candidates.append(medical[key])
        if key in profile:
            candidates.append(profile[key])
    verified_candidate_found = False
    for candidate in candidates:
        if candidate in (None, "", {}, []):
            continue
        text = " ".join(_iter_strings(candidate))
        if isinstance(candidate, dict):
            number = candidate.get("number") or candidate.get("registration_number") or candidate.get("id")
            verified = bool(candidate.get("verified"))
            status_text = str(candidate.get("status", ""))
            status = status_text.lower()
            # A placeholder like "Needs verification" is intentionally not evidence.
            if not (verified or number or (status and "needs verification" not in status)):
                continue
            verified_candidate_found = True
            authority = candidate.get("authority") or candidate.get("council") or candidate.get("issuer")
            if status_text and "needs verification" not in status:
                quote = status_text
            elif authority:
                quote = f"Valid medical professional registration/license verified by profile owner ({authority})"
            else:
                quote = "Valid medical professional registration/license verified in profile"
            if authority and str(authority) not in quote:
                quote = f"{quote} ({authority})"
            evidence.add("license_registration", True, "profile.license_registration", quote, verified=verified)
            if number:
                evidence.add("license_number", number, "profile.license_registration", str(number), verified=verified)
            document = (
                candidate.get("document_path")
                or candidate.get("document")
                or candidate.get("certificate_path")
                or candidate.get("scan_path")
                or candidate.get("file_path")
                or candidate.get("attachment_path")
            )
            if document:
                evidence.add("license_document", document, "profile.license_registration", str(document), verified=verified)
            elif candidate.get("copy_available") or candidate.get("document_verified"):
                evidence.add("license_document", True, "profile.license_registration", "License/registration document marked available in profile", verified=verified)
        else:
            if "needs verification" in text.lower():
                continue
            verified_candidate_found = True
            evidence.add("license_registration", True, "profile.license_registration", text, verified=True)
    if not verified_candidate_found and not candidates and re.search(r"\b(licen[cs]e|registration|registered)\b", profile_text, flags=re.I):
        evidence.add("license_registration", True, "profile", "License or registration mentioned in profile", verified=True)


def _add_medical_exit_exam(evidence: ProfileEvidence, profile: dict[str, Any]) -> None:
    exam = profile.get("medical_exit_exam")
    if exam in (None, "", {}, []):
        return
    if isinstance(exam, dict):
        verified = bool(exam.get("verified"))
        status_text = str(exam.get("status", ""))
        if not (verified or (status_text and "needs verification" not in status_text.lower())):
            return
        quote = status_text if status_text and "needs verification" not in status_text.lower() else "Medical Exit Exam completion verified in profile"
        evidence.add("medical_exit_exam", True, "profile", quote, verified=verified)
    else:
        text = str(exam)
        if "needs verification" not in text.lower():
            evidence.add("medical_exit_exam", True, "profile", text, verified=True)


def _add_languages(evidence: ProfileEvidence, profile: dict[str, Any], texts: list[tuple[str, str]]) -> None:
    languages = profile.get("languages", {})
    if isinstance(languages, dict):
        for name, level in languages.items():
            canonical = _canonical_language(name)
            if canonical:
                evidence.add(f"language_{canonical}", level or True, "profile.languages", f"{name}: {level}", verified=True)
    elif isinstance(languages, list):
        for item in languages:
            if isinstance(item, dict):
                name = item.get("name") or item.get("language") or ""
                level = item.get("level") or item.get("proficiency") or True
            else:
                name, level = str(item), True
            canonical = _canonical_language(name)
            if canonical:
                evidence.add(f"language_{canonical}", level, "profile.languages", f"{name}: {level}", verified=True)

    for source, text in texts:
        for canonical, aliases in LANGUAGE_ALIASES.items():
            if any(re.search(rf"\b{re.escape(alias)}\b", text, flags=re.I) for alias in aliases):
                evidence.add(f"language_{canonical}", True, source, _quote_for_alias(text, aliases), verified=(source == "profile"))


def _canonical_language(name: str) -> str | None:
    lower = str(name or "").lower()
    for canonical, aliases in LANGUAGE_ALIASES.items():
        if any(alias in lower for alias in aliases):
            return canonical
    return None


def _quote_for_alias(text: str, aliases: list[str]) -> str:
    for alias in aliases:
        match = re.search(rf".{{0,45}}\b{re.escape(alias)}\b.{{0,45}}", text, flags=re.I)
        if match:
            return normalize_text(match.group(0))
    return ""


def _add_terms(evidence: ProfileEvidence, texts: list[tuple[str, str]]) -> None:
    for source, text in texts:
        for key, patterns in MEDICAL_TERM_KEYS.items():
            for pattern in patterns:
                match = re.search(pattern, text, flags=re.I)
                if match:
                    quote = normalize_text(text[max(0, match.start() - 50): match.end() + 50])
                    evidence.add(key, True, source, quote, verified=(source == "profile"))
                    break


def _extract_years_from_text(text: str, context_terms: list[str]) -> float | None:
    def repl(match):
        return str(NUMBER_WORDS.get(match.group(1).lower(), match.group(1))) + " years"
    text = re.sub(r"\b(" + "|".join(NUMBER_WORDS) + r")\s+(?:years?|yrs?)\b", repl, text, flags=re.I)
    best: float | None = None
    for match in re.finditer(r"(?P<years>\d{1,2})\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?P<context>.{0,80}?)(?:experience|work)", text, flags=re.I):
        context = match.group("context").lower()
        if any(term in context for term in context_terms):
            value = float(match.group("years"))
            best = max(best or 0, value)
    # Alternate ordering: clinical experience of 4 years.
    for match in re.finditer(r"(?P<context>.{0,80}?)(?P<years>\d{1,2})\+?\s*(?:years?|yrs?)", text, flags=re.I):
        context = match.group("context").lower()
        if any(term in context for term in context_terms):
            value = float(match.group("years"))
            best = max(best or 0, value)
    return best


def _add_experience_years(evidence: ProfileEvidence, profile: dict[str, Any], resume_text: str, today: date | None = None) -> None:
    clinical = profile.get("clinical_experience", {})
    if isinstance(clinical, dict):
        years = clinical.get("years") or clinical.get("years_total")
        if years not in (None, ""):
            evidence.add("clinical_experience_years", float(years), "profile.clinical_experience", f"{years} years clinical experience", verified=True)
    elif isinstance(clinical, (int, float, str)) and str(clinical).strip():
        try:
            evidence.add("clinical_experience_years", float(clinical), "profile.clinical_experience", f"{clinical} years clinical experience", verified=True)
        except ValueError:
            pass

    ngo = profile.get("ngo_humanitarian_experience", {})
    if isinstance(ngo, dict):
        years = ngo.get("years") or ngo.get("years_total")
        if years not in (None, ""):
            evidence.add("ngo_experience_years", float(years), "profile.ngo_humanitarian_experience", f"{years} years NGO/humanitarian experience", verified=True)
    elif isinstance(ngo, bool) and ngo:
        evidence.add("ngo_humanitarian", True, "profile.ngo_humanitarian_experience", "NGO/humanitarian experience marked in profile", verified=True)

    for key, kind in [
        ("clinical_experience_years", "clinical"),
        ("ngo_experience_years", "ngo"),
        ("management_experience_years", "management"),
        ("public_health_experience_years", "public_health"),
    ]:
        inferred = infer_years_from_history(profile, kind=kind, today=today)
        if inferred:
            evidence.add(key, inferred, "profile.work_history", f"{inferred} years inferred from dated work history", verified=True)

    if resume_text:
        clinical_text_years = _extract_years_from_text(resume_text, ["clinical", "medical", "hospital", "clinic", "patient"])
        if clinical_text_years:
            evidence.add("clinical_experience_years", clinical_text_years, "cv", f"{clinical_text_years:g} years clinical experience mentioned in CV", verified=True)
        ngo_text_years = _extract_years_from_text(resume_text, ["ngo", "humanitarian", "emergency", "donor"])
        if ngo_text_years:
            evidence.add("ngo_experience_years", ngo_text_years, "cv", f"{ngo_text_years:g} years NGO/humanitarian experience mentioned in CV", verified=True)


def _add_personal(evidence: ProfileEvidence, profile: dict[str, Any]) -> None:
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    for key in ["location", "nationality", "gender", "phone", "email", "first_name", "last_name"]:
        if personal.get(key):
            evidence.add(key, personal[key], f"profile.personal.{key}", str(personal[key]), verified=True)
    prefs = profile.get("preferences", {}) if isinstance(profile.get("preferences"), dict) else {}
    for loc in prefs.get("locations", []) or []:
        evidence.add("preferred_location", loc, "profile.preferences.locations", str(loc), verified=True)
    for loc in prefs.get("preferred_locations", []) or []:
        evidence.add("preferred_location", loc, "profile.preferences.preferred_locations", str(loc), verified=True)
    if prefs.get("willing_to_relocate") is not None:
        evidence.add("willing_to_relocate", bool(prefs.get("willing_to_relocate")), "profile.preferences.willing_to_relocate", str(prefs.get("willing_to_relocate")), verified=True)
    if prefs.get("field_deployment") is not None:
        evidence.add("field_deployment", bool(prefs.get("field_deployment")), "profile.preferences.field_deployment", str(prefs.get("field_deployment")), verified=True)


def _add_skills_and_certificates(evidence: ProfileEvidence, profile: dict[str, Any]) -> None:
    for key in ["skills", "certificates", "certifications", "training"]:
        value = profile.get(key)
        if value:
            text = "\n".join(_iter_strings(value))
            evidence.add(key, text, f"profile.{key}", text, verified=True)


def build_profile_evidence(profile: dict[str, Any], resume_text: str = "", today: date | None = None) -> ProfileEvidence:
    """Build structured evidence without modifying the caller's profile object."""
    profile = profile_with_owner_confirmed_credentials(profile)
    evidence = ProfileEvidence(raw_profile=profile)
    ptext = _profile_text(profile)
    texts = [("profile", ptext)]
    if resume_text:
        texts.append(("cv", normalize_text(resume_text)))

    _add_personal(evidence, profile)
    _add_structured_education(evidence, profile)
    _add_license(evidence, profile, ptext)
    _add_medical_exit_exam(evidence, profile)
    _add_skills_and_certificates(evidence, profile)
    _add_languages(evidence, profile, texts)
    _add_terms(evidence, texts)
    _add_experience_years(evidence, profile, resume_text, today=today)

    # CV-only medical degree evidence.
    if resume_text and re.search(r"\b(M\.?D\.?|MBBS|Medical Doctor|Doctor of Medicine|Physician)\b", resume_text, flags=re.I):
        quote = _quote_for_alias(resume_text, ["MD", "MBBS", "Medical Doctor", "Doctor of Medicine", "Physician"])
        evidence.add("md_degree", True, "cv", quote or "Medical degree mentioned in CV", verified=True)

    if resume_text and re.search(r"\b(licen[cs]e|registration|registered)\b", resume_text, flags=re.I):
        quote = _quote_for_alias(resume_text, ["license", "licence", "registration", "registered"])
        evidence.add("license_registration", True, "cv", quote or "License/registration mentioned in CV", verified=True)

    return evidence


def summarize_evidence(evidence: ProfileEvidence, keys: list[str]) -> list[str]:
    snippets: list[str] = []
    for key in keys:
        snippets.extend(evidence.evidence_text(key))
    return snippets
