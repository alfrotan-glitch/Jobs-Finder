"""
Review-first tailored document generation.

The output is deterministic and conservative. It uses only facts from the
profile/CV evidence and the match report. It never invents qualifications; open
items are listed as verification warnings instead of being claimed.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from utils.medical_matcher import MET, NEEDS_VERIFICATION, NOT_MET
from utils.profile import build_profile_evidence


def _full_name(profile: dict[str, Any]) -> str:
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    return " ".join(part for part in [personal.get("first_name", ""), personal.get("last_name", "")] if part).strip() or "Applicant"


def _contact_lines(profile: dict[str, Any]) -> list[str]:
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    lines = []
    for key, label in [("email", "Email"), ("phone", "Phone"), ("location", "Location"), ("linkedin", "LinkedIn")]:
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


def _safe_bullets(items: list[Any], limit: int = 6) -> list[str]:
    bullets = []
    for item in items:
        text = _stringify_item(item).strip()
        if text and text not in bullets:
            bullets.append(text)
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
    terms = " ".join([job.get("title", ""), job.get("description", ""), " ".join(matched_labels)]).lower()
    keywords = [
        "medical", "doctor", "clinical", "nutrition", "tfu", "sam", "imam", "cmam", "hmis", "dhis2",
        "bphs", "ephs", "moph", "coordination", "supervision", "safeguarding", "psea", "reporting",
        "supply", "logistics", "emergency", "covid", "ngo", "humanitarian",
    ]
    active_terms = [kw for kw in keywords if kw in terms] or keywords

    def score(entry: dict[str, Any]) -> int:
        text = _stringify_item(entry).lower() + " " + " ".join(entry.get("bullets") or []).lower()
        return sum(1 for kw in active_terms if kw in text)

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


def generate_tailored_documents(
    job: dict[str, Any],
    profile: dict[str, Any],
    match_report: dict[str, Any],
    resume_text: str = "",
) -> dict[str, Any]:
    """
    Generate a tailored CV draft and cover letter draft for review.

    The drafts use only profile facts and matched evidence. They are plain text
    so a nontechnical user can copy/edit them before applying.
    """
    evidence = build_profile_evidence(profile, resume_text=resume_text)
    name = _full_name(profile)
    contact = _contact_lines(profile)
    title = job.get("title") or "the advertised role"
    company = job.get("company") or "your organization"
    location = job.get("location") or ""

    matched = _matched_labels(match_report)
    matched_sentence = ", ".join(matched[:5]) if matched else "the health requirements described in the vacancy"

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
    skills_bullets = _safe_bullets(skills_raw, limit=12)

    languages = []
    for lang_key in ["language_english", "language_dari", "language_pashto"]:
        if evidence.has(lang_key):
            languages.append(lang_key.replace("language_", "").title())

    summary_parts = [f"Medical Doctor with Afghanistan health and nutrition experience relevant to {title} at {company}."]
    if matched:
        summary_parts.append(f"Verified profile/CV evidence includes {matched_sentence}.")

    cv_lines = [
        name.upper(),
        *contact,
        "",
        f"TARGET ROLE: {title}",
        "",
        "PROFESSIONAL SUMMARY",
        " ".join(summary_parts),
        "",
    ]
    if skills_bullets:
        cv_lines.extend(["CORE COMPETENCIES", f"- {', '.join(map(str, skills_bullets))}", ""])
    if work_entries:
        cv_lines.append("PROFESSIONAL EXPERIENCE")
        for entry in _rank_work_entries(work_entries, job, matched)[:5]:
            line = _experience_header(entry)
            if line:
                cv_lines.append(line)
            for bullet in (entry.get("bullets") or [])[:5]:
                cv_lines.append(f"- {bullet}")
            if not entry.get("bullets") and entry.get("description"):
                cv_lines.append(f"- {entry['description']}")
            cv_lines.append("")
    elif work:
        cv_lines.extend(["PROFESSIONAL EXPERIENCE", *[f"- {item}" for item in work], ""])
    if education:
        cv_lines.extend(["EDUCATION", *[f"- {item}" for item in education], ""])
    if evidence.has("license_registration"):
        cv_lines.extend(["LICENSE / REGISTRATION", *[f"- {item}" for item in evidence.evidence_text("license_registration")[:3]], ""])
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
    suggested_subject = facts.get("application_subject") or " — ".join(subject_parts)

    cover_lines = [
        f"Subject: {suggested_subject}",
        "",
        "Dear Hiring Committee,",
        "",
        f"I am writing to apply for the {title} position{(' in ' + location) if location else ''} at {company}.",
    ]
    if matched:
        cover_lines.append(f"My background includes verified experience in {matched_sentence}.")
    else:
        cover_lines.append("I have reviewed the vacancy requirements and would like to be considered for the role.")
    if education:
        cover_lines.append(f"My medical education includes {education[0]}.")
    if evidence.has("license_registration"):
        cover_lines.append("My profile/CV includes evidence of professional license or registration.")
    if languages:
        cover_lines.append(f"I can work in {', '.join(languages)}.")
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
        "matched_requirements_used": matched,
        "review_warnings": warnings,
        "provenance": {
            "profile_fields": ["personal", "medical_education", "license_registration", "work_history", "skills", "languages", "certificates"],
            "job_source_url": facts.get("source_url") or job.get("url"),
            "application_url": facts.get("application_url") or job.get("apply_url"),
        },
    }


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
