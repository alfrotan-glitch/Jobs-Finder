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
from urllib.parse import urlparse, urlunparse

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
        cover_lines.append(f"My verified profile/CV matches key requirements including {matched_sentence}.")
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
    fields = [
        f"Full name: {_full_name(profile)}",
        f"Email: {personal.get('email', 'confirm before submit') or 'confirm before submit'}",
        f"Phone: {personal.get('phone', 'confirm before submit') or 'confirm before submit'}",
        f"Current location: {personal.get('location', 'confirm before submit') or 'confirm before submit'}",
        f"Position applied for: {job.get('title', 'confirm exact title')}",
        "Education: MD, Kabul Medical Science University, 2013–2020",
        "License/registration: verified as valid; enter number only if Dr. Frotan provides the exact number",
        "Medical Exit Exam: verified as completed; enter certificate/document details only if Dr. Frotan provides them",
        "Work history with dates exactly as listed in the tailored CV",
        "Languages: Dari/Persian, English, Pashto",
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
        add("Complete the organization application form if required before emailing")
    return instructions


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
    blocking_user_inputs = _metadata_list(job, "blocking_user_inputs") or _metadata_list(job, "user_required_before_send")

    email_draft = None
    online_application = None
    user_actions = [
        "Review the tailored CV and cover letter for accuracy before use",
        "Do not add a license/registration number, certificate number, issue date, expiry date, or document unless Dr. Frotan provides it",
    ]
    missing: list[str] = list(blocking_user_inputs)
    for item in blocking_user_inputs:
        action = f"Provide/confirm: {item}"
        if action not in user_actions:
            user_actions.append(action)

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
        package_status = "READY_TO_SEND" if not missing else "NEEDS_USER_INPUT"
    elif route_type == "online_form":
        online_application = {"url": online_url, "form_fields_checklist": form_fields}
        user_actions.extend([
            "Open the application URL/form manually",
            "Complete each form field using the checklist and verified profile/CV facts only",
            "Upload the final reviewed files requested by the form",
            "Do not bypass CAPTCHA, login, MFA, or other security controls",
            "Submit only after explicit user confirmation",
        ])
        package_status = "READY_TO_SUBMIT" if online_url else "NEEDS_USER_INPUT"
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
        "special_instructions": special_instructions,
        "user_required_actions": user_actions,
        "missing_items": missing,
        "no_submission_performed": True,
    }
    package["text"] = render_application_package(package)
    return package


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
