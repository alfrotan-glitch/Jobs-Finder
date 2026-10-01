"""
Review-first tailored document generation.

The output is deterministic and conservative. It uses only facts from the
profile/CV evidence and the match report. It never invents qualifications; open
items are listed as verification warnings instead of being claimed.

DOCUMENT EVIDENCE GATE (canonical rule for every employer-facing artifact —
TXT, and therefore also the DOCX/PDF renders derived from the same text):

* Factual CV sections (PROFESSIONAL SUMMARY, PROFESSIONAL EXPERIENCE, CORE
  COMPETENCIES, EDUCATION, LICENSE/REGISTRATION, MEDICAL EXIT EXAM,
  CERTIFICATIONS & TRAINING, LANGUAGES, VACANCY-FIT HIGHLIGHTS) and every
  cover-letter claim may only contain items that are explicitly verified
  (``verified: true`` per the canonical contract in ``utils.profile``) or
  that the authoritative matcher marked MET from verified evidence.
* Unverified profile/CV items are never silently promoted into factual
  content. They are surfaced in ``review_warnings`` instead, so nothing is
  lost but nothing unconfirmed is claimed to an employer.
* There is no generic hardcoded applicant description: the professional
  summary is assembled only from verified evidence (verified MD degree,
  verified experience years) plus the vacancy's own focus phrases.

CONTACT/IDENTITY CONTRACT (single rule for employer-facing contact data):

* Name/email/phone/location/linkedin from ``profile.personal`` are DISPLAY
  data, not credential claims: they are printed in generated documents even
  while the personal block is still an unconfirmed draft (e.g. fresh from a
  CV import), because the user must be able to review them in place, and
  legitimate contact data must never be suppressed or invented.
* Display never implies verification: contact/identity values only become
  verified evidence for matching (gender/nationality/location requirements)
  via explicit personal-field verification (``personal.verification.<field>:
  true``; legacy ``personal.verified: true`` is still honored).
* Known placeholder contact values are replaced with the explicit review
  marker ``CONFIRM BEFORE SUBMISSION`` so a fake address can never be sent.
* While identity/contact fields are not explicitly verified, the application
  package keeps a blocking "confirm identity/contact" item, so a draft import
  is visible as unresolved and the package is never presented as fully ready.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from utils.medical_matcher import MET, NEEDS_VERIFICATION, NOT_ELIGIBLE_STATUS, NOT_MET
from utils.profile import build_profile_evidence, is_unresolved_value, is_verified_flag, parse_profile_date, personal_field_is_verified


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


def _language_lines(profile: dict[str, Any], *, verified_only: bool = False) -> list[str]:
    """Return human-readable language lines for CV/cover-letter display.

    Placeholder proficiency levels (e.g. "Needs verification") are never
    shown verbatim in a document sent to an employer -- the language name is
    shown alone instead, which is honest without leaking internal review
    jargon. When ``verified_only`` is set, only languages with an explicit
    ``verified: true`` flag (and a resolved level) are included.
    """
    values = []
    for item in profile.get("languages") or []:
        if not isinstance(item, dict):
            if verified_only:
                continue
            text = str(item).strip()
            if text and text not in values:
                values.append(text)
            continue
        name = str(item.get("name") or item.get("language") or "").strip()
        level = str(item.get("level") or item.get("proficiency") or "").strip()
        verified = is_verified_flag(item.get("verified")) and not is_unresolved_value(level)
        if not name or (verified_only and not verified):
            continue
        label = "Dari / Persian" if name.lower() in {"dari", "persian", "dari / persian"} else name
        shown_level = level if level and not is_unresolved_value(level) else ""
        text = f"{label} — {shown_level}" if shown_level else label
        if text not in values:
            values.append(text)
    order = {"dari / persian": 0, "dari/persian": 0, "dari": 0, "persian": 0, "english": 1, "pashto": 2}
    values.sort(key=lambda v: order.get(v.split("—", 1)[0].strip().lower(), 99))
    return values


def _contact_lines(profile: dict[str, Any]) -> list[str]:
    """Employer-facing contact lines, per the CONTACT/IDENTITY CONTRACT.

    Contact data is display data for the applicant's own application: it is
    printed even while still an unconfirmed draft (so the user can review it
    in place, and legitimate contact data is never suppressed), but known
    placeholder values are replaced with the explicit CONFIRM BEFORE
    SUBMISSION marker, and nothing here ever counts as verified evidence --
    only explicit personal-field verification does that (see utils.profile).
    """
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    lines = []
    for key, label in [("email", "Email"), ("phone", "Phone")]:
        value = personal.get(key)
        if value or _is_placeholder_contact(value, key):
            lines.append(f"{label}: {_safe_contact_value(personal, key)}")
    for key, label in [("location", "Location"), ("linkedin", "LinkedIn")]:
        # Unresolved placeholders ("Needs verification" etc.) are internal
        # review markers and must never be printed into an employer-facing
        # document; the line is simply omitted until the value is resolved.
        if personal.get(key) and not is_unresolved_value(personal.get(key)):
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
            value = item.get(key)
            # Skip unresolved placeholder values ("Needs verification",
            # "Unknown", "Pending", ...) so they never get printed into a
            # document as if they were a confirmed institution/date/etc.
            if value and not is_unresolved_value(value):
                parts.append(str(value))
        desc = item.get("description") or item.get("duties")
        if desc and not is_unresolved_value(desc):
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


def _resolved_entry_value(entry: dict[str, Any], *keys: str) -> str:
    """First non-placeholder value among ``keys`` ("Needs verification" etc. never prints)."""
    for key in keys:
        value = entry.get(key)
        if value and not is_unresolved_value(value):
            return str(value)
    return ""


def _experience_header(entry: dict[str, Any]) -> str:
    title = _resolved_entry_value(entry, "title", "role")
    organization = _resolved_entry_value(entry, "organization", "employer")
    location = _resolved_entry_value(entry, "location")
    start = _resolved_entry_value(entry, "start", "start_date")
    end = _resolved_entry_value(entry, "end", "end_date")
    parts = [part for part in [title, organization, location] if part]
    header = " | ".join(parts)
    if start or end:
        header += f" ({start} – {end or 'Present'})"
    return header


def _entry_sort_key(entry: dict[str, Any]) -> tuple[date, date, str]:
    end_raw = entry.get("end") or entry.get("end_date") or entry.get("to") or "present"
    start_raw = entry.get("start") or entry.get("start_date") or entry.get("from") or "1900-01"
    end_date = parse_profile_date(end_raw, today=date.today()) or date.today()
    start_date = parse_profile_date(start_raw, today=date.today()) or date(1900, 1, 1)
    return (end_date, start_date, _resolved_entry_value(entry, "title", "role"))


def _reverse_chronological_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(entries, key=_entry_sort_key, reverse=True)


def _entry_text_values(entry: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ["bullets", "responsibilities", "achievements", "duties"]:
        value = entry.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value if item and not is_unresolved_value(item))
        elif value and not is_unresolved_value(value):
            values.append(str(value))
    description = entry.get("description")
    if description and not is_unresolved_value(description):
        values.append(str(description))
    return values


def _split_substantive_bullets(values: list[str]) -> list[str]:
    bullets: list[str] = []
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip(" -•;.")
        if not text or is_unresolved_value(text):
            continue
        parts = [p.strip(" -•;.") for p in re.split(r"(?:\n+|;|\.\s+)", text) if p.strip(" -•;.")]
        for part in parts or [text]:
            part = re.sub(r"\s+", " ", part).strip(" -•;.")
            if len(part) < 8 or is_unresolved_value(part):
                continue
            if not re.search(r"[A-Za-zآ-ی]", part):
                continue
            norm = _normalized_phrase(part)
            if norm and all(norm != _normalized_phrase(existing) for existing in bullets):
                bullets.append(part)
    return bullets


def _entry_bullets_for_job(entry: dict[str, Any], job: dict[str, Any], match_report: dict[str, Any], *, limit: int = 5) -> list[str]:
    bullets = _split_substantive_bullets(_entry_text_values(entry))
    if not bullets:
        return []
    ranked = _rank_strings_for_job(bullets, job, match_report, limit=max(limit, len(bullets)))
    # Keep role-relevant bullets first, then preserve remaining verified duties
    # so a real position is not reduced to one artificial sentence.
    ordered: list[str] = []
    for bullet in ranked + bullets:
        if bullet not in ordered:
            ordered.append(bullet)
        if len(ordered) >= limit:
            break
    return ordered


def _is_verified_entry(item: Any) -> bool:
    """True only for a dict entry explicitly confirmed with ``verified: true``."""
    return isinstance(item, dict) and is_verified_flag(item.get("verified"))


def _split_work_entries(profile: dict[str, Any]) -> tuple[list[dict[str, Any]], list[Any]]:
    """Split work history into (verified dict entries, everything unverified).

    Plain string entries carry no verification flag, so they can never appear
    as factual employer-facing experience; they land in the unverified bucket
    together with dict entries lacking an explicit ``verified: true``.
    """
    entries = _profile_list(profile, "work_history") + _profile_list(profile, "experience")
    verified = [entry for entry in entries if _is_verified_entry(entry)]
    unverified = [entry for entry in entries if not _is_verified_entry(entry)]
    return verified, unverified


def _named_items_by_verification(value: Any) -> tuple[list[str], list[str]]:
    """Split a skills/certificates/training structure into display names.

    Returns ``(verified, unverified)``. Only a dict item carrying an explicit
    ``verified: true`` next to its name counts as verified; plain strings have
    no verification flag and are therefore always unverified. Placeholder
    names are dropped entirely.
    """
    verified: list[str] = []
    unverified: list[str] = []

    def add(bucket: list[str], name: Any) -> None:
        text = str(name or "").strip()
        if text and not is_unresolved_value(text) and text not in verified and text not in unverified:
            bucket.append(text)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            name = node.get("name") or node.get("title")
            if name:
                add(verified if is_verified_flag(node.get("verified")) else unverified, name)
            for key, child in node.items():
                if key not in {"name", "title", "verified"}:
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
        elif node not in (None, ""):
            add(unverified, node)

    walk(value)
    return verified, unverified


def _skills_by_verification(profile: dict[str, Any]) -> tuple[list[str], list[str]]:
    return _named_items_by_verification(profile.get("skills"))


def _certificates_by_verification(profile: dict[str, Any]) -> tuple[list[str], list[str]]:
    verified: list[str] = []
    unverified: list[str] = []
    for key in ["certificates", "certifications", "training"]:
        v, u = _named_items_by_verification(profile.get(key))
        verified.extend(item for item in v if item not in verified)
        unverified.extend(item for item in u if item not in unverified and item not in verified)
    return verified, unverified


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
    ignored_keys = {"closing_date", "application_subject"}
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


def _requirement_met(match_report: dict[str, Any], key: str) -> bool:
    """True only when the authoritative matcher marked this requirement MET.

    MET is only produced by the matcher from genuinely verified evidence, so
    this is the single safe source of truth for "did we actually meet this
    requirement" -- document generation must not reconstruct this itself from
    raw evidence presence.
    """
    return any(item.get("key") == key and item.get("status") == MET for item in _requirement_matches(match_report))


def _verified_dict_items(items: list[Any]) -> list[Any]:
    """Keep only dict entries explicitly confirmed with ``verified: true``.

    Plain (non-dict) entries carry no verification field and are therefore
    never treated as confirmed facts suitable for an EDUCATION-style
    credential section.
    """
    return [item for item in items if isinstance(item, dict) and is_verified_flag(item.get("verified"))]


def _education_lines(items: list[Any], *, limit: int = 6) -> list[str]:
    lines: list[str] = []
    for item in _verified_dict_items(items):
        degree = _resolved_entry_value(item, "degree", "title", "name")
        institution = _resolved_entry_value(item, "institution", "school", "university", "organization")
        start = _resolved_entry_value(item, "start", "start_date", "from")
        end = _resolved_entry_value(item, "end", "end_date", "to")
        year = _resolved_entry_value(item, "year")
        years = f"{start}–{end}" if start and end else year
        parts = [part for part in [degree, institution, years] if part]
        line = " — ".join(parts).strip()
        if line and line not in lines:
            lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def _focus_labels(match_report: dict[str, Any], *, limit: int = 8) -> list[str]:
    labels: list[str] = []
    for item in _requirement_matches(match_report):
        key = item.get("key")
        if key in {"source_validity", "role_family_compatibility", "closing_date", "application_destination", "application_subject", "location_requirement"}:
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
    """Return verified factual profile lines for selecting vacancy-fit highlights.

    DOCUMENT EVIDENCE GATE: vacancy-fit highlights are presented to the
    employer as confirmed evidence, so only explicitly verified work-history
    entries and explicitly verified skill/certificate items may feed them.
    Unverified profile data stays out of this pool entirely (it is surfaced
    via review warnings instead).
    """
    lines: list[str] = []

    def add(text: str) -> None:
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if text and not is_unresolved_value(text) and text not in lines:
            lines.append(text)

    verified_work, _ = _split_work_entries(profile)
    for entry in verified_work:
        header = _experience_header(entry)
        for bullet in entry.get("bullets") or []:
            add(f"{bullet} ({header})" if header else bullet)
        if not entry.get("bullets") and entry.get("description"):
            add(f"{entry['description']} ({header})" if header else entry["description"])
    verified_skills, _ = _skills_by_verification(profile)
    for value in verified_skills:
        add(value)
    verified_certs, _ = _certificates_by_verification(profile)
    for cert in verified_certs:
        add(cert)
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


def _competencies_from_verified_experience(profile: dict[str, Any], job: dict[str, Any], match_report: dict[str, Any], *, limit: int = 10) -> list[str]:
    lines = "\n".join(_profile_evidence_lines(profile)).lower()
    candidates = [
        ("Clinical consultations", ["clinical consultation", "clinical consultations"]),
        ("Patient assessment", ["patient assessment"]),
        ("Diagnosis and treatment", ["diagnosis", "treatment"]),
        ("Referral coordination", ["referral"]),
        ("HMIS reporting", ["hmis"]),
        ("Nutrition screening", ["nutrition screening"]),
        ("SAM/IMAM/CMAM services", ["sam", "imam", "cmam"]),
        ("Therapeutic Feeding Unit", ["tfu", "therapeutic feeding"]),
        ("Team supervision", ["supervision", "supervised", "supervise"]),
        ("Team mentoring", ["mentoring", "mentor"]),
        ("MoPH coordination", ["moph", "ministry of public health"]),
        ("Safeguarding / PSEA", ["safeguarding", "psea"]),
    ]
    found = [label for label, needles in candidates if any(needle in lines for needle in needles)]
    return _rank_strings_for_job(found, job, match_report, limit=limit) if found else []



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


def _max_verified_years(evidence, key: str) -> float | None:
    values: list[float] = []
    for value in evidence.verified_values(key):
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return max(values) if values else None


def _verified_profile_title(profile: dict[str, Any], evidence) -> str:
    """Return a profile-owner-confirmed professional title, if available."""
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    candidates: list[tuple[Any, bool]] = []
    candidates.append((personal.get("professional_title"), personal_field_is_verified(profile, "professional_title")))
    title = profile.get("professional_title")
    if isinstance(title, dict):
        candidates.append((title.get("text") or title.get("value") or title.get("title"), is_verified_flag(title.get("verified"))))
    else:
        # A top-level plain string has no sibling verification flag.  Only use
        # it when the verified medical-degree evidence independently supports a
        # medical professional headline.
        candidates.append((title, evidence.has_verified("md_degree")))
    for value, verified in candidates:
        text = str(value or "").strip()
        if verified and text and not is_unresolved_value(text):
            return text
    return ""


def _signature_title(profile: dict[str, Any], evidence) -> str:
    title = _verified_profile_title(profile, evidence)
    if title:
        return title.split("|", 1)[0].strip()
    if evidence.has_verified("md_degree"):
        return "Medical Doctor"
    return ""


def _professional_title(profile: dict[str, Any], evidence, job: dict[str, Any], match_report: dict[str, Any]) -> str:
    profile_title = _verified_profile_title(profile, evidence)
    if profile_title:
        return profile_title
    if not evidence.has_verified("md_degree"):
        return "Applicant"
    focus = " ".join(_focus_labels(match_report, limit=8) + _job_focus_phrases(job, match_report, limit=8)).lower()
    has_public_health = any(
        evidence.has_verified(key)
        for key in ["public_health_experience_years", "ngo_experience_years", "management_experience_years", "nutrition", "imam", "hmis", "supervision_management"]
    )
    has_clinical = evidence.has_verified("clinical_experience_years")
    if has_public_health and any(term in focus for term in ["nutrition", "imam", "cmam", "sam", "tfu", "hmis", "public health", "supervision", "coordination"]):
        return "Medical Doctor | Public Health, Nutrition & Clinical Programs"
    if has_clinical and any(term in focus for term in ["clinical", "patient", "treatment", "diagnosis", "opd"]):
        return "Medical Doctor | Clinical Care & Primary Health"
    return "Medical Doctor"


def _verified_profile_summary(profile: dict[str, Any]) -> str:
    summary = profile.get("professional_summary") or profile.get("summary")
    if isinstance(summary, dict):
        text = str(summary.get("text") or summary.get("value") or "").strip()
        if is_verified_flag(summary.get("verified")) and text and not is_unresolved_value(text):
            return text
    return ""


def _has_verified_md(profile: dict[str, Any]) -> bool:
    raw_education_items = _profile_list(profile, "medical_education") + _profile_list(profile, "medical.education") + _profile_list(profile, "medical.degrees") + _profile_list(profile, "education")
    return any("MD" in line or "Medical Doctor" in line or "Doctor of Medicine" in line for line in _education_lines(raw_education_items, limit=6))


def _verified_work_haystack(profile: dict[str, Any]) -> str:
    work_entries, _ = _split_work_entries(profile)
    pieces: list[str] = []
    for entry in work_entries:
        pieces.append(_experience_header(entry))
        pieces.extend(_entry_text_values(entry))
    return "\n".join(piece for piece in pieces if piece).lower()


def _professional_background_sentence(profile: dict[str, Any]) -> str:
    """Concise background sentence grounded in verified profile entries."""
    if not _has_verified_md(profile):
        return ""
    haystack = _verified_work_haystack(profile)
    has_acf = "action against hunger" in haystack or "acf" in haystack
    has_tfu = "tfu doctor" in haystack or "therapeutic feeding unit" in haystack
    has_health_nutrition = "health & nutrition supervisor" in haystack or "health and nutrition supervisor" in haystack
    if has_acf and has_tfu and has_health_nutrition:
        return (
            "I am a Medical Doctor with clinical, health and nutrition program experience in humanitarian and public-health settings in Afghanistan, "
            "including experience as a TFU Doctor and Safeguarding/PSEA Focal Point and as a Health & Nutrition Supervisor with Action Against Hunger."
        )
    if any(term in haystack for term in ["clinical", "patient", "treatment", "diagnosis", "public health", "nutrition", "hmis"]):
        return "I am a Medical Doctor with clinical, health-program and public-health experience in Afghanistan."
    return ""


def _verified_summary_sentence(profile: dict[str, Any], evidence, title: str, company: str, focus_phrases: list[str], highlights: list[str]) -> str:
    """Build the professional-summary opener from verified evidence only."""
    profile_summary = _verified_profile_summary(profile)
    if profile_summary:
        return profile_summary
    headline = "Medical Doctor" if evidence.has_verified("md_degree") else "Applicant"
    qualifiers: list[str] = []
    clinical_years = _max_verified_years(evidence, "clinical_experience_years")
    if clinical_years:
        qualifiers.append(f"{clinical_years:g} years of clinical experience")
    ngo_years = _max_verified_years(evidence, "ngo_experience_years")
    if ngo_years:
        qualifiers.append(f"{ngo_years:g} years of NGO/humanitarian experience")
    public_years = _max_verified_years(evidence, "public_health_experience_years")
    if public_years:
        qualifiers.append(f"{public_years:g} years of public-health experience")
    if qualifiers:
        sentence = f"{headline} with {' and '.join(qualifiers)}."
    else:
        sentence = f"{headline} applying for the {title} role at {company}."
    if focus_phrases and highlights:
        sentence += f" Relevant experience is strongest in {', '.join(focus_phrases[:3])}."
    return sentence

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

    # DOCUMENT EVIDENCE GATE: every factual section below is restricted to
    # explicitly verified items. Credential-style facts (education, license,
    # exam) already required explicit verification; the same single rule now
    # governs work history, skills, certificates/training, languages, and the
    # professional summary. Unverified items are collected into review
    # warnings instead of being printed as employer-facing facts.
    raw_education_items = _profile_list(profile, "medical_education") + _profile_list(profile, "medical.education") + _profile_list(profile, "medical.degrees") + _profile_list(profile, "education")
    education = _education_lines(raw_education_items, limit=6)
    unverified_education = [item for item in raw_education_items if not _is_verified_entry(item)]

    work_entries, unverified_work = _split_work_entries(profile)
    verified_skills, unverified_skills = _skills_by_verification(profile)
    certs_verified, unverified_certs = _certificates_by_verification(profile)
    certs = _safe_bullets(certs_verified, limit=8)
    skills_bullets = _rank_strings_for_job(verified_skills, job, match_report, limit=12)
    for item in _competencies_from_verified_experience(profile, job, match_report, limit=12):
        if item not in skills_bullets:
            skills_bullets.append(item)
    skills_bullets = skills_bullets[:12]

    # Languages: only explicitly verified languages (name + resolved level +
    # verified: true) may be listed as factual CV content. Unverified mentions
    # (profile drafts or CV text) are review warnings, never CV facts.
    languages = _language_lines(profile, verified_only=True)
    unverified_languages = [item for item in _language_lines(profile) if item not in languages]

    professional_title = _professional_title(profile, evidence, job, match_report)
    signature_title = _signature_title(profile, evidence)
    summary = _verified_summary_sentence(profile, evidence, title, company, focus_phrases, vacancy_highlights)

    cv_lines = [
        name.upper(),
        professional_title,
        *contact,
        "",
        "PROFESSIONAL SUMMARY",
        summary,
        "",
    ]
    if skills_bullets:
        cv_lines.extend(["CORE PROFESSIONAL COMPETENCIES", *[f"- {item}" for item in skills_bullets], ""])
    if work_entries:
        cv_lines.append("PROFESSIONAL EXPERIENCE")
        for entry in _reverse_chronological_entries(work_entries):
            line = _experience_header(entry)
            if line:
                cv_lines.append(line)
            for bullet in _entry_bullets_for_job(entry, job, match_report, limit=12):
                cv_lines.append(f"- {bullet}")
            cv_lines.append("")
    if education:
        cv_lines.extend(["EDUCATION", *[f"- {item}" for item in education], ""])
    if evidence.has_verified("license_registration"):
        cv_lines.extend(["PROFESSIONAL REGISTRATION", *[f"- {item}" for item in evidence.evidence_text("license_registration", verified_only=True)[:3]], ""])
    if evidence.has_verified("medical_exit_exam"):
        cv_lines.extend(["MEDICAL EXIT EXAMINATION", *[f"- {item}" for item in evidence.evidence_text("medical_exit_exam", verified_only=True)[:2]], ""])
    if certs:
        cv_lines.extend(["RELEVANT TRAINING & CERTIFICATIONS", *[f"- {item}" for item in certs], ""])
    if languages:
        cv_lines.extend(["LANGUAGES", f"- {', '.join(languages)}", ""])

    warnings = _verification_warnings(match_report)
    # Unverified profile items excluded by the document evidence gate stay
    # visible to the user as review warnings so nothing is silently lost --
    # mark the item `verified: true` in profile.yaml after review to include it.
    for entry in unverified_work:
        header = _experience_header(entry) if isinstance(entry, dict) else str(entry).strip()
        header = header or _stringify_item(entry)
        if header:
            warnings.append(f"Unverified work history excluded from employer-facing documents (set verified: true after review to include): {header}")
    if unverified_skills:
        warnings.append("Unverified skills excluded from employer-facing documents (set verified: true after review to include): " + ", ".join(unverified_skills[:15]))
    if unverified_certs:
        warnings.append("Unverified certificates/training excluded from employer-facing documents (set verified: true after review to include): " + ", ".join(unverified_certs[:15]))
    if unverified_languages:
        warnings.append("Unverified languages excluded from employer-facing documents (confirm level and set verified: true to include): " + ", ".join(unverified_languages[:10]))
    if unverified_education:
        labels = [label for label in (_stringify_item(item) for item in unverified_education) if label]
        if labels:
            warnings.append("Unverified education excluded from employer-facing documents (set verified: true after review to include): " + "; ".join(labels[:6]))

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
    background_sentence = _professional_background_sentence(profile)
    if background_sentence:
        cover_lines.append(background_sentence)
    else:
        cover_lines.append("I am interested in this role because it aligns with my medical training and qualifications.")
    if vacancy_highlights:
        strongest = []
        for item in vacancy_highlights[:3]:
            text = str(item).strip()
            header_start = text.rfind(". (")
            if header_start != -1 and " | " in text[header_start:]:
                text = text[: header_start + 1].strip()
            strongest.append(text.rstrip("."))
        cover_lines.append("Relevant experience includes:")
        cover_lines.extend(f"- {str(item).rstrip('.')}" for item in strongest)
    elif focus_phrases:
        cover_lines.append(f"I understand that the vacancy emphasizes {', '.join(focus_phrases[:3])}.")
    else:
        cover_lines.append("I have reviewed the responsibilities and would welcome consideration for the role based on the qualifications presented in my CV.")
    credential_sentences: list[str] = []
    if education:
        credential_sentences.append(f"my medical education includes {education[0]}")
    if _requirement_met(match_report, "license_registration"):
        credential_sentences.append("I meet the professional medical registration/license requirement stated for the role")
    if _requirement_met(match_report, "medical_exit_exam"):
        credential_sentences.append("my Medical Exit Examination is included in my professional record")
    if languages:
        credential_sentences.append(f"my language profile includes {', '.join(languages)}")
    if credential_sentences:
        cover_lines.append("Additionally, " + "; ".join(credential_sentences) + ".")
    if any(value is True for value in evidence.verified_values("field_deployment")):
        cover_lines.append("I am available for field deployment in line with the needs of the position.")
    elif any(value is True for value in evidence.verified_values("willing_to_relocate")):
        cover_lines.append("I am willing to relocate or deploy for the position if selected.")
    cover_lines.extend([
        "",
        "I would welcome the opportunity to discuss how my qualifications can support your health program and the communities served by this position. Thank you for considering my application.",
        "",
        "Sincerely,",
        name,
    ])
    if signature_title:
        cover_lines.append(signature_title)
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    cover_lines.extend([
        f"Email: {_safe_contact_value(personal, 'email')}",
        f"Phone: {_safe_contact_value(personal, 'phone')}",
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
    language_summary = "; ".join(_language_lines(profile, verified_only=True)) or "enter only languages you have verified in profile.yaml"
    fields = [
        f"Full name: {_full_name(profile)}",
        f"Email: {_safe_contact_value(personal, 'email')}",
        f"Phone: {_safe_contact_value(personal, 'phone')}",
        f"Current location: {personal.get('location') if personal.get('location') and not is_unresolved_value(personal.get('location')) else 'confirm before submit'}",
        f"Position applied for: {job.get('title', 'confirm exact title')}",
        "Education: use only education shown in the reviewed profile/CV",
        "License/registration: enter only explicitly verified details; leave number/date blank when missing",
        "Medical Exit Exam: include only when explicitly verified in the profile",
        "Work history with dates exactly as listed in the tailored CV",
        f"Languages: {language_summary}",
        "References/referees: use only references explicitly approved before submission",
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


def _known_organization(value: str) -> str:
    text = str(value or "").strip()
    if text.lower() in {"", "unknown", "unknown employer", "unknown organization", "unknown org", "the employer"}:
        return ""
    return text


def _email_subject(title: str, requested_subject: str = "", reference: str = "") -> str:
    requested = str(requested_subject or "").strip()
    if requested:
        return requested
    subject = f"Application – {title}" if title else "Application"
    if reference:
        subject += f" – Ref: {reference}"
    return subject


def _email_highlights(items: list[str], *, limit: int = 4) -> list[str]:
    highlights: list[str] = []
    for item in items:
        text = re.sub(r"\s+", " ", str(item or "")).strip(" -•.")
        if not text:
            continue
        header_start = text.rfind(". (")
        if header_start != -1 and " | " in text[header_start:]:
            text = text[: header_start + 1].strip()
        if text not in highlights:
            highlights.append(text)
        if len(highlights) >= limit:
            break
    return highlights


def _email_body(
    *,
    name: str,
    title: str,
    company: str,
    location: str,
    personal: dict[str, Any],
    highlights: list[str],
    include_cover_letter: bool,
    background_sentence: str = "",
    signature_title: str = "",
) -> str:
    organization = _known_organization(company)
    position = f"the {title} position" if title else "the advertised position"
    where = f" in {location}" if location else ""
    at_org = f" at {organization}" if organization else ""
    intro = f"I am writing to apply for {position}{where}{at_org}."
    lines = ["Dear Hiring Committee,", "", intro]
    if background_sentence:
        lines.extend(["", background_sentence])
    if highlights:
        lines.extend(["", "Relevant experience I would bring to this role includes:"])
        lines.extend(f"- {item}" for item in highlights)
    else:
        lines.extend(["", "I would welcome consideration for this role based on the qualifications described in my CV."])
    attachment_sentence = "I have prepared my CV for your review"
    if include_cover_letter:
        attachment_sentence += ", along with a separate cover letter"
    attachment_sentence += "."
    lines.extend([
        "",
        attachment_sentence,
        "Thank you for considering my application. I would welcome the opportunity to discuss my suitability for the position.",
        "",
        "Sincerely,",
        name,
    ])
    if signature_title:
        lines.append(signature_title)
    lines.extend([
        f"Email: {_safe_contact_value(personal, 'email')}",
        f"Phone: {_safe_contact_value(personal, 'phone')}",
    ])
    return "\n".join(lines).strip() + "\n"


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
            "Attachments to include before sending:",
            *[f"- {item}" for item in (email.get("attachments_to_include") or email.get("attachments", []))],
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
    company = str(job.get("company") or docs.get("company") or "")
    source_url = facts.get("source_url") or metadata.get("source_url") or job.get("url") or ""
    deadline = facts.get("closing_date") or metadata.get("closing_date") or metadata.get("deadline") or ""
    application_method = str(facts.get("application_method") or metadata.get("application_method") or "UNAVAILABLE").upper()
    email_to = _extract_email(facts.get("apply_email") or facts.get("application_email") or metadata.get("apply_email") or metadata.get("application_email") or job.get("apply_email"))
    web_route_raw = facts.get("apply_url") or facts.get("application_url") or metadata.get("apply_url") or metadata.get("application_url") or job.get("apply_url") or ""
    route_value, route_notes = _normalize_application_url(str(web_route_raw))
    online_url = route_value if _is_http_url(route_value) else ""
    if application_method == "EMAIL" and email_to:
        route_type = "email"
    elif application_method == "WEB" and online_url:
        route_type = "online_form"
    elif email_to:
        route_type = "email"
        application_method = "EMAIL"
    elif online_url:
        route_type = "online_form"
        application_method = "WEB"
    else:
        route_type = "manual_review"
        application_method = "UNAVAILABLE"
    reference = facts.get("reference_number") or metadata.get("reference_number") or ""
    requested_subject = facts.get("application_subject") or metadata.get("application_subject") or ""
    subject = _email_subject(title, requested_subject=requested_subject, reference=reference)
    required_documents = _infer_required_documents(job)
    special_instructions = _infer_special_instructions(job, facts, route_type)
    for note in route_notes:
        if note not in special_instructions:
            special_instructions.append(note)
    form_fields = _infer_form_fields(job, profile)
    attachment_list = _attachment_labels(required_documents, generated_paths)
    if (generated_paths.get("cover_letter") or docs.get("cover_letter")) and not any("cover" in str(item).lower() for item in attachment_list):
        attachment_list.append(generated_paths.get("cover_letter") or "Tailored cover letter")
    blocking_user_inputs = _infer_blocking_user_inputs(job, route_type, required_documents)

    email_draft = None
    online_application = None
    user_actions = [
        "Review the tailored CV and cover letter for accuracy before use",
        "Do not add a license/registration number, certificate number, issue date, expiry date, or document unless the applicant provides it",
    ]
    missing: list[str] = list(blocking_user_inputs)
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    if not personal.get("email") or _is_placeholder_contact(personal.get("email"), "email"):
        missing.append("Confirmed personal email address")
    if not personal.get("phone") or _is_placeholder_contact(personal.get("phone"), "phone"):
        missing.append("Confirmed phone number")
    # CONTACT/IDENTITY CONTRACT: draft (e.g. CV-imported) contact data is
    # displayed in the documents for review, but each identity/contact field
    # stays a visible blocker until explicitly confirmed. A legacy
    # personal.verified: true profile still satisfies this check, but new
    # dashboard confirmations write personal.verification.<field>: true.
    identity_fields = ["first_name", "last_name", "email", "phone"]
    unverified_identity = [field for field in identity_fields if personal.get(field) and not personal_field_is_verified(profile, field)]
    if unverified_identity:
        missing.append("Identity/contact details reviewed and confirmed")
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

    official_page = facts.get("vacancy_url") or metadata.get("vacancy_url") or job.get("url") or ""

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
                location=str(job.get("location") or ""),
                personal=personal,
                highlights=_email_highlights(docs.get("selected_vacancy_fit_evidence") or []),
                include_cover_letter=bool(generated_paths.get("cover_letter") or docs.get("cover_letter")),
                background_sentence=_professional_background_sentence(profile),
                signature_title=_signature_title(profile, build_profile_evidence(profile)),
            ),
            "attachments_to_include": attachment_list,
            "attachments": attachment_list,
        }
        user_actions.extend([
            "Attach the final reviewed CV and any cover letter listed in the attachment list before sending",
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
        missing.append("direct application route verified from the official vacancy page")
        user_actions.append("Open the official vacancy/source page and verify the application route manually")
        package_status = "NEEDS_USER_INPUT"

    package = {
        "job_id": job.get("id"),
        "job_title": title,
        "company": company,
        "route_type": route_type,
        "application_method": application_method,
        "package_status": package_status,
        "source_url": source_url,
        "official_vacancy_page": official_page,
        "deadline": deadline,
        "vacancy_reference": reference,
        "application_route": email_to or online_url or official_page,
        "apply_email": email_to,
        "apply_url": online_url or None,
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
