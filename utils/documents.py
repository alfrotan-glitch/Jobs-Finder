"""
Review-first tailored document generation.

The output is deterministic and conservative. It uses only facts from the
profile/CV evidence and the match report. It never invents qualifications; open
items are listed as verification warnings instead of being claimed.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from utils.medical_matcher import MET, NEEDS_VERIFICATION, NOT_ELIGIBLE_STATUS, NOT_MET
from utils.profile import build_profile_evidence


def _full_name(profile: dict[str, Any]) -> str:
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    return " ".join(part for part in [personal.get("first_name", ""), personal.get("last_name", "")] if part).strip() or "Applicant"


def _is_placeholder_contact(value: Any, key: str = "") -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if key == "email" and text in {"doctor@example.org", "example@example.org", "email@example.com", "test@example.com"}:
        return True
    if key == "phone":
        digits = re.sub(r"\D+", "", text)
        if digits in {"93000000000", "0000000000", "00000000000"}:
            return True
        if re.fullmatch(r"(?:\+?93)?\s*0{3}[\s-]*0{3}[\s-]*0{3}", text):
            return True
    return False


def _safe_contact_value(personal: dict[str, Any], key: str) -> str:
    value = personal.get(key)
    if value and not _is_placeholder_contact(value, key):
        return str(value)
    return "CONFIRM BEFORE SUBMISSION"


def _language_lines(profile: dict[str, Any]) -> list[str]:
    values = []
    for item in profile.get("languages") or []:
        if not isinstance(item, dict):
            text = str(item).strip()
            if text and text not in values:
                values.append(text)
            continue
        name = str(item.get("name") or item.get("language") or "").strip()
        level = str(item.get("level") or item.get("proficiency") or "").strip()
        if not name:
            continue
        label = "Dari/Persian" if name.lower() in {"dari", "persian", "dari / persian"} else name
        text = f"{label} — {level}" if level else label
        if text not in values:
            values.append(text)
    order = {"dari/persian": 0, "dari": 0, "persian": 0, "english": 1, "pashto": 2}
    values.sort(key=lambda v: order.get(v.split("—", 1)[0].strip().lower(), 99))
    return values


def _contact_lines(profile: dict[str, Any]) -> list[str]:
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    lines = []
    for key, label in [("email", "Email"), ("phone", "Phone")]:
        value = personal.get(key)
        if value or _is_placeholder_contact(value, key):
            lines.append(f"{label}: {_safe_contact_value(personal, key)}")
    for key, label in [("location", "Location"), ("linkedin", "LinkedIn")]:
        if personal.get(key):
            lines.append(f"{label}: {personal[key]}")
    return lines


def _profile_list(profile: dict[str, Any], path: str) -> list[Any]:
    obj: Any = profile
    for key in path.split("."):
        if not isinstance(obj, dict):
            return []
        obj = obj.get(key)
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    return [obj]


def _stringify_item(item: Any) -> str:
    if isinstance(item, dict):
        parts = []
        for key in ["degree", "title", "name", "institution", "organization", "employer", "location", "start", "end", "year", "level"]:
            if item.get(key):
                parts.append(str(item[key]))
        desc = item.get("description") or item.get("duties")
        if desc:
            parts.append(str(desc))
        return " — ".join(parts)
    return str(item)


def _normalized_phrase(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _safe_bullets(items: list[Any], limit: int = 6) -> list[str]:
    bullets = []
    normalized: list[str] = []
    for item in items:
        text = _stringify_item(item).strip()
        norm = _normalized_phrase(text)
        if not text or not norm:
            continue
        if text in bullets or norm in normalized:
            continue
        # Avoid ATS-noisy repetitions such as a broad competency
        # "BPHS/EPHS & IMAM/CMAM" followed by separate "BPHS", "EPHS".
        words = set(norm.split())
        if any(
            (len(norm) >= 3 and f" {norm} " in f" {existing} ")
            or (words and words.issubset(set(existing.split())) and len(words) >= 2)
            for existing in normalized
        ):
            continue
        bullets.append(text)
        normalized.append(norm)
        if len(bullets) >= limit:
            break
    return bullets


def _experience_header(entry: dict[str, Any]) -> str:
    title = entry.get("title") or entry.get("role") or ""
    organization = entry.get("organization") or entry.get("employer") or ""
    location = entry.get("location") or ""
    start = entry.get("start") or entry.get("start_date") or ""
    end = entry.get("end") or entry.get("end_date") or ""
    parts = [part for part in [title, organization, location] if part]
    header = " | ".join(parts)
    if start or end:
        header += f" ({start} – {end or 'Present'})"
    return header


def _rank_work_entries(entries: list[dict[str, Any]], job: dict[str, Any], matched_labels: list[str]) -> list[dict[str, Any]]:
    focus_text = "\n".join([str(job.get("title", "")), str(job.get("description", "")), "\n".join(matched_labels)])
    terms = _tokenize_focus(focus_text)

    def score(entry: dict[str, Any]) -> tuple[int, int, int, str]:
        title = str(entry.get("title") or entry.get("role") or "")
        text = (_stringify_item(entry) + " " + " ".join(str(b) for b in (entry.get("bullets") or []))).strip()
        hits = len(_focus_term_hits(text, terms))
        title_lower = title.lower()
        health_role_bonus = 0
        if any(token in title_lower for token in ["medical doctor", "medical officer", "tfu medical", "physician"]):
            health_role_bonus += 4
        if any(token in title_lower for token in ["health and nutrition", "nutrition supervisor", "technical supervisor"]):
            health_role_bonus += 4
        if any(token in title_lower for token in ["supervisor", "team leader", "in-charge"]):
            health_role_bonus += 2
        # Administrative / communications roles stay available for coordination-heavy
        # vacancies, but should not outrank direct clinical/health supervision evidence.
        support_role_penalty = 2 if any(token in title_lower for token in ["administrative", "finance", "public relations", "communications advisor"]) else 0
        recency = str(entry.get("end") or entry.get("end_date") or entry.get("start") or "")
        return (hits + health_role_bonus - support_role_penalty, hits, health_role_bonus, recency)

    return sorted(entries, key=score, reverse=True)


def _matched_labels(match_report: dict[str, Any]) -> list[str]:
    labels = []
    for item in match_report.get("requirement_matches", []):
        if item.get("status") == MET and item.get("key") not in {"closing_date", "application_destination"}:
            labels.append(item.get("label", ""))
    return [label for label in labels if label]


def _verification_warnings(match_report: dict[str, Any]) -> list[str]:
    warnings = []
    for item in match_report.get("requirement_matches", []):
        if item.get("status") == NEEDS_VERIFICATION:
            warnings.append(f"Verify: {item.get('label')} — {item.get('explanation')}")
        elif item.get("status") == NOT_MET:
            warnings.append(f"Potential gap: {item.get('label')} — {item.get('explanation')}")
    return warnings


def _package_verification_blockers(match_report: dict[str, Any]) -> list[dict[str, str]]:
    """Return unmet/unverified requirements that must stay visible in review packages."""
    blockers: list[dict[str, str]] = []
    ignored_keys = {"closing_date", "application_destination", "application_subject"}
    for item in match_report.get("requirement_matches", []):
        if not isinstance(item, dict) or item.get("key") in ignored_keys:
            continue
        status = item.get("status")
        if status not in {NEEDS_VERIFICATION, NOT_MET}:
            continue
        label = str(item.get("label") or item.get("key") or "Requirement").strip()
        explanation = str(item.get("explanation") or "Verify this requirement before submission.").strip()
        if status == NEEDS_VERIFICATION:
            prefix = "Verify before applying"
            action = f"Verify requirement before applying: {label} — {explanation}"
        else:
            prefix = "Do not submit unless resolved"
            action = f"Do not submit unless resolved: {label} — {explanation}"
        blockers.append({"status": str(status), "label": label, "explanation": explanation, "prefix": prefix, "action": action})
    return blockers



# ---------------------------------------------------------------------------
# Tailoring helpers
# ---------------------------------------------------------------------------

TAILORING_KEYWORDS = [
    "medical", "doctor", "clinical", "diagnosis", "treatment", "patient", "curative", "opd", "mobile health",
    "primary health", "phc", "bphs", "ephs", "hmis", "dhis2", "data", "report",
    "nutrition", "tfu", "tsfp", "sam", "imam", "cmam", "iycf", "imnci",
    "supervision", "supervise", "mentor", "capacity", "training", "management", "coordination",
    "moph", "government", "authority", "stakeholder", "referral", "medicine", "medicines", "supply", "supplies", "stock", "logistics",
    "quality", "ipc", "patient safety", "safecare", "emergency", "outbreak", "covid", "safeguarding", "psea",
    "english", "dari", "pashto", "software", "computer", "ms office",
]


FOCUS_STOP_TERMS = {"office", "ms", "program", "project"}


def _tokenize_focus(text: str) -> set[str]:
    lower = str(text or "").lower()
    terms: set[str] = set()
    for keyword in TAILORING_KEYWORDS:
        if keyword in lower:
            terms.add(keyword)
            if keyword.endswith("ies"):
                terms.add(keyword[:-3] + "y")
            for part in re.split(r"[^a-z0-9]+", keyword):
                if len(part) >= 3 and part not in FOCUS_STOP_TERMS:
                    terms.add(part)
                    if part.endswith("ies"):
                        terms.add(part[:-3] + "y")
    for word in re.findall(r"[a-z0-9]{4,}", lower):
        if word in {"medical", "health", "doctor", "clinic", "clinical", "supervision", "management", "quality", "training", "reporting", "referral"}:
            terms.add(word)
    return terms


def _focus_term_hits(text: str, terms: set[str]) -> list[str]:
    lower = text.lower()
    hits: list[str] = []
    variants = {
        "supervision": ["supervision", "supervise", "supervised", "supervisor", "supervisory"],
        "supervise": ["supervise", "supervised", "supervisor", "supervision"],
        "management": ["management", "managed", "manager", "manage"],
        "coordination": ["coordination", "coordinate", "coordinated", "coordinating"],
        "reporting": ["reporting", "reports", "report"],
        "referral": ["referral", "referrals"],
        "supply": ["supply", "supplies", "stock", "logistics"],
        "supplies": ["supply", "supplies", "stock", "logistics"],
        "clinical": ["clinical", "clinic"],
        "health": ["health", "healthcare"],
    }
    for term in terms:
        if not term or term in FOCUS_STOP_TERMS:
            continue
        candidates = variants.get(term, [term])
        matched = False
        for candidate in candidates:
            if " " in candidate or "/" in candidate or "&" in candidate:
                matched = candidate in lower
            else:
                matched = re.search(rf"(?<![a-z0-9]){re.escape(candidate)}(?![a-z0-9])", lower) is not None
            if matched:
                break
        if matched:
            hits.append(term)
    return hits


def _requirement_matches(match_report: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in match_report.get("requirement_matches", []) if isinstance(item, dict)]


def _focus_labels(match_report: dict[str, Any], *, limit: int = 8) -> list[str]:
    labels: list[str] = []
    for item in _requirement_matches(match_report):
        key = item.get("key")
        if key in {"closing_date", "application_destination", "application_subject", "location_requirement"}:
            continue
        if item.get("status") != MET:
            continue
        label = str(item.get("label") or "").strip()
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def _profile_evidence_lines(profile: dict[str, Any]) -> list[str]:
    """Return factual profile/CV lines suitable for selecting vacancy-fit highlights."""
    lines: list[str] = []

    def add(text: str) -> None:
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if text and text not in lines:
            lines.append(text)

    for entry in profile.get("work_history") or profile.get("experience") or []:
        if not isinstance(entry, dict):
            continue
        header = _experience_header(entry)
        for bullet in entry.get("bullets") or []:
            add(f"{bullet} ({header})" if header else bullet)
        if not entry.get("bullets") and entry.get("description"):
            add(f"{entry['description']} ({header})" if header else entry["description"])
    skills = profile.get("skills", {})
    if isinstance(skills, dict):
        for values in skills.values():
            for value in values if isinstance(values, list) else [values]:
                add(str(value))
    elif isinstance(skills, list):
        for value in skills:
            add(str(value))
    for cert in profile.get("certificates") or profile.get("certifications") or profile.get("training") or []:
        add(str(cert))
    return lines


def _rank_strings_for_job(items: list[str], job: dict[str, Any], match_report: dict[str, Any], *, limit: int = 6) -> list[str]:
    focus_text = "\n".join([
        str(job.get("title", "")),
        str(job.get("description", "")),
        "\n".join(_focus_labels(match_report, limit=20)),
    ])
    terms = _tokenize_focus(focus_text)
    if not terms:
        return _safe_bullets(items, limit=limit)

    def score(item: str) -> tuple[int, int, int]:
        hits = len(_focus_term_hits(item, terms))
        if hits <= 0:
            return (0, 0, -abs(len(item) - 160))
        lower = item.lower()
        work_evidence_bonus = 2 if ("(" in item and "|" in item) else 0
        health_evidence_bonus = 0
        if any(token in lower for token in ["medical doctor", "tfu medical", "health and nutrition supervisor", "clinical assessment", "hmis", "bphs", "ephs", "imam"]):
            health_evidence_bonus = 2
        support_role_penalty = 0
        if "administrative and finance officer" in lower:
            support_role_penalty = 4
        elif "public relations" in lower or "communications advisor" in lower:
            support_role_penalty = 2
        # Prefer dated health/clinical/supervisory evidence.  General admin or
        # communications experience remains available for review, but it must not
        # outrank direct medical and health-program evidence on health vacancies.
        return (hits + work_evidence_bonus + health_evidence_bonus - support_role_penalty, hits, -abs(len(item) - 160))

    ranked = sorted([str(item) for item in items if str(item).strip()], key=score, reverse=True)
    ranked = [item for item in ranked if score(item)[0] > 0] or ranked
    return _safe_bullets(ranked, limit=limit)


def _vacancy_fit_highlights(profile: dict[str, Any], job: dict[str, Any], match_report: dict[str, Any], *, limit: int = 6) -> list[str]:
    return _rank_strings_for_job(_profile_evidence_lines(profile), job, match_report, limit=limit)



def _job_focus_phrases(job: dict[str, Any], match_report: dict[str, Any] | None = None, *, limit: int = 6) -> list[str]:
    """Human-readable vacancy focus phrases for professional documents."""
    text = f"{job.get('title', '')}\n{job.get('description', '')}".lower()
    phrases: list[str] = []

    def add(phrase: str, *needles: str) -> None:
        if phrase in phrases:
            return
        if any(needle in text for needle in needles):
            phrases.append(phrase)

    add("primary healthcare service supervision", "primary healthcare", "primary health", "phc")
    add("patient referral coordination", "referral")
    add("medicine, stock and medical-supply coordination", "medical supplies", "medicines", "stock", "supply chain")
    add("supportive supervision and mentorship", "supportive supervision", "mentorship", "mentor", "supervision")
    add("health data, HMIS and reporting", "hmis", "data management", "records", "reports", "reporting")
    add("quality improvement and patient safety", "quality improvement", "quality", "patient safety", "safecare")
    add("TSFP project and nutrition service implementation", "tsfp")
    add("nutrition service implementation", "nutrition", "malnutrition")
    add("BPHS/EPHS compliance", "bphs", "ephs")
    add("clinical assessment, diagnosis and treatment", "diagnosis", "treatment", "clinical", "curative")
    add("OPD and mobile health service delivery", "opd", "mobile health", "mobile team")
    add("infection prevention and control", "infection", "ipc")
    add("MoPH and stakeholder coordination", "moph", "ministry of public health", "stakeholder", "government authorities")
    add("district and health-center selection", "district", "health center", "health centre")
    if not phrases and match_report:
        for label in _focus_labels(match_report, limit=limit):
            lower = label.lower()
            if any(skip in lower for skip in ["degree", "license", "registration", "exit", "gender", "nationality"]):
                continue
            phrases.append(label)
            if len(phrases) >= limit:
                break
    return phrases[:limit]

def _requirement_summary_phrase(match_report: dict[str, Any]) -> str:
    labels = _focus_labels(match_report, limit=5)
    return ", ".join(labels) if labels else "the advertised health requirements"

def generate_tailored_documents(
    job: dict[str, Any],
    profile: dict[str, Any],
    match_report: dict[str, Any],
    resume_text: str = "",
) -> dict[str, Any]:
    """
    Generate a vacancy-specific CV and cover letter for user review.

    The documents are deterministic: they select and order existing profile/CV
    evidence against the vacancy requirements.  They do not invent facts, hidden
    license numbers, references, dates, or unavailable documents.
    """
    evidence = build_profile_evidence(profile, resume_text=resume_text)
    name = _full_name(profile)
    contact = _contact_lines(profile)
    title = job.get("title") or "the advertised role"
    company = job.get("company") or "your organization"
    location = job.get("location") or ""

    focus_labels = _focus_labels(match_report)
    focus_phrases = _job_focus_phrases(job, match_report)
    matched_sentence = ", ".join(focus_phrases[:5]) if focus_phrases else _requirement_summary_phrase(match_report)
    vacancy_highlights = _vacancy_fit_highlights(profile, job, match_report, limit=6)

    education = _safe_bullets(_profile_list(profile, "medical_education") + _profile_list(profile, "medical.education") + _profile_list(profile, "medical.degrees"), limit=4)
    work_entries = [item for item in (_profile_list(profile, "work_history") + _profile_list(profile, "experience")) if isinstance(item, dict)]
    work = _safe_bullets(_profile_list(profile, "work_history") + _profile_list(profile, "experience"), limit=6)
    certs = _safe_bullets(_profile_list(profile, "certificates") + _profile_list(profile, "certifications") + _profile_list(profile, "training"), limit=8)

    skills_raw = []
    skills = profile.get("skills", {})
    if isinstance(skills, dict):
        for value in skills.values():
            if isinstance(value, list):
                skills_raw.extend(value)
            elif value:
                skills_raw.append(value)
    elif isinstance(skills, list):
        skills_raw.extend(skills)
    skills_bullets = _rank_strings_for_job([str(item) for item in skills_raw], job, match_report, limit=12)

    languages = _language_lines(profile)
    if not languages:
        for lang_key in ["language_english", "language_dari", "language_pashto"]:
            if evidence.has(lang_key):
                languages.append(lang_key.replace("language_", "").title())

    summary_parts = [
        f"Medical Doctor with Afghanistan health and nutrition field/supervisory experience, tailored for the {title} role at {company}."
    ]
    if focus_labels:
        summary_parts.append(f"Vacancy focus areas considered for tailoring include {matched_sentence}; the evidence below is limited to verified profile/CV facts.")

    cv_lines = [
        name.upper(),
        *contact,
        "",
        f"TARGET ROLE: {title}",
        f"TARGET ORGANIZATION: {company}",
    ]
    if location:
        cv_lines.append(f"VACANCY LOCATION: {location}")
    cv_lines.extend([
        "",
        "PROFESSIONAL SUMMARY",
        " ".join(summary_parts),
        "",
    ])
    if vacancy_highlights:
        cv_lines.extend(["VACANCY-FIT HIGHLIGHTS", *[f"- {item}" for item in vacancy_highlights], ""])
    if skills_bullets:
        cv_lines.extend(["CORE COMPETENCIES", f"- {', '.join(map(str, skills_bullets))}", ""])
    if work_entries:
        cv_lines.append("PROFESSIONAL EXPERIENCE")
        for entry in _rank_work_entries(work_entries, job, focus_labels)[:5]:
            line = _experience_header(entry)
            if line:
                cv_lines.append(line)
            ranked_entry_bullets = _rank_strings_for_job([str(b) for b in (entry.get("bullets") or [])], job, match_report, limit=5)
            for bullet in ranked_entry_bullets:
                cv_lines.append(f"- {bullet}")
            if not ranked_entry_bullets and entry.get("description"):
                cv_lines.append(f"- {entry['description']}")
            cv_lines.append("")
    elif work:
        cv_lines.extend(["PROFESSIONAL EXPERIENCE", *[f"- {item}" for item in work], ""])
    if education:
        cv_lines.extend(["EDUCATION", *[f"- {item}" for item in education], ""])
    if evidence.has("license_registration"):
        cv_lines.extend(["LICENSE / REGISTRATION", *[f"- {item}" for item in evidence.evidence_text("license_registration")[:3]], ""])
    if evidence.has("medical_exit_exam"):
        cv_lines.extend(["MEDICAL EXIT EXAM", *[f"- {item}" for item in evidence.evidence_text("medical_exit_exam")[:2]], ""])
    if certs:
        cv_lines.extend(["CERTIFICATIONS & TRAINING", *[f"- {item}" for item in certs], ""])
    if languages:
        cv_lines.extend(["LANGUAGES", f"- {', '.join(languages)}", ""])

    warnings = _verification_warnings(match_report)

    facts = match_report.get("facts", {})
    metadata = job.get("metadata", {}) if isinstance(job.get("metadata", {}), dict) else {}
    reference = facts.get("reference_number") or metadata.get("reference_number")
    subject_parts = []
    if reference:
        subject_parts.append(str(reference))
    subject_parts.append(str(title))
    suggested_subject = facts.get("application_subject") or metadata.get("application_subject") or " — ".join(subject_parts)

    cover_lines = [
        f"Subject: {suggested_subject}",
        "",
        "Dear Hiring Committee,",
        "",
        f"I am writing to apply for the {title} position{(' in ' + location) if location else ''} at {company}.",
    ]
    if focus_labels:
        cover_lines.append(f"I understand that the vacancy emphasizes {matched_sentence}.")
    if vacancy_highlights:
        cover_highlights = [item for item in vacancy_highlights if "(" in item and "|" in item]
        cover_highlights.extend(item for item in vacancy_highlights if item not in cover_highlights)
        cover_lines.extend(["My relevant experience includes:", *[f"- {item}" for item in cover_highlights[:4]]])
    elif focus_labels:
        cover_lines.append(f"My verified profile/CV evidence is relevant to {matched_sentence}.")
    else:
        cover_lines.append("I have reviewed the vacancy requirements and would like to be considered for the role.")
    if education:
        cover_lines.append(f"My medical education includes {education[0]}.")
    if evidence.has("license_registration") and any(item.get("key") == "license_registration" for item in _requirement_matches(match_report)):
        cover_lines.append("I also meet the professional medical registration/license requirement stated for the role.")
    if evidence.has("medical_exit_exam") and any(item.get("key") == "medical_exit_exam" for item in _requirement_matches(match_report)):
        cover_lines.append("My profile also includes verified completion of the required Medical Exit Exam.")
    if languages:
        cover_lines.append(f"My verified language profile is {', '.join(languages)}.")
    cover_lines.extend([
        "",
        "I would welcome the opportunity to discuss how my experience can support your health program and the communities served by this position.",
        "",
        "Sincerely,",
        name,
    ])

    return {
        "generated_at": date.today().isoformat(),
        "job_id": job.get("id"),
        "job_title": title,
        "company": company,
        "tailored_cv_text": "\n".join(cv_lines).strip() + "\n",
        "cover_letter": "\n".join(cover_lines).strip() + "\n",
        "suggested_subject": suggested_subject,
        "matched_requirements_used": focus_labels,
        "selected_vacancy_fit_evidence": vacancy_highlights,
        "review_warnings": warnings,
        "provenance": {
            "profile_fields": ["personal", "medical_education", "license_registration", "medical_exit_exam", "work_history", "skills", "languages", "certificates"],
            "job_source_url": facts.get("source_url") or metadata.get("source_url") or job.get("url"),
            "application_url": facts.get("application_url") or job.get("apply_url"),
            "tailoring_method": "ranked profile/CV evidence against extracted vacancy requirements and source text",
        },
    }

def _extract_email(value: str | None) -> str:
    if not value:
        return ""
    match = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", str(value), flags=re.I)
    return match.group(0) if match else ""


def _is_http_url(value: str | None) -> bool:
    if not value:
        return False
    try:
        parsed = urlparse(str(value))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _normalize_application_url(value: str) -> tuple[str, list[str]]:
    """Normalize common employer form URL mistakes without bypassing controls."""
    if not _is_http_url(value):
        return value, []
    parsed = urlparse(str(value))
    notes: list[str] = []
    path = parsed.path or ""
    if parsed.netloc.lower() == "docs.google.com" and "/forms/d/" in path and path.endswith("/edit"):
        path = path[: -len("/edit")] + "/viewform"
        normalized = urlunparse(parsed._replace(path=path))
        notes.append(
            "Source supplied a Google Forms /edit URL; use the respondent /viewform URL for manual applicant review/submission. "
            "If Google requires owner access or login, stop and verify the correct employer link."
        )
        return normalized, notes
    return value, []


def _metadata_list(job: dict[str, Any], key: str) -> list[str]:
    metadata = job.get("metadata", {}) if isinstance(job.get("metadata", {}), dict) else {}
    value = metadata.get(key)
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _infer_required_documents(job: dict[str, Any]) -> list[str]:
    explicit = _metadata_list(job, "required_documents") or _metadata_list(job, "required_document_checklist")
    if explicit:
        return explicit
    text = f"{job.get('title', '')}\n{job.get('description', '')}".lower()
    docs: list[str] = []

    def add(label: str) -> None:
        if label not in docs:
            docs.append(label)

    if "cv" in text or "resume" in text or not docs:
        add("Tailored CV / resume")
    if "cover letter" in text or "application letter" in text:
        add("Tailored cover letter / application letter")
    if "application form" in text:
        add("Organization application form, completed if required")
    if "reference" in text or "referee" in text:
        add("References/referees requested by the vacancy")
    if "tazkira" in text or "تذکره" in text:
        add("Tazkira if requested by the employer")
    if "academic certificate" in text or "diploma" in text or "سند تحصیلی" in text:
        if "only if" in text or "if selected" in text or "called for" in text:
            add("Academic certificates/diplomas only if later requested by the employer")
        else:
            add("Academic certificates/diplomas if requested by the application form")
    if "pdf" in text and "word" in text:
        add("PDF and Word-format copies if the employer form requests both")
    return docs


def _infer_form_fields(job: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    explicit = _metadata_list(job, "form_fields") or _metadata_list(job, "form_field_checklist")
    if explicit:
        return explicit
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    language_summary = "; ".join(_language_lines(profile)) or "confirm languages from reviewed CV"
    fields = [
        f"Full name: {_full_name(profile)}",
        f"Email: {_safe_contact_value(personal, 'email')}",
        f"Phone: {_safe_contact_value(personal, 'phone')}",
        f"Current location: {personal.get('location', 'confirm before submit') or 'confirm before submit'}",
        f"Position applied for: {job.get('title', 'confirm exact title')}",
        "Education: MD, Kabul Medical Science University, 2013–2020",
        "License/registration: verified as valid; enter number only if Dr. Frotan provides the exact number",
        "Medical Exit Exam: verified as completed; enter certificate/document details only if Dr. Frotan provides them",
        "Work history with dates exactly as listed in the tailored CV",
        f"Languages: {language_summary}",
        "References/referees: use only references approved by Dr. Frotan before submission",
        "Document uploads: attach only the reviewed final files listed in the document checklist",
    ]
    return fields


def _infer_special_instructions(job: dict[str, Any], facts: dict[str, Any], route_type: str) -> list[str]:
    explicit = _metadata_list(job, "special_instructions") or _metadata_list(job, "application_instructions")
    instructions: list[str] = []
    for item in explicit:
        if item not in instructions:
            instructions.append(item)
    text = str(job.get("description", ""))
    lower = text.lower()

    def add(label: str) -> None:
        if label not in instructions:
            instructions.append(label)

    if route_type == "email" and facts.get("application_subject"):
        add(f"Use the exact email subject/reference: {facts['application_subject']}")
    elif route_type == "email" and facts.get("application_subject_required"):
        add("Email subject/reference is required by the vacancy; verify exact wording before sending")
    if "only one application" in lower or "only one" in lower:
        add("Submit only one application for this vacancy")
    if "do not submit academic" in lower:
        add("Do not attach academic certificates at initial application stage")
    if "validated copies" in lower and "requested only if" in lower:
        add("Validated academic copies are requested only if selected/called by the employer")
    if "select" in lower and ("district" in lower or "health center" in lower or "health centre" in lower):
        add("When the form asks, accurately select the intended district and health center")
    if "press submit" in lower:
        add("After user review, press Submit only once and only with explicit user confirmation")
    if "application form" in lower and route_type == "email":
        form_urls = [url.rstrip(".,);]") for url in re.findall(r"https?://\S+", text) if "form" in url.lower() or "application" in url.lower() or "acbar.org/applicationform" in url.lower()]
        if form_urls:
            for url in form_urls[:3]:
                add(f"Complete the organization application form before emailing: {url}")
        else:
            add("Complete the organization application form if required before emailing")
    return instructions


def _infer_blocking_user_inputs(job: dict[str, Any], route_type: str, required_documents: list[str]) -> list[str]:
    """Infer user-supplied items that cannot be generated safely.

    This is intentionally conservative.  Employer forms, references, IDs, and
    signatures must come from the applicant/user; if they are required for an
    email package, the package is prepared for review but not marked ready to
    send.
    """
    blocking = _metadata_list(job, "blocking_user_inputs") or _metadata_list(job, "user_required_before_send")
    text = f"{job.get('title', '')}\n{job.get('description', '')}\n" + "\n".join(required_documents)
    lower = text.lower()

    def add(label: str) -> None:
        if label not in blocking:
            blocking.append(label)

    if route_type == "email" and "application form" in lower:
        add("Completed organization application form")
    if route_type == "email" and (re.search(r"\b(?:three|3)\s+references?\b", lower) or "referee" in lower):
        add("Approved professional reference contacts")
    if route_type == "email" and re.search(r"\b(?:signature|sign and date|date and signature)\b", lower):
        add("Signature/date where required by the employer form")
    if route_type in {"email", "online_form"} and re.search(r"\b(?:tazkera|tazkira|passport)\b", lower):
        add("Personal identifier details only if the employer form requires them")
    return blocking


def _attachment_labels(required_documents: list[str], generated_paths: dict[str, str] | None = None) -> list[str]:
    generated_paths = generated_paths or {}
    labels: list[str] = []

    def add(label: str) -> None:
        if label not in labels:
            labels.append(label)

    for doc in required_documents:
        lower = doc.lower()
        if "cv" in lower or "resume" in lower:
            add(generated_paths.get("tailored_cv") or "Tailored CV / resume")
        elif "cover" in lower or "application letter" in lower:
            add(generated_paths.get("cover_letter") or "Tailored cover letter / application letter")
        else:
            add(doc)
    if not labels:
        add(generated_paths.get("tailored_cv") or "Tailored CV / resume")
        add(generated_paths.get("cover_letter") or "Tailored cover letter / application letter")
    return labels


def _email_body(
    *,
    name: str,
    title: str,
    company: str,
    source_url: str,
    deadline: str,
    attachment_list: list[str],
) -> str:
    attachment_text = "\n".join(f"- {item}" for item in attachment_list)
    deadline_sentence = f" The vacancy deadline is {deadline}." if deadline else ""
    source_sentence = f" I reviewed the vacancy at {source_url}." if source_url else ""
    return "\n".join([
        "Dear Hiring Committee,",
        "",
        f"Please find attached my application for the {title} position at {company}.{deadline_sentence}{source_sentence}",
        "",
        "Attached documents:",
        attachment_text,
        "",
        "I would be grateful if you would consider my application. Please let me know if any additional information is required.",
        "",
        "Sincerely,",
        name,
    ]).strip() + "\n"


def render_application_package(package: dict[str, Any]) -> str:
    """Render a structured application package as a plain-text review file."""
    lines = [
        f"Application package: {package.get('job_title')} — {package.get('company')}",
        f"Package status: {package.get('package_status')}",
        f"Route type: {package.get('route_type')}",
        f"Source URL: {package.get('source_url') or 'N/A'}",
        f"Deadline: {package.get('deadline') or 'N/A'}",
        f"Vacancy/reference number: {package.get('vacancy_reference') or 'N/A'}",
        "",
    ]
    email = package.get("email_draft") or {}
    if email:
        lines.extend([
            "EMAIL DRAFT",
            f"To: {email.get('to')}",
            f"Subject: {email.get('subject')}",
            "Body:",
            email.get("body", "").rstrip(),
            "",
            "Attachment list:",
            *[f"- {item}" for item in email.get("attachments", [])],
            "",
        ])
    online = package.get("online_application") or {}
    if online:
        lines.extend([
            "ONLINE APPLICATION",
            f"Application URL/form: {online.get('url')}",
            "Required form fields/data checklist:",
            *[f"- {item}" for item in online.get("form_fields_checklist", [])],
            "",
        ])
    elif package.get("form_fields_checklist"):
        lines.extend([
            "Required form fields/data checklist:",
            *[f"- {item}" for item in package.get("form_fields_checklist", [])],
            "",
        ])
    lines.extend([
        "Required document/attachment checklist:",
        *[f"- {item}" for item in package.get("required_documents_checklist", [])],
        "",
    ])
    review_warnings = package.get("review_warnings") or []
    if review_warnings:
        lines.extend([
            "Verification warnings before submission:",
            *[f"- {item}" for item in review_warnings],
            "",
        ])
    lines.extend([
        "Special application instructions:",
        *([f"- {item}" for item in package.get("special_instructions", [])] or ["- None beyond normal review and submission instructions."]),
        "",
        "Still required from user before sending/submitting:",
        *[f"- {item}" for item in package.get("user_required_actions", [])],
        "",
        "Safety status: prepared for user review only. No application has been submitted.",
    ])
    return "\n".join(lines).strip() + "\n"


def generate_application_package(
    job: dict[str, Any],
    profile: dict[str, Any],
    match_report: dict[str, Any],
    tailored_documents: dict[str, Any] | None = None,
    *,
    generated_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Prepare the review-first email/form package needed after CV tailoring.

    The package is deterministic and safe: it does not submit applications, does
    not bypass external controls, and does not invent license numbers, document
    numbers, dates, references, or unavailable attachments.  If an employer asks
    for the actual license/registration number or document, the matcher should
    keep the job out of READY_TO_APPLY until those facts are explicitly present.
    """
    facts = match_report.get("facts", {}) if isinstance(match_report, dict) else {}
    metadata = job.get("metadata", {}) if isinstance(job.get("metadata", {}), dict) else {}
    docs = tailored_documents or {}
    generated_paths = generated_paths or {}
    name = _full_name(profile)
    title = str(job.get("title") or docs.get("job_title") or "the advertised role")
    company = str(job.get("company") or docs.get("company") or "the employer")
    source_url = facts.get("source_url") or metadata.get("source_url") or job.get("url") or ""
    deadline = facts.get("closing_date") or metadata.get("closing_date") or metadata.get("deadline") or ""
    route_value_raw = facts.get("application_email") or facts.get("application_url") or job.get("apply_url") or job.get("url") or ""
    route_value, route_notes = _normalize_application_url(str(route_value_raw))
    email_to = _extract_email(facts.get("application_email") or route_value)
    online_url = route_value if _is_http_url(route_value) else ""
    route_type = "email" if email_to else "online_form" if online_url else "manual_review"
    reference = facts.get("reference_number") or metadata.get("reference_number") or ""
    subject = facts.get("application_subject") or metadata.get("application_subject") or docs.get("suggested_subject") or title
    required_documents = _infer_required_documents(job)
    special_instructions = _infer_special_instructions(job, facts, route_type)
    for note in route_notes:
        if note not in special_instructions:
            special_instructions.append(note)
    form_fields = _infer_form_fields(job, profile)
    attachment_list = _attachment_labels(required_documents, generated_paths)
    blocking_user_inputs = _infer_blocking_user_inputs(job, route_type, required_documents)

    email_draft = None
    online_application = None
    user_actions = [
        "Review the tailored CV and cover letter for accuracy before use",
        "Do not add a license/registration number, certificate number, issue date, expiry date, or document unless Dr. Frotan provides it",
    ]
    missing: list[str] = list(blocking_user_inputs)
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    if not personal.get("email") or _is_placeholder_contact(personal.get("email"), "email"):
        missing.append("Confirmed personal email address")
    if not personal.get("phone") or _is_placeholder_contact(personal.get("phone"), "phone"):
        missing.append("Confirmed phone number")
    for item in blocking_user_inputs + [m for m in missing if m not in blocking_user_inputs]:
        action = f"Provide/confirm: {item}"
        if action not in user_actions:
            user_actions.append(action)

    review_warnings = list(docs.get("review_warnings") or _verification_warnings(match_report))
    for blocker in _package_verification_blockers(match_report):
        missing_label = f"{blocker['prefix']}: {blocker['label']}"
        if missing_label not in missing:
            missing.append(missing_label)
        if blocker["action"] not in user_actions:
            user_actions.append(blocker["action"])
        instruction = f"{blocker['prefix']}: {blocker['label']} — {blocker['explanation']}"
        if instruction not in special_instructions:
            special_instructions.append(instruction)
        warning = f"{blocker['status']}: {blocker['label']} — {blocker['explanation']}"
        if warning not in review_warnings:
            review_warnings.append(warning)

    if route_type == "email":
        if not email_to:
            missing.append("application email")
        if facts.get("application_subject_required") and not subject:
            missing.append("required email subject/reference")
        email_draft = {
            "to": email_to,
            "subject": subject,
            "body": _email_body(
                name=name,
                title=title,
                company=company,
                source_url=source_url,
                deadline=deadline,
                attachment_list=attachment_list,
            ),
            "attachments": attachment_list,
        }
        user_actions.extend([
            "Attach the final reviewed files listed in the attachment list",
            "Send the email manually only after explicit user confirmation",
        ])
        package_status = "READY_FOR_REVIEW" if not missing else "NEEDS_USER_INPUT"
    elif route_type == "online_form":
        online_application = {"url": online_url, "form_fields_checklist": form_fields}
        user_actions.extend([
            "Open the application URL/form manually",
            "Complete each form field using the checklist and verified profile/CV facts only",
            "Upload the final reviewed files requested by the form",
            "Do not bypass CAPTCHA, login, MFA, or other security controls",
            "Submit only after explicit user confirmation",
        ])
        package_status = "READY_FOR_REVIEW" if online_url and not missing else "NEEDS_USER_INPUT"
    else:
        missing.append("application route")
        user_actions.append("Open the source URL and verify the application route manually")
        package_status = "NEEDS_USER_INPUT"

    package = {
        "job_id": job.get("id"),
        "job_title": title,
        "company": company,
        "route_type": route_type,
        "package_status": package_status,
        "source_url": source_url,
        "deadline": deadline,
        "vacancy_reference": reference,
        "application_route": email_to or online_url or route_value,
        "email_draft": email_draft,
        "online_application": online_application,
        "form_fields_checklist": form_fields,
        "required_documents_checklist": required_documents,
        "review_warnings": review_warnings,
        "special_instructions": special_instructions,
        "user_required_actions": user_actions,
        "missing_items": missing,
        "no_submission_performed": True,
    }
    package["text"] = render_application_package(package)
    return package



# ---------------------------------------------------------------------------
# File export helpers
# ---------------------------------------------------------------------------


def _safe_slug(value: str, *, max_len: int = 90) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return (slug[:max_len].strip("_") or "application")


def _write_text_docx_pdf(
    text: str,
    base_path: Any,
    *,
    document_type: str = "cv",
    metadata: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Write TXT plus globally designed DOCX/PDF exports.

    The TXT file remains the canonical ATS/plain-text source.  DOCX/PDF are
    rendered through the shared Jobs-Finder document design system so every
    application package receives the same professional visual language.  Export
    failures are surfaced in sidecar text files instead of silently losing the
    canonical content.
    """
    from utils.document_design import render_professional_document_artifacts

    base = Path(base_path)
    try:
        return render_professional_document_artifacts(
            text or "",
            base,
            document_type=document_type,
            metadata=metadata or {},
        )
    except Exception as exc:  # pragma: no cover - environment/export dependency safety
        base.parent.mkdir(parents=True, exist_ok=True)
        txt = base.with_suffix(".txt")
        txt.write_text(text or "", encoding="utf-8")
        base.with_suffix(".docx.txt").write_text(f"Designed DOCX export failed: {exc}\n\n{text or ''}", encoding="utf-8")
        base.with_suffix(".pdf.txt").write_text(f"Designed PDF export failed: {exc}\n\n{text or ''}", encoding="utf-8")
        raise RuntimeError(f"Global document design export failed for {base}: {exc}") from exc


def _application_document_base_paths(job: dict[str, Any], out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    prefix = application_bundle_prefix(job)
    return {
        "tailored_cv": out / f"{prefix}_tailored_cv",
        "cover_letter": out / f"{prefix}_cover_letter",
    }


def _expected_document_paths(job: dict[str, Any], out_dir: str | Path) -> dict[str, dict[str, str]]:
    bases = _application_document_base_paths(job, out_dir)
    return {
        key: {"txt": str(base.with_suffix(".txt")), "docx": str(base.with_suffix(".docx")), "pdf": str(base.with_suffix(".pdf"))}
        for key, base in bases.items()
    }


def application_bundle_prefix(job: dict[str, Any]) -> str:
    job_id = str(job.get("id") or "job")
    return f"{_safe_slug(job_id, max_len=32)}_{_safe_slug(job.get('title') or 'application', max_len=55)}"


def write_application_bundle_files(
    job: dict[str, Any],
    tailored_documents: dict[str, Any],
    package: dict[str, Any],
    *,
    out_dir: str | Path = "documents/applications",
) -> dict[str, Any]:
    """Persist a complete review package for one vacancy.

    Returns exact paths for the generated CV, cover letter, package text/JSON,
    and form-field checklist.  The caller remains responsible for review and
    explicit user confirmation before any real submission.
    """
    import json

    out = Path(out_dir)
    prefix = application_bundle_prefix(job)
    bases = _application_document_base_paths(job, out)
    design_metadata = {"job": job, "package": package, "tailored_documents": tailored_documents}
    cv_paths = _write_text_docx_pdf(
        tailored_documents.get("tailored_cv_text", ""),
        bases["tailored_cv"],
        document_type="cv",
        metadata=design_metadata,
    )
    cover_paths = _write_text_docx_pdf(
        tailored_documents.get("cover_letter", ""),
        bases["cover_letter"],
        document_type="cover_letter",
        metadata=design_metadata,
    )
    package_txt = out / f"{prefix}_complete_application_package.txt"
    package_json = out / f"{prefix}_complete_application_package.json"
    fields_txt = out / f"{prefix}_application_data_checklist.txt"
    package_txt.write_text(package.get("text", ""), encoding="utf-8")
    package_json.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    fields_lines = [
        f"Form/data checklist — {package.get('job_title')} — {package.get('company')}",
        f"Source URL: {package.get('source_url') or 'N/A'}",
        f"Deadline: {package.get('deadline') or 'N/A'}",
        "",
        "Use only verified facts. Do not invent missing personal identifiers, references, license numbers, certificate numbers, documents, issue dates, or expiry dates.",
        "",
        "Required form fields/data:",
        *[f"- {item}" for item in package.get("form_fields_checklist", [])],
        "",
        "Still required from user:",
        *[f"- {item}" for item in package.get("user_required_actions", [])],
    ]
    fields_txt.write_text("\n".join(fields_lines).strip() + "\n", encoding="utf-8")
    return {
        "tailored_cv": cv_paths,
        "cover_letter": cover_paths,
        "application_package_txt": str(package_txt),
        "application_package_json": str(package_json),
        "application_data_checklist": str(fields_txt),
    }


def prepare_application_bundle(
    job: dict[str, Any],
    profile: dict[str, Any],
    match_report: dict[str, Any],
    *,
    resume_text: str = "",
    out_dir: str | Path = "documents/applications",
) -> dict[str, Any]:
    """Generate documents, application package, and file exports for one job.

    Application documents are only generated for eligible or reviewable
    vacancies.  A deterministic NOT_ELIGIBLE match means the pipeline must not
    create positive CV/cover-letter artifacts for that role.
    """
    if str(match_report.get("readiness_status") or "") == NOT_ELIGIBLE_STATUS:
        raise ValueError(
            f"Refusing to prepare application documents for NOT_ELIGIBLE vacancy {job.get('id') or job.get('title') or ''}".strip()
        )
    docs = generate_tailored_documents(job, profile, match_report, resume_text=resume_text)
    expected_paths = _expected_document_paths(job, out_dir)
    package = generate_application_package(
        job,
        profile,
        match_report,
        docs,
        generated_paths={
            "tailored_cv": expected_paths["tailored_cv"].get("pdf") or expected_paths["tailored_cv"].get("txt", ""),
            "cover_letter": expected_paths["cover_letter"].get("pdf") or expected_paths["cover_letter"].get("txt", ""),
        },
    )
    paths = write_application_bundle_files(job, docs, package, out_dir=out_dir)
    docs["application_package"] = package
    docs["generated_paths"] = paths
    docs["no_submission_performed"] = True
    return docs

def redact_unverified_claims(text: str, allowed_terms: list[str]) -> str:
    """Small helper for tests and future AI output validation.

    It flags text containing common medical claims not represented in allowed
    terms.  It returns a warning string, not modified application content.
    """
    lowered_allowed = " ".join(allowed_terms).lower()
    risky = []
    for term in ["licensed", "registered", "mbbs", "md", "bphs", "ephs", "hmis", "imam", "imnci"]:
        if re.search(rf"\b{term}\b", text, flags=re.I) and term.lower() not in lowered_allowed:
            risky.append(term)
    return ", ".join(sorted(set(risky)))
