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
        # Canonical rule: only a literal boolean True counts as verified.
        # This deliberately does NOT use bool(verified) -- bool("false") and
        # bool(0 if accidentally passed as "0") etc. are traps that would
        # silently coerce a non-boolean "truthy" value (e.g. the string
        # "true", "yes", or the integer 1) into verified evidence. Every
        # caller is expected to have already resolved its own verification
        # decision via is_verified_flag()/parse_tristate() before calling
        # add(); this check is a second, independent backstop against
        # truthiness coercion inside the evidence store itself.
        verified = verified is True
        bucket = self.items.setdefault(key, [])
        for item in bucket:
            if item.value == value and item.source == source:
                # A later, more authoritative (explicitly verified) add for a
                # fact already recorded as unverified must upgrade it rather
                # than being silently dropped as a duplicate -- otherwise an
                # owner-confirmed `verified: true` item could be shadowed by
                # an earlier unverified mention of the same text/value.
                if verified and not item.verified:
                    item.verified = True
                    if quote:
                        item.quote = str(quote)
                return
        bucket.append(EvidenceItem(key=key, value=value, source=source, quote=str(quote or value), verified=verified))

    def has(self, key: str) -> bool:
        return bool(self.items.get(key))

    def has_verified(self, key: str) -> bool:
        """True only when at least one item for this key is explicitly verified."""
        return any(item.verified for item in self.items.get(key, []))

    def values(self, key: str) -> list[Any]:
        return [item.value for item in self.items.get(key, [])]

    def first(self, key: str, default: Any = None) -> Any:
        values = self.values(key)
        return values[0] if values else default

    def evidence_text(self, key: str, *, verified_only: bool = False) -> list[str]:
        return [item.quote for item in self.items.get(key, []) if item.quote and (not verified_only or item.verified)]

    def verified_values(self, key: str) -> list[Any]:
        return [item.value for item in self.items.get(key, []) if item.verified]

    def to_dict(self) -> dict[str, Any]:
        return {key: [item.to_dict() for item in items] for key, items in self.items.items()}


# ---------------------------------------------------------------------------
# Canonical verification/boolean semantics
#
# This is the single mechanism used across the whole product to decide
# whether a fact is verified or whether a yes/no field is resolved.  Nothing
# else in this codebase should re-implement these rules or rely on Python
# truthiness for semantic values.
# ---------------------------------------------------------------------------

#: Tokens that mean "this value is not yet known/confirmed". Case-insensitive.
UNRESOLVED_TOKENS = {
    "needs verification",
    "need verification",
    "unverified",
    "unknown",
    "unconfirmed",
    "pending",
    "tbd",
    "n/a",
    "na",
    "not provided",
    "not specified",
    "none",
    "",
}

#: Tokens that resolve a yes/no field to True.
YES_TOKENS = {"yes", "y", "true", "confirmed", "willing", "available"}

#: Tokens that resolve a yes/no field to False.
NO_TOKENS = {"no", "n", "false", "unwilling", "not willing", "unavailable"}


def is_unresolved_value(value: Any) -> bool:
    """True when ``value`` is a placeholder such as "Needs verification".

    This never uses truthiness: an explicit ``False`` or ``0`` is NOT
    unresolved, only recognised placeholder text (or an empty/None value) is.
    """
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    text = str(value).strip().lower()
    return text in UNRESOLVED_TOKENS


def parse_tristate(value: Any) -> bool | None:
    """Canonical yes/no/unresolved parser for semantic boolean profile fields.

    Returns ``True``/``False`` only for recognised yes/no tokens (or native
    Python booleans). Anything else -- including "Needs verification",
    "Unknown", "Unconfirmed", empty strings, or unrecognised free text --
    returns ``None`` (unresolved). This deliberately never falls back to
    ``bool(value)`` truthiness.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in YES_TOKENS:
        return True
    if text in NO_TOKENS:
        return False
    return None


def is_verified_flag(value: Any) -> bool:
    """Canonical interpretation of an explicit ``verified`` schema field.

    Only a literal boolean ``True`` counts as verified. Strings such as
    ``"Needs verification"``, ``"Unknown"``, ``"true"``, or any other
    non-boolean value are NOT verified. A missing field is NOT verified.
    This function intentionally does not use ``bool(value)`` truthiness.
    """
    return value is True


PERSONAL_VERIFICATION_FIELDS = {
    "first_name",
    "last_name",
    "email",
    "phone",
    "location",
    "nationality",
    "gender",
    "linkedin",
    "professional_title",
}


def personal_field_is_verified(profile: dict[str, Any], key: str) -> bool:
    """Return the explicit verification status of one personal field.

    ``personal.verification.<field>: true`` is the only way a personal fact
    becomes verified evidence, so identity, contact, gender, nationality,
    location, and professional title are each confirmed on their own:
    confirming an email never verifies gender. Only a literal boolean
    ``true`` counts.
    """
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    verification = personal.get("verification") or {}
    return isinstance(verification, dict) and is_verified_flag(verification.get(key))


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
    "quality_improvement": [r"\bquality\s+improvement\b", r"\bquality\s+assurance\b", r"\bQA\s*/\s*QI\b", r"\bclinical\s*/\s*service\s+audit\b", r"\bclinical\s+audit\b"],
    "emergency_response": [r"emergency response", r"outbreak", r"COVID-?19", r"rapid response", r"contact tracing"],
    "supply_logistics": [r"medical supply", r"stock (?:management|monitoring)", r"forecasting", r"logistics", r"procurement"],
}

LANGUAGE_ALIASES = {
    "english": ["english"],
    "dari": ["dari"],
    "pashto": ["pashto", "pushto"],
}

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
        # A work-history entry only counts toward verified years-of-experience
        # evidence when the owner has explicitly confirmed it (`verified: true`).
        # Dates existing on an entry are not enough by themselves.
        if not is_verified_flag(entry.get("verified")):
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


def _iter_dicts(value: Any) -> list[dict[str, Any]]:
    """Collect every dict found within a (possibly nested) list/dict value."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for item in value.values():
            found.extend(_iter_dicts(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_iter_dicts(item))
    return found


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
        "professional_summary",
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
        if isinstance(item, dict):
            # Join only the human-facing, resolved descriptive fields; never
            # leak the internal `verified` flag value (e.g. the literal word
            # "False") or unresolved placeholders ("Needs verification") into
            # evidence text shown to the user.
            display_fields = {k: v for k, v in item.items() if k != "verified" and not is_unresolved_value(v)}
            text = " ".join(_iter_strings(display_fields))
            verified = is_verified_flag(item.get("verified"))
        else:
            text = str(item)
            verified = False
        if re.search(r"\b(M\.?D\.?|MBBS|Medical Doctor|Doctor of Medicine|Physician)\b", text, flags=re.I):
            evidence.add("md_degree", True, "profile.medical_education", text, verified=verified)
            evidence.add("medical_education", text, "profile.medical_education", text, verified=verified)


def _add_license(evidence: ProfileEvidence, profile: dict[str, Any]) -> None:
    candidates = []
    medical = profile.get("medical", {}) if isinstance(profile.get("medical"), dict) else {}
    for key in ["license", "registration", "license_registration"]:
        if key in medical:
            candidates.append(medical[key])
        if key in profile:
            candidates.append(profile[key])
    for candidate in candidates:
        if candidate in (None, "", {}, []):
            continue
        text = " ".join(_iter_strings(candidate))
        if isinstance(candidate, dict):
            number = candidate.get("number") or candidate.get("registration_number") or candidate.get("id")
            verified = is_verified_flag(candidate.get("verified"))
            status_text = str(candidate.get("status", "") or "")
            status_resolved = status_text and not is_unresolved_value(status_text)
            # A placeholder like "Needs verification" is intentionally not evidence.
            if not (verified or number or status_resolved):
                continue
            authority = candidate.get("authority") or candidate.get("council") or candidate.get("issuer")
            authority_known = authority and not is_unresolved_value(authority)
            if status_resolved:
                quote = status_text
            elif verified and authority_known:
                quote = f"Medical professional registration/license confirmed by profile owner ({authority})"
            elif verified:
                quote = "Medical professional registration/license confirmed in profile"
            else:
                quote = "License/registration details present in profile; not yet explicitly verified"
            if authority_known and str(authority) not in quote:
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
            elif is_verified_flag(candidate.get("document_verified")) or (verified and parse_tristate(candidate.get("copy_available")) is True):
                # parse_tristate, not truthiness: copy_available: "no"/"Needs
                # verification" must never count as an available document.
                evidence.add("license_document", True, "profile.license_registration", "License/registration document marked available in profile", verified=verified)
        else:
            if is_unresolved_value(text):
                continue
            evidence.add("license_registration", True, "profile.license_registration", text, verified=False)


def _add_medical_exit_exam(evidence: ProfileEvidence, profile: dict[str, Any]) -> None:
    exam = profile.get("medical_exit_exam")
    if exam in (None, "", {}, []):
        return
    if isinstance(exam, dict):
        verified = is_verified_flag(exam.get("verified"))
        status_text = str(exam.get("status", "") or "")
        status_resolved = status_text and not is_unresolved_value(status_text)
        if not (verified or status_resolved):
            return
        if status_resolved:
            quote = status_text
        elif verified:
            quote = "Medical Exit Exam completion confirmed in profile"
        else:
            quote = "Medical Exit Exam status present in profile; not yet explicitly verified"
        evidence.add("medical_exit_exam", True, "profile", quote, verified=verified)
    else:
        text = str(exam)
        if not is_unresolved_value(text):
            evidence.add("medical_exit_exam", True, "profile", text, verified=False)


def _add_languages(evidence: ProfileEvidence, profile: dict[str, Any], texts: list[tuple[str, str]]) -> None:
    languages = profile.get("languages", {})
    if isinstance(languages, dict):
        # A bare {name: level} mapping has no field to carry an explicit
        # verification flag, so it can never be treated as verified evidence.
        for name, level in languages.items():
            canonical = _canonical_language(name)
            if canonical and not is_unresolved_value(level):
                evidence.add(f"language_{canonical}", level, "profile.languages", f"{name}: {level}", verified=False)
    elif isinstance(languages, list):
        for item in languages:
            if isinstance(item, dict):
                name = item.get("name") or item.get("language") or ""
                level = item.get("level") or item.get("proficiency") or ""
                # Verification requires an explicit `verified: true` AND a
                # resolved (non-placeholder) level; a contradictory
                # combination (verified: true with level "Needs verification")
                # is treated conservatively as unverified.
                verified = is_verified_flag(item.get("verified")) and not is_unresolved_value(level)
            else:
                name, level, verified = str(item), "", False
            canonical = _canonical_language(name)
            if canonical and not is_unresolved_value(level):
                evidence.add(f"language_{canonical}", level or True, "profile.languages", f"{name}: {level}" if level else str(name), verified=verified)
            elif canonical and is_unresolved_value(level):
                # Keep a record that the language was mentioned, but it must
                # never satisfy a hard language requirement.
                evidence.add(f"language_{canonical}", level or "Needs verification", "profile.languages", f"{name}: unresolved proficiency", verified=False)

    for source, text in texts:
        for canonical, aliases in LANGUAGE_ALIASES.items():
            if any(re.search(rf"\b{re.escape(alias)}\b", text, flags=re.I) for alias in aliases):
                evidence.add(f"language_{canonical}", True, source, _quote_for_alias(text, aliases), verified=False)


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


def _add_term_matches(evidence: ProfileEvidence, text: str, source: str, *, verified: bool) -> None:
    for key, patterns in MEDICAL_TERM_KEYS.items():
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                quote = normalize_text(text[max(0, match.start() - 50): match.end() + 50])
                evidence.add(key, True, source, quote, verified=verified)
                break


def _add_terms(evidence: ProfileEvidence, texts: list[tuple[str, str]]) -> None:
    for source, text in texts:
        _add_term_matches(evidence, text, source, verified=False)


def _add_verified_profile_terms(evidence: ProfileEvidence, profile: dict[str, Any]) -> None:
    """Promote terms from explicitly verified profile facts into verified evidence."""
    work = profile.get("work_history") or profile.get("experience") or []
    if isinstance(work, list):
        for entry in work:
            if isinstance(entry, dict) and is_verified_flag(entry.get("verified")):
                text = "\n".join(_iter_strings({k: v for k, v in entry.items() if k != "verified"}))
                _add_term_matches(evidence, text, "profile.work_history", verified=True)
    for key in ["skills", "certificates", "certifications", "training"]:
        for item in _iter_dicts(profile.get(key)):
            name = item.get("name") or item.get("title") or ""
            if name and is_verified_flag(item.get("verified")):
                _add_term_matches(evidence, str(name), f"profile.{key}", verified=True)


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
    # Schema rule: `clinical_experience.years` and `ngo_humanitarian_experience.years`
    # are single scalar fields that the profile owner types directly into
    # profile.yaml (profile_builder.py never fills them from a CV -- it always
    # leaves them blank). profile.yaml.example documents this convention
    # explicitly ("Add a number only when verified."), so a present numeric
    # value here is treated as owner-confirmed. This is intentionally
    # different from `work_history`, whose list entries CAN be bulk-pasted
    # from a CV and therefore require an explicit `verified: true` per entry
    # (see below) before they count as evidence.
    clinical = profile.get("clinical_experience", {})
    if isinstance(clinical, dict):
        years = clinical.get("years") or clinical.get("years_total")
        if years not in (None, "") and not is_unresolved_value(years):
            try:
                evidence.add("clinical_experience_years", float(years), "profile.clinical_experience", f"{years} years clinical experience", verified=True)
            except (TypeError, ValueError):
                pass
    elif isinstance(clinical, (int, float, str)) and str(clinical).strip() and not is_unresolved_value(clinical):
        try:
            evidence.add("clinical_experience_years", float(clinical), "profile.clinical_experience", f"{clinical} years clinical experience", verified=True)
        except ValueError:
            pass

    ngo = profile.get("ngo_humanitarian_experience", {})
    if isinstance(ngo, dict):
        years = ngo.get("years") or ngo.get("years_total")
        if years not in (None, "") and not is_unresolved_value(years):
            try:
                evidence.add("ngo_experience_years", float(years), "profile.ngo_humanitarian_experience", f"{years} years NGO/humanitarian experience", verified=True)
            except (TypeError, ValueError):
                pass
    elif isinstance(ngo, bool) and ngo:
        evidence.add("ngo_humanitarian", True, "profile.ngo_humanitarian_experience", "NGO/humanitarian experience marked in profile", verified=True)

    # Schema rule: a work_history entry only contributes to verified years-of-
    # experience evidence when that specific entry carries `verified: true`.
    # Merely having start/end dates (or being present in profile.yaml) is not
    # enough -- this mirrors the rule used for medical_education, license, and
    # medical_exit_exam, so there is one consistent standard across the whole
    # profile instead of education needing explicit verification while work
    # history does not.
    for key, kind in [
        ("clinical_experience_years", "clinical"),
        ("ngo_experience_years", "ngo"),
        ("management_experience_years", "management"),
        ("public_health_experience_years", "public_health"),
    ]:
        inferred = infer_years_from_history(profile, kind=kind, today=today)
        if inferred:
            evidence.add(key, inferred, "profile.work_history", f"{inferred} years inferred from explicitly verified work-history entries", verified=True)

    if resume_text:
        clinical_text_years = _extract_years_from_text(resume_text, ["clinical", "medical", "hospital", "clinic", "patient"])
        if clinical_text_years:
            evidence.add("clinical_experience_years", clinical_text_years, "cv", f"{clinical_text_years:g} years clinical experience mentioned in CV", verified=False)
        ngo_text_years = _extract_years_from_text(resume_text, ["ngo", "humanitarian", "emergency", "donor"])
        if ngo_text_years:
            evidence.add("ngo_experience_years", ngo_text_years, "cv", f"{ngo_text_years:g} years NGO/humanitarian experience mentioned in CV", verified=False)


def _add_personal(evidence: ProfileEvidence, profile: dict[str, Any]) -> None:
    # Personal/preference scalars live directly in profile.yaml, which the
    # profile_builder CV importer DOES populate for some fields (first_name,
    # last_name, email, phone are extracted straight from CV text; see
    # profile_builder.build_profile_from_cv_text). A CV-derived value is
    # therefore NOT automatically verified just because it is present and
    # non-placeholder -- per the canonical rule, identity/contact data is
    # subject to explicit verification: each field is confirmed on its own
    # under personal.verification.<field>.
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    for key in ["location", "nationality", "gender", "phone", "email", "first_name", "last_name", "linkedin"]:
        value = personal.get(key)
        if value and not is_unresolved_value(value):
            evidence.add(key, value, f"profile.personal.{key}", str(value), verified=personal_field_is_verified(profile, key))

    title_value = personal.get("professional_title")
    if title_value and not is_unresolved_value(title_value):
        evidence.add(
            "professional_title",
            title_value,
            "profile.personal.professional_title",
            str(title_value),
            verified=personal_field_is_verified(profile, "professional_title"),
        )
    prefs = profile.get("preferences", {}) if isinstance(profile.get("preferences"), dict) else {}
    for loc in prefs.get("locations", []) or []:
        if not is_unresolved_value(loc):
            evidence.add("preferred_location", loc, "profile.preferences.locations", str(loc), verified=True)
    for loc in prefs.get("preferred_locations", []) or []:
        if not is_unresolved_value(loc):
            evidence.add("preferred_location", loc, "profile.preferences.preferred_locations", str(loc), verified=True)
    # Canonical tri-state parsing: "Needs verification"/"Unknown"/etc. resolve
    # to None and are therefore never added as evidence (never silently
    # become True through truthiness). Only a recognised Yes/No token (or a
    # native boolean) is added.
    relocate = parse_tristate(prefs.get("willing_to_relocate"))
    if relocate is not None:
        evidence.add("willing_to_relocate", relocate, "profile.preferences.willing_to_relocate", str(prefs.get("willing_to_relocate")), verified=True)
    deployment = parse_tristate(prefs.get("field_deployment"))
    if deployment is not None:
        evidence.add("field_deployment", deployment, "profile.preferences.field_deployment", str(prefs.get("field_deployment")), verified=True)


def _add_skills_and_certificates(evidence: ProfileEvidence, profile: dict[str, Any]) -> None:
    """Record skills/certificates/training as ordinary (unverified) evidence.

    These are not currently consumed as pass/fail eligibility evidence by the
    matcher (see DIRECT_EVIDENCE_KEYS) -- they are only ever used as ordinary,
    self-reported resume content. Per the canonical verification contract,
    mere presence in profile.yaml does not verify a claim; an individual
    skill/certificate/training item can opt in to verified status only via an
    explicit ``{"name": ..., "verified": true}`` structure.
    """
    for key in ["skills", "certificates", "certifications", "training"]:
        value = profile.get(key)
        if not value:
            continue
        verified_items: list[str] = []
        for text in _iter_strings(value):
            if text:
                evidence.add(key, text, f"profile.{key}", text, verified=False)
        for item in _iter_dicts(value):
            name = item.get("name") or item.get("title") or ""
            if name and is_verified_flag(item.get("verified")):
                verified_items.append(str(name))
        for name in verified_items:
            evidence.add(key, name, f"profile.{key}", name, verified=True)


def build_profile_evidence(profile: dict[str, Any], resume_text: str = "", today: date | None = None) -> ProfileEvidence:
    """Build structured evidence without modifying the caller's profile object."""
    profile = deepcopy(profile)
    evidence = ProfileEvidence(raw_profile=profile)
    ptext = _profile_text(profile)
    texts = [("profile", ptext)]
    if resume_text:
        texts.append(("cv", normalize_text(resume_text)))

    _add_personal(evidence, profile)
    _add_structured_education(evidence, profile)
    _add_license(evidence, profile)
    _add_medical_exit_exam(evidence, profile)
    _add_skills_and_certificates(evidence, profile)
    _add_languages(evidence, profile, texts)
    _add_terms(evidence, texts)
    _add_verified_profile_terms(evidence, profile)
    _add_experience_years(evidence, profile, resume_text, today=today)

    # CV-only medical degree evidence.
    if resume_text and re.search(r"\b(M\.?D\.?|MBBS|Medical Doctor|Doctor of Medicine|Physician)\b", resume_text, flags=re.I):
        quote = _quote_for_alias(resume_text, ["MD", "MBBS", "Medical Doctor", "Doctor of Medicine", "Physician"])
        evidence.add("md_degree", True, "cv", quote or "Medical degree mentioned in CV", verified=False)

    if resume_text and re.search(r"\b(licen[cs]e|registration|registered)\b", resume_text, flags=re.I):
        quote = _quote_for_alias(resume_text, ["license", "licence", "registration", "registered"])
        evidence.add("license_registration", True, "cv", quote or "License/registration mentioned in CV", verified=False)

    return evidence
