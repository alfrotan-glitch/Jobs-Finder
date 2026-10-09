"""
Review-first tailored document generation.

The output is deterministic and conservative. It uses only facts from the
canonical profile and the match report. It never invents qualifications; open
items are listed as verification warnings instead of being claimed.

DOCUMENT EVIDENCE GATE (canonical rule for every employer-facing artifact —
TXT, and therefore also the DOCX/PDF renders derived from the same text):

* Factual CV sections (PROFESSIONAL SUMMARY, PROFESSIONAL EXPERIENCE, CORE
  COMPETENCIES, EDUCATION, LICENSE/REGISTRATION, MEDICAL EXIT EXAM,
  CERTIFICATIONS & TRAINING, LANGUAGES, VACANCY-FIT HIGHLIGHTS) and every
  cover-letter claim may only contain items that are explicitly verified
  (``verified: true`` per the canonical contract in ``utils.profile``) or
  that the authoritative matcher marked MET from verified evidence.
* Unverified profile items are never silently promoted into factual
  content. They are surfaced in ``review_warnings`` instead, so nothing is
  lost but nothing unconfirmed is claimed to an employer.
* There is no generic hardcoded applicant description: the professional
  summary is assembled only from verified evidence (verified MD degree,
  verified experience years) plus the vacancy's own focus phrases.

CONTACT/IDENTITY CONTRACT (single rule for employer-facing contact data):

* Name/email/phone/location/linkedin are factual applicant data. They are
  printed only when their own ``personal.verification.<field>: true`` flag is
  present; a fresh CV draft or merely non-empty text is not enough.
* Missing, unverified, or placeholder name/email/phone values are replaced
  with the generic review marker ``CONFIRM BEFORE SUBMISSION``. Unverified
  location/linkedin lines are omitted rather than claimed.
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
from utils.paths import project_path
from utils.profile import (
    build_profile_evidence,
    is_unresolved_value,
    is_verified_flag,
    parse_profile_date,
    personal_field_is_verified,
    require_runtime_profile,
)


def _full_name(profile: dict[str, Any]) -> str:
    """Return a name only when both displayed name components are verified."""
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    first = personal.get("first_name", "")
    last = personal.get("last_name", "")
    if (
        first
        and last
        and not is_unresolved_value(first)
        and not is_unresolved_value(last)
        and personal_field_is_verified(profile, "first_name")
        and personal_field_is_verified(profile, "last_name")
    ):
        return f"{first} {last}".strip()
    return "CONFIRM BEFORE SUBMISSION"


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


def _safe_contact_value(profile: dict[str, Any], key: str) -> str:
    """Return a contact value only with its own explicit verification flag."""
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    value = personal.get(key)
    if (
        value
        and not is_unresolved_value(value)
        and not _is_placeholder_contact(value, key)
        and personal_field_is_verified(profile, key)
    ):
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
        name = str(item.get("name") or "").strip()
        level = str(item.get("level") or "").strip()
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
    """Employer-facing contact lines, gated by per-field verification."""
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    lines = []
    for key, label in [("email", "Email"), ("phone", "Phone")]:
        # Keep a generic marker visible when a contact value is absent or
        # unverified so a review package cannot accidentally look send-ready.
        lines.append(f"{label}: {_safe_contact_value(profile, key)}")
    for key, label in [("location", "Location"), ("linkedin", "LinkedIn")]:
        value = personal.get(key)
        if value and not is_unresolved_value(value) and personal_field_is_verified(profile, key):
            lines.append(f"{label}: {value}")
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
        for key in ["degree", "title", "name", "institution", "organization", "location", "start", "end", "graduation_year", "level"]:
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


def _safe_bullets(items: list[Any], limit: int | None = None) -> list[str]:
    bullets = []
    normalized: list[str] = []
    for item in items:
        text = _stringify_item(item).strip()
        norm = _normalized_phrase(text)
        if not text or not norm:
            continue
        if text in bullets or norm in normalized:
            continue
        # Avoid noisy repetitions such as a broad competency
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
        if limit is not None and len(bullets) >= limit:
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
    title = _resolved_entry_value(entry, "title")
    organization = _resolved_entry_value(entry, "organization")
    location = _resolved_entry_value(entry, "location")
    start = _resolved_entry_value(entry, "start")
    end = _resolved_entry_value(entry, "end")
    parts = [part for part in [title, organization, location] if part]
    header = " | ".join(parts)
    if start or end:
        header += f" ({start} – {end or 'Present'})"
    return header


def _entry_sort_key(entry: dict[str, Any]) -> tuple[date, date, str]:
    end_raw = entry.get("end") or "present"
    start_raw = entry.get("start") or "1900-01"
    end_date = parse_profile_date(end_raw, today=date.today()) or date.today()
    start_date = parse_profile_date(start_raw, today=date.today()) or date(1900, 1, 1)
    return (end_date, start_date, _resolved_entry_value(entry, "title"))


def _reverse_chronological_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(entries, key=_entry_sort_key, reverse=True)


#: Keys a work-history entry may carry a duty description in. ``bullets``,
#: ``achievements``, ``duties`` and ``description`` are the owner's free-form
#: fields; ``responsibilities`` is the verification-gated one.
DUTY_KEYS = ("bullets", "responsibilities", "achievements", "duties")


def _verified_responsibility_texts(value: Any) -> list[str]:
    """Return only owner-verified responsibility text from a canonical entry.

    ``responsibilities`` is verification-gated. An entry counts as verified CV
    content only when it is a mapping carrying a literal ``verified: true`` and
    a non-empty ``text``. A bare string, a missing flag, and an explicit
    ``verified: false`` are all draft material: the wording is preserved in the
    profile for owner review and is never presented as applicant experience.

    The gated shape exists so a generated scope draft can be recorded without
    being usable as a fact. The one place an unverified line may be surfaced is
    ``needs_verification``, which this function never reads.
    """
    if not isinstance(value, list):
        return []
    texts: list[str] = []
    for item in value:
        if not isinstance(item, dict) or item.get("verified") is not True:
            continue
        text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
        if text and not is_unresolved_value(text):
            texts.append(text)
    return texts


def _pending_responsibility_items(profile: dict[str, Any]) -> list[dict[str, str]]:
    """Drafts held back from employer-facing documents, for owner review only.

    These are duty suggestions that no applicant evidence covers. Each one was
    written by the system from verified profile evidence (role title, competency
    inventory, certificates) rather than supplied by the applicant, so it is
    reported to the owner instead of being printed as fact. Where the
    applicant's own supplied CV did document a duty, that duty now lives in
    ``responsibilities`` with ``verified: true`` and is printed normally.
    """
    pending: list[dict[str, str]] = []
    for entry in _profile_list(profile, "work_history"):
        if not isinstance(entry, dict):
            continue
        role = _experience_header(entry)
        drafts = entry.get("needs_verification")
        if not isinstance(drafts, list):
            continue
        for item in drafts:
            text = ""
            if isinstance(item, dict) and item.get("verified") is not True:
                text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
            if text:
                pending.append({"role": role, "text": text})
    return pending


def _pending_responsibility_warning(profile: dict[str, Any]) -> str:
    """One review line summarising drafts that are excluded from documents."""
    pending = _pending_responsibility_items(profile)
    if not pending:
        return ""
    roles = sorted({item["role"] for item in pending if item["role"]})
    return (
        f"{len(pending)} detailed responsibility draft(s) for {len(roles)} role(s) are NOT presented as verified "
        "experience: the applicant supplied no duties covering them, so the wording is system-authored. "
        "Confirm each line against your own record and move it to `responsibilities` with `verified: true` to publish "
        "it. Roles affected: " + "; ".join(roles)
    )


def _entry_text_values(entry: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in DUTY_KEYS:
        value = entry.get(key)
        if key == "responsibilities":
            # Verification-gated: unverified drafts never become CV content.
            values.extend(_verified_responsibility_texts(value))
        elif isinstance(value, list):
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


def _entry_bullets_for_job(
    entry: dict[str, Any],
    job: dict[str, Any],
    match_report: dict[str, Any],
    *,
    limit: int | None = None,
) -> list[str]:
    """Reorder real duties for a vacancy without rewriting or inventing them.

    A relevant position keeps every substantive verified responsibility. Less
    relevant positions may pass a small ``limit`` so they remain present but
    concise. The source strings are returned verbatim apart from whitespace and
    sentence-boundary normalization performed by ``_split_substantive_bullets``.
    """
    bullets = _split_substantive_bullets(_entry_text_values(entry))
    if not bullets:
        return []
    ranked = _rank_strings_for_job(bullets, job, match_report, limit=len(bullets))
    ordered: list[str] = []
    for bullet in ranked + bullets:
        if bullet not in ordered:
            ordered.append(bullet)
    return ordered if limit is None else ordered[:limit]


def _is_verified_entry(item: Any) -> bool:
    """True only for a dict entry explicitly confirmed with ``verified: true``."""
    return isinstance(item, dict) and is_verified_flag(item.get("verified"))


def _split_work_entries(profile: dict[str, Any]) -> tuple[list[dict[str, Any]], list[Any]]:
    """Split work history into (verified dict entries, everything unverified).

    Plain string entries carry no verification flag, so they can never appear
    as factual employer-facing experience; they land in the unverified bucket
    together with dict entries lacking an explicit ``verified: true``.
    """
    entries = _profile_list(profile, "work_history")
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
    for key in ["certificates"]:
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
    # Missing/expired closing dates are application blockers. The application
    # subject has its own exact-route handling below, but every other matcher
    # blocker is surfaced verbatim rather than being silently downgraded.
    ignored_keys = {"application_subject"}
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
    "field", "assessment", "outpatient", "inpatient", "ward", "clinical audit", "case management",
    "child protection", "protection", "infection", "prevention",
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
        # Employers write the long form of a verified acronym. Matching it is
        # presentation only: the acronym itself still has to exist as verified
        # canonical evidence before it is printed.
        "ipc": ["ipc", "infection prevention", "infection control"],
        "patient": ["patient", "patients"],
        "patient safety": ["patient safety", "clinical safety"],
        "assessment": ["assessment", "assessments"],
        "nutrition": ["nutrition", "nutritional", "malnutrition"],
        "safeguarding": ["safeguarding", "safeguard"],
        "psea": ["psea", "sexual exploitation"],
        "quality": ["quality", "quality improvement", "quality assurance"],
        "monitoring": ["monitoring", "monitor"],
        "hmis": ["hmis", "dhis2", "health management information system", "health data"],
        "training": ["training", "training follow-up", "capacity building"],
        "capacity": ["capacity", "capacity building"],
        "moph": ["moph", "ministry of public health", "public health directorate"],
        "government": ["government", "governor"],
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


def _education_lines(items: list[Any], *, limit: int | None = None) -> list[str]:
    lines: list[str] = []
    for item in _verified_dict_items(items):
        degree = _resolved_entry_value(item, "degree")
        field = _resolved_entry_value(item, "field", "field_of_study", "specialization")
        institution = _resolved_entry_value(item, "institution")
        start = _resolved_entry_value(item, "start")
        end = _resolved_entry_value(item, "end")
        year = _resolved_entry_value(item, "graduation_year")
        years = f"{start}–{end}" if start and end else year
        parts = [part for part in [degree, field, institution, years] if part]
        line = " — ".join(parts).strip()
        if line and line not in lines:
            lines.append(line)
        if limit is not None and len(lines) >= limit:
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
        for value in _entry_text_values(entry):
            add(f"{value} ({header})" if header else value)
    verified_skills, _ = _skills_by_verification(profile)
    for value in verified_skills:
        add(value)
    verified_certs, _ = _certificates_by_verification(profile)
    for cert in verified_certs:
        add(cert)
    return lines


def _rank_strings_for_job(items: list[str], job: dict[str, Any], match_report: dict[str, Any], *, limit: int | None = None) -> list[str]:
    focus_text = "\n".join([
        str(job.get("title", "")),
        str(job.get("description", "")),
        "\n".join(_focus_labels(match_report, limit=20)),
    ])
    terms = _tokenize_focus(focus_text)
    priority_terms = _job_title_terms(job)
    if not terms and not priority_terms:
        return _safe_bullets(items, limit=limit)

    def score(item: str) -> tuple[int, int, int]:
        hits = len(_focus_term_hits(item, terms)) + len(_focus_term_hits(item, priority_terms))
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


def _work_entry_relevance(entry: dict[str, Any], job: dict[str, Any], match_report: dict[str, Any]) -> int:
    """Deterministically score only textual overlap; never create a new fact."""
    focus = _tokenize_focus("\n".join([
        str(job.get("description") or ""),
        " ".join(_focus_labels(match_report, limit=20)),
    ]))
    text = "\n".join([_experience_header(entry), *_entry_text_values(entry)])
    hits = len(_focus_term_hits(text, focus)) + len(_focus_term_hits(text, _job_title_terms(job)))
    lower = text.lower()
    # Direct clinical/health roles should remain prominent for clinical health
    # vacancies even when a terse vacancy omits detailed keywords.
    if any(term in lower for term in ["medical doctor", "clinical", "health & nutrition", "health and nutrition", "public health", "rapid response"]):
        hits += 2
    return hits


def _tailored_work_sections(
    entries: list[dict[str, Any]], job: dict[str, Any], match_report: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (most relevant, remaining) while retaining every verified role."""
    chronological = _reverse_chronological_entries(entries)
    scored = [(entry, _work_entry_relevance(entry, job, match_report)) for entry in chronological]
    relevant = [entry for entry, score in sorted(scored, key=lambda pair: pair[1], reverse=True) if score > 0]
    relevant_ids = {id(entry) for entry in relevant}
    remaining = [entry for entry in chronological if id(entry) not in relevant_ids]
    # A generic vacancy can have no useful overlap. Keep the latest role in the
    # leading section so the CV still has a natural first-page chronology.
    if not relevant and remaining:
        # Keep a natural lead role without imposing a cap: all other verified
        # employment records remain in the same CV immediately afterwards.
        relevant.append(remaining.pop(0))
    return relevant, remaining


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
    """Return the profile owner's confirmed professional title, if any.

    The title comes from ``personal.professional_title`` and counts only
    when ``personal.verification.professional_title`` is true.
    """
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    if not personal_field_is_verified(profile, "professional_title"):
        return ""
    text = str(personal.get("professional_title") or "").strip()
    return text if text and not is_unresolved_value(text) else ""


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
        return "Professional"
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
    raw_education_items = _profile_list(profile, "medical_education")
    return any("MD" in line or "Medical Doctor" in line or "Doctor of Medicine" in line for line in _education_lines(raw_education_items))


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
    if any(term in haystack for term in ["clinical", "patient", "treatment", "diagnosis", "public health", "nutrition", "hmis"]):
        return "I am a Medical Doctor with clinical, health-program and public-health experience in Afghanistan."
    return ""


MONTH_ABBREVIATIONS = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def _display_period(value: str) -> str:
    """Render a supplied date for a human reader without adding precision.

    ``2020-10`` becomes ``Oct 2020``; a bare year stays a year; any other
    supplied wording is returned unchanged, so a non-precise value can never
    gain invented month- or day-level precision.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if text.lower() in {"present", "current", "now", "ongoing"}:
        return "Present"
    match = re.fullmatch(r"(\d{4})[-/](\d{2})", text)
    if match:
        month = int(match.group(2))
        if 1 <= month <= 12:
            return f"{MONTH_ABBREVIATIONS[month]} {match.group(1)}"
    return text


def _experience_dates(entry: dict[str, Any]) -> str:
    start = _display_period(_resolved_entry_value(entry, "start"))
    end = _display_period(_resolved_entry_value(entry, "end"))
    return f"{start} – {end}" if start and end else start or end


def _language_pairs(lines: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in lines:
        if "—" in line:
            name, level = [part.strip() for part in line.split("—", 1)]
        else:
            name, level = line.strip(), ""
        if name and (name, level) not in pairs:
            pairs.append((name, level))
    return pairs


#: Ordered competency groups used for the professional skills architecture.
#: The first rule that matches a competency name wins, so every verified
#: competency appears exactly once in the rendered CV.
EXPERTISE_GROUP_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Clinical & Medical Practice", ("clinical care", "clinical practice", "clinical assessment", "diagnosis", "treatment", "patient", "curative", "medical doctor", "infection prevention", "ipc")),
    ("Health & Nutrition Programming", ("nutrition", "imam", "cmam", "sam", "mam", "tfu", "otp", "iycf", "imnci", "malnutrition")),
    ("Public Health Systems & Quality", ("bphs", "ephs", "hmis", "dhis2", "moph", "liaison", "quality", "audit")),
    # "Provincial & Ministry of Public Health Stakeholder Coordination" is the
    # applicant's own wording for a coordination competency, so it belongs with
    # the other coordination evidence rather than in the public-health group:
    # a hit-rich label in the wrong group can outvote the group the vacancy
    # itself names.
    ("Programme Coordination & Field Operations", ("coordination", "stakeholder", "monitoring", "reporting", "emergency", "outbreak", "covid", "program implementation", "programme implementation")),
    ("Supervision & Capacity Building", ("supervision", "supervisory", "capacity", "team")),
    ("Safeguarding, Protection & Compliance", ("safeguarding", "psea", "child protection", "protection")),
    ("Supply Chain, Logistics & Administration", ("supply", "forecast", "logistics", "stock", "procurement", "admin", "finance")),
]

UNGROUPED_EXPERTISE_TITLE = "Additional Professional Competencies"

NUMBER_WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
    7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
    13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen",
    18: "eighteen", 19: "nineteen", 20: "twenty", 21: "twenty-one", 22: "twenty-two",
    23: "twenty-three", 24: "twenty-four", 25: "twenty-five", 26: "twenty-six",
    27: "twenty-seven", 28: "twenty-eight", 29: "twenty-nine", 30: "thirty",
}


def _match_expertise_group(competency: str) -> str:
    lowered = str(competency or "").lower()
    for title, needles in EXPERTISE_GROUP_RULES:
        if any(needle in lowered for needle in needles):
            return title
    return UNGROUPED_EXPERTISE_TITLE


def build_expertise_groups(skills: list[str], *, rank_key=None) -> list[dict[str, Any]]:
    """Group verified competencies into the professional skills architecture.

    ``rank_key`` optionally reorders items for a vacancy. It is a sort key
    only: it can never drop, rename, or remove a verified competency.
    """
    items = [str(skill).strip() for skill in skills if str(skill).strip()]
    buckets: dict[str, list[str]] = {}
    for skill in items:
        buckets.setdefault(_match_expertise_group(skill), []).append(skill)
    if rank_key is not None:
        for group_items in buckets.values():
            group_items.sort(key=rank_key)
    sequence = [title for title, _ in EXPERTISE_GROUP_RULES] + [UNGROUPED_EXPERTISE_TITLE]
    groups = [(title, buckets[title]) for title in sequence if buckets.get(title)]
    if rank_key is not None:
        # A group's position reflects the relevance of the group as a whole --
        # its own title plus its best-matching competency -- so the group named
        # after the vacancy's own area leads, while every group and every
        # competency is still printed.
        def group_key(pair: tuple[str, list[str]]) -> tuple[int, int, int]:
            # ``rank_key`` returns (-hits, ...). A group whose own title names
            # the vacancy's area is weighted highest; within that, a group whose
            # competencies match broadly leads a group with a single match.
            title_hits = -rank_key(pair[0])[0]
            item_hits = [-rank_key(item)[0] for item in pair[1]]
            relevance = 3 * title_hits + sum(item_hits)
            return (-relevance, -sum(item_hits), -len(pair[1]))

        groups.sort(key=group_key)
    return [{"group": title, "items": group_items} for title, group_items in groups]


def _focus_terms(job: dict[str, Any], match_report: dict[str, Any]) -> set[str]:
    focus_text = "\n".join([
        str(job.get("title", "")),
        str(job.get("description", "")),
        "\n".join(_focus_labels(match_report, limit=20)),
    ])
    return _tokenize_focus(focus_text)


def _job_title_terms(job: dict[str, Any]) -> set[str]:
    """Focus terms taken from the vacancy title.

    The advertised title is the strongest statement of what a role is about, so
    its terms are counted in addition to the description's when ranking
    verified evidence. It is a presentation signal only -- no term can introduce
    evidence the canonical profile does not already verify.
    """
    if not isinstance(job, dict):
        return set()
    return _tokenize_focus(str(job.get("title") or ""))


def _focus_rank_key(terms: set[str], priority_terms: set[str] | None = None):
    """Stable relevance ordering. Equal relevance keeps canonical order.

    With no usable vacancy focus terms (for example the position-neutral
    master CV) the key is constant, so every caller keeps its canonical
    order instead of an arbitrary length-based shuffle.
    """
    terms = terms or set()
    priority_terms = priority_terms or set()
    if not terms and not priority_terms:
        return lambda _text: (0, 0)

    def key(text: str) -> tuple[int, int]:
        hits = len(_focus_term_hits(text, terms))
        if priority_terms:
            hits += len(_focus_term_hits(text, priority_terms))
        return (-hits, abs(len(str(text)) - 160))

    return key


def _without_attribution(text: str) -> str:
    """Drop the ``(Role | Employer | Location)`` attribution from evidence text.

    Used only where the surrounding sentence already states the role, so a
    letter bullet stays readable. The wording itself is never changed.
    """
    # One nested group is allowed so a parenthesised date range inside the
    # attribution, e.g. "(Role | Org | Place (2020-10 – 2020-12))", is removed.
    cleaned = re.sub(
        r"\s*\((?:[^()]|\([^()]*\))*\|(?:[^()]|\([^()]*\))*\)\s*$",
        "",
        str(text or "").strip(),
    )
    return cleaned.rstrip(".").strip() or str(text or "").strip().rstrip(".")


def _join_and(values: list[str]) -> str:
    clean = [str(value).strip() for value in values if str(value).strip()]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} and {clean[1]}"
    return ", ".join(clean[:-1]) + f", and {clean[-1]}"


def _spell_years(value: float) -> str:
    whole = int(value)
    if float(whole) == float(value):
        return NUMBER_WORDS.get(whole, str(whole))
    if abs((value - whole) - 0.5) < 1e-9:
        return f"{NUMBER_WORDS.get(whole, str(whole))} and a half"
    return NUMBER_WORDS.get(whole, str(whole))


def _verified_duration_phrase(evidence, key: str = "clinical_experience_years") -> str:
    """Spelled-out duration so no unverified numeric precision is printed."""
    years = _max_verified_years(evidence, key)
    if years is None:
        return ""
    lower_bound = any(item.lower_bound for item in evidence.items.get(key, []) if item.verified)
    spelled = _spell_years(years)
    return f"more than {spelled} years" if lower_bound else f"{spelled} years"


def _verified_education_parts(profile: dict[str, Any]) -> tuple[str, str]:
    """Return (field, institution) of the verified medical degree, if supplied."""
    first_medical: tuple[str, str] = ("", "")
    for item in _verified_dict_items(_profile_list(profile, "medical_education")):
        degree = _resolved_entry_value(item, "degree")
        field = _resolved_entry_value(item, "field", "field_of_study", "specialization")
        institution = _resolved_entry_value(item, "institution")
        if not first_medical[0] and not first_medical[1]:
            first_medical = (field, institution)
        if re.search(r"\b(M\.?D\.?|MBBS|Medical Doctor|Doctor of Medicine|Physician)\b", degree, flags=re.IGNORECASE):
            return field, institution
    if _has_verified_md(profile):
        return first_medical
    return "", ""


def _verified_organizations(profile: dict[str, Any]) -> list[str]:
    organizations: list[str] = []
    verified_work, _ = _split_work_entries(profile)
    for entry in verified_work:
        organization = _resolved_entry_value(entry, "organization")
        if organization and organization not in organizations:
            organizations.append(organization)
    return organizations


def _verified_experience_context(profile: dict[str, Any]) -> str:
    verified_work, _ = _split_work_entries(profile)
    haystack = " ".join(_resolved_entry_value(entry, "location") for entry in verified_work).lower()
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    location = str(personal.get("location") or "").lower()
    if personal_field_is_verified(profile, "location"):
        haystack += f" {location}"
    return "Afghanistan" if "afghanistan" in haystack else ""


def _experience_coverage_clauses(evidence, rank_key=None) -> list[str]:
    """Human-readable coverage phrases, each gated on verified evidence."""
    clauses: list[str] = []

    def add(clause: str, *keys: str) -> None:
        if any(evidence.has_verified(key) for key in keys):
            clauses.append(clause)

    add("health and nutrition service delivery", "health_nutrition_experience")
    add("clinical care", "clinical_experience_years", "md_degree")
    add("humanitarian health programming", "ngo_humanitarian", "ngo_experience_years")
    add("public-health service delivery", "public_health_experience")
    add("team supervision and capacity building", "supervision_management")
    add("programme coordination", "program_coordination")
    # The applicant supplied "HMIS/DHIS2 reporting and data quality" as one
    # competency. The earlier clause pair split it into a reporting clause that
    # added "field monitoring" -- a duty this profile explicitly holds as
    # unsupported -- and a rephrased HMIS clause. The reporting evidence now
    # carries the applicant's own wording, and nothing more, exactly once.
    if evidence.has_verified("hmis"):
        clauses.append("HMIS/DHIS2 reporting and data quality")
    elif evidence.has_verified("reporting"):
        clauses.append("health-data reporting")
    add("clinical audit and quality improvement", "quality_improvement")
    add("MoPH and health-authority coordination", "moph_coordination")
    add("emergency and outbreak response", "emergency_response")
    add("safeguarding, PSEA, and child protection", "safeguarding_psea")
    add("medical supply forecasting and logistics", "supply_logistics")
    if rank_key is not None:
        clauses.sort(key=rank_key)
    return clauses


def _is_health_supervisory_role(job: dict[str, Any]) -> bool:
    """True for a supervisory health or nutrition vacancy, judged by its title."""
    title = str(job.get("title") or "").lower()
    return "supervisor" in title and ("health" in title or "nutrition" in title)


# Priority tiers for a supervisory health/nutrition letter, strongest first.
# Clinical, safeguarding, and other lines fall after every tier.
_SUPERVISORY_TIER_TERMS = (
    ("supervis", "nutrition", "bphs", "ephs"),
    ("logistic", "supply", "procure"),
    ("coordinat", "ministry of public health", "moph", "stakeholder", "health authorit"),
    ("hmis", "dhis2"),
)


def _supervisory_tier(text: str) -> int:
    lower = text.lower()
    for tier, terms in enumerate(_SUPERVISORY_TIER_TERMS):
        if any(term in lower for term in terms):
            return tier
    return len(_SUPERVISORY_TIER_TERMS)


def _supervisory_letter_highlights(items: list[str], *, limit: int) -> list[str]:
    """Order verified evidence for a supervisory letter; select, never add.

    Role-attributed experience lines come before bare competency lines (a line
    with a ``|`` in its attribution is a role). Within that, the priority tier
    decides, and the vacancy ranking order breaks ties.
    """

    def key(pair: tuple[int, str]) -> tuple[bool, int, int]:
        index, text = pair
        is_experience = "|" in text
        return (not is_experience, _supervisory_tier(text), index)

    return [text for _, text in sorted(enumerate(items), key=key)][:limit]


# Experience dimensions in the order a supervisory health/nutrition letter leads with.
_SUPERVISORY_DIMENSION_ORDER = (
    "supervision_management",
    "health_nutrition_experience_years",
    "frontline_experience_years",
    "clinical_experience_years",
)


def _supervisory_lead_clauses(evidence) -> list[str]:
    """Coverage clauses for a supervisory health/nutrition letter, verified only.

    Each clause is gated on the same verified evidence key that the general
    coverage clauses use. Clauses without verified evidence are omitted.
    """
    clauses: list[str] = []

    def add(clause: str, *keys: str) -> None:
        if any(evidence.has_verified(key) for key in keys):
            clauses.append(clause)

    add("team supervision and capacity building", "supervision_management")
    add("health and nutrition service delivery", "health_nutrition_experience")
    add("BPHS/EPHS-related service delivery", "bphs", "ephs")
    add("medical supply forecasting and logistics", "supply_logistics")
    add("MoPH and health-authority coordination", "moph_coordination")
    return clauses


def _professional_profile_paragraph(
    profile: dict[str, Any],
    evidence,
    job: dict[str, Any],
    match_report: dict[str, Any],
    competencies: list[str],
    organization_order: list[str] | None = None,
    *,
    first_person: bool = False,
    has_languages_section: bool = False,
) -> str:
    """Build a substantive professional profile from verified facts only.

    Every sentence restates verified canonical-profile evidence: the verified
    medical degree (plus, when verified, the exit exam and registration), the
    verified duration lower bound, the verified experience dimensions, the
    verified employers, the verified competency inventory, and the verified
    languages. No achievement, number, date, or duty is invented, and no
    unverified profile item can appear here. ``first_person`` only changes
    sentence voice for a cover letter; it never changes the evidence used.

    ``has_languages_section`` is set when the caller's document prints its own
    LANGUAGES section, which carries the same verified languages in the same
    words. The summary then omits its languages sentence so one fact is not
    printed twice in one document. Every other sentence is unchanged: the
    narrative, the coverage areas, the employers and the headline competencies
    all remain in the summary as well as being detailed in their own sections.
    """
    owner_summary = _verified_profile_summary(profile)
    if owner_summary:
        return owner_summary
    rank_key = _focus_rank_key(_focus_terms(job, match_report))
    sentences: list[str] = []
    if not evidence.has_verified("md_degree"):
        # Nothing substantive is verified yet, so the document states that
        # plainly instead of presenting an unverified profile as a credential.
        sentences.append(
            "This document is generated only from verified canonical-profile facts, and no verified "
            "professional credential is recorded yet. Confirm the profile before using it."
            if first_person
            else "This CV is generated only from verified canonical-profile facts, and no verified "
            "professional credential is recorded yet. Confirm the profile before using this document."
        )
        languages = _language_lines(profile, verified_only=True)
        if languages:
            sentences.append("Languages: " + ", ".join(_lowercase_level(line) for line in languages) + ".")
        return " ".join(sentences)

    field, institution = _verified_education_parts(profile)
    identity = "Medical Doctor (MD)"
    if field:
        identity += f" qualified in {field}"
    if institution:
        identity += f" at {institution}"
    credentials: list[str] = []
    if evidence.has_verified("medical_exit_exam"):
        credentials.append("a completed Medical Exit Examination")
    if evidence.has_verified("license_registration"):
        credentials.append("a valid medical professional registration/license")
    lead = f"I am a {identity}" if first_person else identity
    identity_sentence = lead + (f", with {_join_and(credentials)}" if credentials else "") + "."
    # A cover letter for a supervisory health/nutrition vacancy leads with the
    # verified supervision and field experience; the medical identity follows.
    supervisory = first_person and _is_health_supervisory_role(job)
    if not supervisory:
        sentences.append(identity_sentence)

    duration = _verified_duration_phrase(evidence)
    if duration:
        dimension_pairs = [
            ("clinical_experience_years", "clinical"),
            ("health_nutrition_experience_years", "health and nutrition"),
            # The applicant's own profile claims "combined field and
            # supervisory experience", so supervision is named whenever the
            # canonical record carries supervision evidence.
            ("supervision_management", "supervisory"),
            ("frontline_experience_years", "field"),
        ]
        if supervisory:
            dimension_pairs.sort(key=lambda pair: _SUPERVISORY_DIMENSION_ORDER.index(pair[0]))
        dimensions = [label for key, label in dimension_pairs if evidence.has_verified(key)]
        if dimensions:
            joined = _join_and(dimensions) if len(dimensions) > 1 else dimensions[0]
            amount = f"{duration} of combined {joined} experience" if len(dimensions) > 1 else f"{duration} of {joined} experience"
            context = _verified_experience_context(profile)
            if first_person:
                sentences.append(f"I bring {amount}" + (f" in {context}" if context else "") + ".")
            else:
                sentences.append(f"Brings {amount}" + (f" in {context}" if context else "") + ".")

    clauses = _supervisory_lead_clauses(evidence) if supervisory else _experience_coverage_clauses(evidence, rank_key)
    if clauses:
        lead_in = "My professional experience covers" if first_person else "Professional experience covers"
        sentences.append(f"{lead_in} {_join_and(clauses[:6])}.")
    if supervisory:
        sentences.append(identity_sentence)

    organizations = _verified_organizations(profile)
    if organizations and organization_order:
        # A tailored CV already ordered its roles by vacancy relevance, and the
        # cover letter follows the same verified order.
        preferred = [org for org in organization_order if org in organizations]
        preferred = list(dict.fromkeys(preferred))
        remainder = [org for org in organizations if org not in preferred]
        organizations = preferred + remainder
    elif organizations and rank_key is not None and not first_person:
        organizations = sorted(organizations, key=rank_key)
    if organizations:
        lead_in = "My experience includes work with" if first_person else "Employment history includes assignments with"
        sentences.append(f"{lead_in} {_join_and(organizations[:4])}.")

    if competencies:
        lead_in = "My core technical competencies include" if first_person else "Core technical competencies include"
        sentences.append(f"{lead_in} {_join_and(competencies[:8])}.")

    if not has_languages_section:
        languages = _language_lines(profile, verified_only=True)
        if languages:
            rendered = ", ".join(_lowercase_level(line) for line in languages)
            sentences.append(f"Languages: {rendered}.")
    return " ".join(sentence for sentence in sentences if sentence)


def _lowercase_level(line: str) -> str:
    """Render a language line as prose, e.g. ``English (fluent)``."""
    if "—" in line:
        name, level = line.split("—", 1)
        level = level.strip()
        return f"{name.strip()} ({level.lower()})" if level else name.strip()
    return line.strip()


def _cv_references_section() -> list[str]:
    """Default CV reference line: no private contact data is ever printed."""
    return ["Available on request for shortlisted applications."]


def _render_canonical_cv_text(model: dict[str, Any]) -> str:
    """Serialize the one CV model used by TXT, PDF and DOCX.

    Section order is the professional one: profile, competencies, experience,
    credentials, training, languages, references. Section headings are stable
    because they are the same strings an ATS parser and the DOCX/PDF design
    system both key on.
    """
    lines = [str(model.get("name") or "CONFIRM BEFORE SUBMISSION"), str(model.get("headline") or "Professional")]
    lines.extend(str(item) for item in model.get("contact_lines") or [] if str(item).strip())
    lines.extend(["", "PROFESSIONAL SUMMARY", str(model.get("profile") or ""), ""])

    expertise = [group for group in (model.get("expertise") or []) if group.get("items")]
    if expertise:
        lines.append("CORE PROFESSIONAL COMPETENCIES")
        for group in expertise:
            items = "; ".join(str(item) for item in group.get("items") or [])
            lines.append(f"{group.get('group')}: {items}")
        lines.append("")
    elif model.get("strengths"):
        lines.extend(["CORE PROFESSIONAL COMPETENCIES", *[f"- {item}" for item in model["strengths"]], ""])

    if model.get("experience"):
        lines.append("PROFESSIONAL EXPERIENCE")
        for item in model["experience"]:
            if item.get("role"):
                lines.append(str(item["role"]))
            metadata = " | ".join(str(value) for value in [item.get("org"), item.get("loc"), item.get("dates")] if value)
            if metadata:
                lines.append(metadata)
            lines.extend(f"- {bullet}" for bullet in item.get("bullets") or [])
            lines.append("")

    for title, values in [
        ("EDUCATION", model.get("education") or []),
        ("PROFESSIONAL REGISTRATION", model.get("registration") or []),
        ("MEDICAL EXIT EXAMINATION", model.get("exit_exam") or []),
        ("PROFESSIONAL TRAINING & CERTIFICATIONS", model.get("certifications") or []),
    ]:
        if values:
            lines.extend([title, *[f"- {value}" for value in values], ""])

    if model.get("languages"):
        language_line = "  |  ".join(f"{name}{(' — ' + level) if level else ''}" for name, level in model["languages"])
        lines.extend(["LANGUAGES", f"- {language_line}", ""])

    references = [str(item) for item in (model.get("references") or []) if str(item).strip()]
    if references:
        lines.extend(["REFERENCES", *[f"- {value}" for value in references], ""])
    return "\n".join(lines).strip() + "\n"


def generate_master_cv(profile: dict[str, Any]) -> dict[str, Any]:
    """Build a position-neutral master-CV model from verified canonical facts.

    This is deliberately separate from vacancy tailoring. It preserves the
    supplied work-history order, the complete verified competency inventory,
    every verified certificate, and every verified responsibility; it receives
    no vacancy, match report, employer, or target-title input, so a role's
    wording and priority can never become a new canonical applicant fact.

    The master CV is comprehensive rather than short: verified role scope,
    grouped technical competencies, credentials, training, and languages are
    all presented, and no verified evidence is dropped to reduce page count.
    """
    profile = require_runtime_profile(profile)
    evidence = build_profile_evidence(profile)
    raw_education_items = _profile_list(profile, "medical_education")
    education = _education_lines(raw_education_items)
    work_entries, unverified_work = _split_work_entries(profile)
    verified_skills, unverified_skills = _skills_by_verification(profile)
    certs_verified, unverified_certs = _certificates_by_verification(profile)
    languages = _language_lines(profile, verified_only=True)
    unverified_languages = [item for item in _language_lines(profile) if item not in languages]

    expertise = build_expertise_groups(verified_skills)

    # The canonical profile keeps the owner's source order. In contrast to a
    # vacancy CV, there is no relevance score and therefore no role-specific
    # reordering or selection.
    experience = [
        {
            "role": _resolved_entry_value(entry, "title"),
            "org": _resolved_entry_value(entry, "organization"),
            "loc": _resolved_entry_value(entry, "location"),
            "dates": _experience_dates(entry),
            "bullets": _split_substantive_bullets(_entry_text_values(entry)),
        }
        for entry in work_entries
    ]
    model = {
        "name": _full_name(profile),
        "headline": _verified_profile_title(profile, evidence) or "Medical Doctor",
        "contact_lines": _contact_lines(profile),
        "profile": _professional_profile_paragraph(
            profile,
            evidence,
            {},
            {},
            [item for group in expertise for item in group["items"]],
            has_languages_section=True,
        ),
        "expertise": expertise,
        "strengths": [item for group in expertise for item in group["items"]],
        "experience": experience,
        "education": education,
        "registration": evidence.evidence_text("license_registration", verified_only=True) if evidence.has_verified("license_registration") else [],
        "exit_exam": evidence.evidence_text("medical_exit_exam", verified_only=True) if evidence.has_verified("medical_exit_exam") else [],
        "certifications": _safe_bullets(certs_verified),
        "languages": _language_pairs(languages),
        "references": _cv_references_section(),
    }
    warnings: list[str] = []
    undated = [item["role"] for item in experience if not item.get("dates")]
    if undated:
        # A missing date is reported for owner review rather than invented.
        warnings.append(
            "Work-history dates were not supplied for: " + "; ".join(undated) + ". They are presented without dates and no dates were invented."
        )
    for entry in unverified_work:
        label = _experience_header(entry) if isinstance(entry, dict) else str(entry).strip()
        if label:
            warnings.append(f"Unverified work history omitted from master CV: {label}")
    if unverified_skills:
        warnings.append("Unverified skills omitted from master CV: " + ", ".join(unverified_skills[:15]))
    if unverified_certs:
        warnings.append("Unverified certificates/training omitted from master CV: " + ", ".join(unverified_certs[:15]))
    if unverified_languages:
        warnings.append("Unverified languages omitted from master CV: " + ", ".join(unverified_languages[:10]))
    pending_warning = _pending_responsibility_warning(profile)
    if pending_warning:
        warnings.append(pending_warning)

    return {
        "generated_at": date.today().isoformat(),
        "position_neutral": True,
        "master_cv_model": model,
        "master_cv_text": _render_canonical_cv_text(model),
        "review_warnings": warnings,
        "provenance": {
            "profile_fields": ["personal", "professional_summary", "medical_education", "license_registration", "medical_exit_exam", "work_history", "skills", "languages", "certificates", "experience_evidence", "clinical_experience"],
            "tailoring_method": "none — position-neutral presentation of verified canonical-profile evidence only",
        },
    }


def write_master_cv(
    profile: dict[str, Any],
    *,
    out_dir: str | Path = project_path("documents/master_cv"),
) -> dict[str, Any]:
    """Write TXT/DOCX/PDF position-neutral master-CV artifacts locally.

    The output belongs under the ignored documents directory and never writes
    back into ``profile.yaml``. Vacancy-specific CVs continue to use
    ``prepare_application_bundle`` downstream of matching/tailoring.
    """
    master = generate_master_cv(profile)
    out = Path(out_dir)
    base = out / f"{_safe_slug(_full_name(profile), max_len=70)}_position_neutral_master_cv"
    master["generated_paths"] = _write_text_docx_pdf(
        master["master_cv_text"],
        base,
        document_type="cv",
        metadata={"document_kind": "position-neutral master CV"},
        canonical_cv_model=master["master_cv_model"],
    )
    return master


def generate_tailored_documents(
    job: dict[str, Any],
    profile: dict[str, Any],
    match_report: dict[str, Any],
) -> dict[str, Any]:
    """Generate a vacancy-specific CV and cover letter from profile.yaml facts.

    The documents are deterministic: they select and order verified canonical
    profile evidence against vacancy requirements.  CV imports, caches, and
    draft profiles are rejected rather than becoming a second applicant source.
    """
    profile = require_runtime_profile(profile)
    evidence = build_profile_evidence(profile)
    name = _full_name(profile)
    contact = _contact_lines(profile)
    title = job.get("title") or "the advertised role"
    company = job.get("company") or "your organization"
    location = job.get("location") or ""

    focus_labels = _focus_labels(match_report)
    focus_phrases = _job_focus_phrases(job, match_report)
    if _is_health_supervisory_role(job):
        # Every verified evidence line is a candidate; the supervisory priority
        # orders them. The vacancy-overlap filter is not used here, because it
        # would drop verified logistics evidence that shares no keyword with
        # the vacancy text.
        vacancy_highlights = _supervisory_letter_highlights(_profile_evidence_lines(profile), limit=6)
    else:
        vacancy_highlights = _vacancy_fit_highlights(profile, job, match_report, limit=6)

    # DOCUMENT EVIDENCE GATE: every factual section below is restricted to
    # explicitly verified items. Credential-style facts (education, license,
    # exam) already required explicit verification; the same single rule now
    # governs work history, skills, certificates/training, languages, and the
    # professional summary. Unverified items are collected into review
    # warnings instead of being printed as employer-facing facts.
    raw_education_items = _profile_list(profile, "medical_education")
    education = _education_lines(raw_education_items)
    unverified_education = [item for item in raw_education_items if not _is_verified_entry(item)]

    work_entries, unverified_work = _split_work_entries(profile)
    verified_skills, unverified_skills = _skills_by_verification(profile)
    certs_verified, unverified_certs = _certificates_by_verification(profile)
    # A professional CV may be three or four pages when verified evidence
    # warrants it. Core competencies are ordered for the vacancy, never cut to
    # a fixed count.
    certs = _safe_bullets(certs_verified)
    # Tailoring is ordering, never selection: every verified competency is kept
    # and only its position inside its professional group (and the position of
    # the group itself) is driven by the vacancy's focus.
    focus_rank_key = _focus_rank_key(_focus_terms(job, match_report), _job_title_terms(job))
    skills_bullets = sorted(verified_skills, key=focus_rank_key)
    expertise = build_expertise_groups(verified_skills, rank_key=focus_rank_key)

    # Languages: only explicitly verified languages (name + resolved level +
    # verified: true) may be listed as factual CV content. Unverified mentions
    # (unverified profile data) are review warnings, never employer-facing facts.
    languages = _language_lines(profile, verified_only=True)
    unverified_languages = [item for item in _language_lines(profile) if item not in languages]

    professional_title = _professional_title(profile, evidence, job, match_report)
    signature_title = _signature_title(profile, evidence)

    ordered_work: list[dict[str, Any]] = []
    if work_entries:
        most_relevant, remaining = _tailored_work_sections(work_entries, job, match_report)
        # Tailoring is ordering only. Every verified role and every substantive
        # responsibility is retained, including roles that are less relevant to
        # the vacancy at hand.
        for entry in most_relevant + remaining:
            ordered_work.append(
                {
                    "role": _resolved_entry_value(entry, "title"),
                    "org": _resolved_entry_value(entry, "organization"),
                    "loc": _resolved_entry_value(entry, "location"),
                    "dates": _experience_dates(entry),
                    "bullets": _entry_bullets_for_job(entry, job, match_report),
                }
            )

    ranked_competencies = [item for group in expertise for item in group["items"]]
    summary = _professional_profile_paragraph(
        profile,
        evidence,
        job,
        match_report,
        ranked_competencies,
        organization_order=[entry["org"] for entry in ordered_work if entry.get("org")],
        has_languages_section=True,
    )

    canonical_cv_model = {
        "name": name,
        "headline": professional_title,
        "contact_lines": contact,
        "profile": summary,
        "expertise": expertise,
        "strengths": skills_bullets,
        "experience": ordered_work,
        "education": education,
        "registration": evidence.evidence_text("license_registration", verified_only=True) if evidence.has_verified("license_registration") else [],
        "exit_exam": evidence.evidence_text("medical_exit_exam", verified_only=True) if evidence.has_verified("medical_exit_exam") else [],
        "certifications": certs,
        "languages": _language_pairs(languages),
        "references": _cv_references_section(),
    }
    cv_text = _render_canonical_cv_text(canonical_cv_model)

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
    pending_warning = _pending_responsibility_warning(profile)
    if pending_warning:
        warnings.append(pending_warning)

    facts = match_report.get("facts", {})
    metadata = job.get("metadata", {}) if isinstance(job.get("metadata", {}), dict) else {}
    reference = facts.get("reference_number") or metadata.get("reference_number")
    # One subject rule for the letter and the email draft, so they cannot drift.
    suggested_subject = _email_subject(
        str(job.get("title") or ""),
        requested_subject=str(facts.get("application_subject") or metadata.get("application_subject") or ""),
        reference=str(reference or ""),
    )

    cover_lines = [
        f"Subject: {suggested_subject}",
        "",
        "Dear Hiring Committee,",
        "",
        f"I am writing to apply for the {title} position{(' in ' + location) if location else ''} at {company}.",
        "",
    ]
    # The letter body restates the same verified evidence as the CV, in the
    # first person. It never claims a credential, duration, or duty that the
    # canonical profile does not already verify.
    intro = _professional_profile_paragraph(
        profile,
        evidence,
        job,
        match_report,
        ranked_competencies,
        organization_order=[entry["org"] for entry in ordered_work if entry.get("org")],
        first_person=True,
    )
    cover_lines.append(intro)
    if vacancy_highlights:
        strongest = [_without_attribution(item) for item in vacancy_highlights[:3]]
        cover_lines.extend(["", "Relevant verified experience for this role includes:"])
        cover_lines.extend(f"- {item}" for item in strongest if item)
    elif focus_phrases:
        cover_lines.extend(["", f"I understand that the vacancy emphasizes {', '.join(focus_phrases[:3])}, and my verified experience covers these areas."])
    if any(value is True for value in evidence.verified_values("field_deployment")):
        cover_lines.extend(["", "I am available for field deployment in line with the needs of the position."])
    elif any(value is True for value in evidence.verified_values("willing_to_relocate")):
        cover_lines.extend(["", "I am willing to relocate or deploy for the position if selected."])
    cover_lines.extend([
        "",
        "I would welcome the opportunity to discuss how my qualifications can support your health programme and the communities served by this position. Thank you for considering my application.",
        "",
        "Sincerely,",
        name,
    ])
    if signature_title:
        cover_lines.append(signature_title)
    cover_lines.extend([
        f"Email: {_safe_contact_value(profile, 'email')}",
        f"Phone: {_safe_contact_value(profile, 'phone')}",
    ])

    return {
        "generated_at": date.today().isoformat(),
        "job_id": job.get("id"),
        "job_title": title,
        "company": company,
        "tailored_cv_text": cv_text,
        "tailored_cv_model": canonical_cv_model,
        "cover_letter": "\n".join(cover_lines).strip() + "\n",
        "suggested_subject": suggested_subject,
        "matched_requirements_used": focus_labels,
        "selected_vacancy_fit_evidence": vacancy_highlights,
        "review_warnings": warnings,
        "provenance": {
            "profile_fields": ["personal", "medical_education", "license_registration", "medical_exit_exam", "work_history", "skills", "languages", "certificates"],
            "job_source_url": facts.get("source_url") or metadata.get("source_url") or job.get("url"),
            "application_url": facts.get("application_url") or job.get("apply_url"),
            "tailoring_method": "ranked canonical-profile evidence against extracted vacancy requirements and source text",
        },
    }

def _extract_email(value: str | None) -> str:
    if not value:
        return ""
    match = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", str(value), flags=re.IGNORECASE)
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
        f"Email: {_safe_contact_value(profile, 'email')}",
        f"Phone: {_safe_contact_value(profile, 'phone')}",
        f"Current location: {personal.get('location') if personal.get('location') and not is_unresolved_value(personal.get('location')) and personal_field_is_verified(profile, 'location') else 'confirm before submit'}",
        f"Position applied for: {job.get('title', 'confirm exact title')}",
        "Education: use only education shown in the reviewed canonical profile",
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
        text = re.sub(r"\s+", " ", _without_attribution(str(item or ""))).strip(" -•.")
        if not text:
            continue
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
    profile: dict[str, Any],
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
        f"Email: {_safe_contact_value(profile, 'email')}",
        f"Phone: {_safe_contact_value(profile, 'phone')}",
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
    profile = require_runtime_profile(profile)
    if str((match_report or {}).get("readiness_status") or "") == NOT_ELIGIBLE_STATUS:
        # Keep this callable for an explicit, auditable blocked-state response
        # (the bundle orchestrator refuses document generation earlier). Never
        # represent a proven-ineligible role as a review-ready package.
        blocked = {
            "job_id": job.get("id"),
            "job_title": str(job.get("title") or "the advertised role"),
            "company": str(job.get("company") or ""),
            "route_type": "blocked",
            "application_method": "UNAVAILABLE",
            "package_status": "BLOCKED",
            "source_url": "",
            "official_vacancy_page": "",
            "deadline": "",
            "vacancy_reference": "",
            "application_route": "",
            "apply_email": "",
            "apply_url": None,
            "email_draft": None,
            "online_application": None,
            "form_fields_checklist": [],
            "required_documents_checklist": [],
            "review_warnings": ["BLOCKED: authoritative matching classified this vacancy as NOT_ELIGIBLE."],
            "special_instructions": [],
            "user_required_actions": ["Do not submit an application package unless the authoritative eligibility finding is corrected with verified evidence."],
            "missing_items": ["Eligibility is NOT_ELIGIBLE"],
            "no_submission_performed": True,
        }
        blocked["text"] = render_application_package(blocked)
        return blocked
    facts = match_report.get("facts", {}) if isinstance(match_report, dict) else {}
    metadata = job.get("metadata", {}) if isinstance(job.get("metadata", {}), dict) else {}
    docs = tailored_documents or {}
    generated_paths = generated_paths or {}
    name = _full_name(profile)
    title = str(job.get("title") or docs.get("job_title") or "the advertised role")
    company = str(job.get("company") or docs.get("company") or "")
    # Source listing provenance is independent from the vacancy page. Never
    # relabel job.url as a source URL when the source did not provide one.
    source_url = facts.get("source_url") or metadata.get("source_url") or ""
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
    # CONTACT/IDENTITY CONTRACT: every printed identity/contact field must be
    # present, resolved, and explicitly confirmed on its own. A generic
    # document marker is never enough for a package to be review-ready.
    identity_fields = ["first_name", "last_name", "email", "phone"]
    unresolved_identity = [
        field
        for field in identity_fields
        if not personal.get(field) or is_unresolved_value(personal.get(field)) or not personal_field_is_verified(profile, field)
    ]
    if unresolved_identity:
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
                profile=profile,
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
            "Complete each form field using the checklist and verified canonical-profile facts only",
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
    canonical_cv_model: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Write TXT plus globally designed DOCX/PDF exports.

    The TXT file remains the canonical plain-text source.  DOCX/PDF are
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
            canonical_cv_model=canonical_cv_model,
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
    out_dir: str | Path = project_path("documents/applications"),
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
        canonical_cv_model=tailored_documents.get("tailored_cv_model"),
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
    out_dir: str | Path = project_path("documents/applications"),
) -> dict[str, Any]:
    """Generate documents, application package, and file exports for one job.

    Application documents are only generated for eligible or reviewable
    vacancies.  A deterministic NOT_ELIGIBLE match means the pipeline must not
    create positive CV/cover-letter artifacts for that role.
    """
    profile = require_runtime_profile(profile)
    if str(match_report.get("readiness_status") or "") == NOT_ELIGIBLE_STATUS:
        raise ValueError(
            f"Refusing to prepare application documents for NOT_ELIGIBLE vacancy {job.get('id') or job.get('title') or ''}".strip()
        )
    docs = generate_tailored_documents(job, profile, match_report)
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
