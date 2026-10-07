"""
Deterministic MD-first eligibility matching.

The matcher compares extracted vacancy requirements with verified canonical
profile evidence.  It does not produce a single arbitrary score.  Every important
requirement is shown as Required/Preferred/Information → Met / Not met /
Needs verification, with evidence and provenance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from utils.medical_requirements import (
    AFGHAN_PROVINCES,
    ExtractedRequirements,
    Requirement,
    extract_requirements_from_job,
    is_valid_application_url,
    is_valid_email,
)
from utils.profile import (
    ProfileEvidence,
    build_profile_evidence,
    require_runtime_profile,
)

MET = "Met"
NOT_MET = "Not met"
NEEDS_VERIFICATION = "Needs verification"

READY_TO_APPLY = "READY_TO_APPLY"
NEEDS_VERIFICATION_STATUS = "NEEDS_VERIFICATION"
NOT_ELIGIBLE_STATUS = "NOT_ELIGIBLE"


@dataclass
class RequirementMatch:
    key: str
    label: str
    required: str
    status: str
    explanation: str
    evidence: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    value: Any = True
    criticality: str = "important"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MatchReport:
    priority: str
    readiness_status: str
    recommendation: str
    explanation: str
    requirement_matches: list[RequirementMatch]
    extracted_requirements: dict[str, Any]
    profile_evidence: dict[str, Any]
    counts: dict[str, int]
    facts: dict[str, Any]
    provenance: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority": self.priority,
            "readiness_status": self.readiness_status,
            "recommendation": self.recommendation,
            "explanation": self.explanation,
            "requirement_matches": [m.to_dict() for m in self.requirement_matches],
            "extracted_requirements": self.extracted_requirements,
            "profile_evidence": self.profile_evidence,
            "counts": self.counts,
            "facts": self.facts,
            "provenance": self.provenance,
        }


# Requirements that can be answered by the same evidence key.
DIRECT_EVIDENCE_KEYS = {
    "md_degree": ["md_degree", "medical_education"],
    "license_registration": ["license_registration"],
    "license_number": ["license_number"],
    "license_document": ["license_document"],
    "medical_exit_exam": ["medical_exit_exam"],
    # Deliberately no evidence alias for a Medical Council Exam. A verified
    # Medical Exit Exam is not equivalent unless the vacancy explicitly uses
    # exit-exam wording, so a council-exam requirement remains review work.
    "medical_council_exam": [],
    "health_public_education": ["medical_education", "md_degree"],
    "medical_specialist": ["medical_specialist"],
    "specialist_obgyn": ["specialist_obgyn"],
    "pharmacy_degree": ["pharmacy_degree"],
    "nursing_midwifery_certificate": ["nursing_midwifery_certificate"],
    "pediatric_specialist": ["pediatric_specialist"],
    "afghanistan_experience": ["afghanistan_experience"],
    "bphs": ["bphs"],
    "ephs": ["ephs"],
    "phc": ["phc", "bphs", "ephs"],
    "hmis": ["hmis"],
    "imnci": ["imnci"],
    "imam": ["imam"],
    "nutrition": ["nutrition"],
    "srhr": ["srhr"],
    "ipc": ["ipc"],
    "ngo_humanitarian": ["ngo_humanitarian", "ngo_experience_years"],
    "reporting": ["reporting"],
    "supervision_management": ["supervision_management", "management_experience_years"],
    "moph_coordination": ["moph_coordination", "afghanistan_experience"],
    "safeguarding_psea": ["safeguarding_psea"],
    "quality_improvement": ["quality_improvement"],
    "emergency_response": ["emergency_response"],
    "supply_logistics": ["supply_logistics"],
    "language_english": ["language_english"],
    "language_dari": ["language_dari"],
    "language_pashto": ["language_pashto"],
}

HARD_CONSTRAINTS = {"gender_requirement", "nationality_requirement", "closing_date", "application_url"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def match_job_against_profile(
    job: Any,
    profile: dict[str, Any],
    *,
    today: date | None = None,
) -> MatchReport:
    """Match only a runtime applicant profile, never CV/import/cache text."""
    profile = require_runtime_profile(profile)
    extracted = extract_requirements_from_job(job, today=today)
    evidence = build_profile_evidence(profile, today=today)
    return match_extracted_requirements(extracted, evidence, today=today)


def match_extracted_requirements(
    extracted: ExtractedRequirements,
    profile_evidence: ProfileEvidence,
    *,
    today: date | None = None,
) -> MatchReport:
    today = today or date.today()
    matches: list[RequirementMatch] = []

    for requirement in extracted.requirements:
        matches.append(_match_requirement(requirement, profile_evidence, today=today))

    # Application URL/email are important operational requirements even if not in
    # the vacancy text's qualifications section.
    facts = dict(extracted.facts)
    if facts.get("application_url") or facts.get("application_email") or facts.get("official_route") or facts.get("application_method"):
        matches.append(_match_application_destination(facts))
        if facts.get("application_subject_required"):
            matches.append(_match_application_subject(facts))
    else:
        matches.append(
            RequirementMatch(
                key="application_destination",
                label="Application destination",
                required="Required",
                status=NEEDS_VERIFICATION,
                explanation="No application URL or email was found in the vacancy. Open the source page and verify where to apply.",
                evidence=[],
                required_evidence=[],
                value=None,
                criticality="essential",
            )
        )

    counts = {MET: 0, NOT_MET: 0, NEEDS_VERIFICATION: 0}
    for match in matches:
        counts[match.status] = counts.get(match.status, 0) + 1

    priority = _priority(matches, facts)
    recommendation = _recommendation(priority, matches, facts)
    explanation = _summary(priority, matches, facts)

    readiness = classify_application_readiness(matches)
    return MatchReport(
        priority=priority,
        readiness_status=readiness,
        recommendation=recommendation,
        explanation=f"{readiness}: {explanation}",
        requirement_matches=matches,
        extracted_requirements=extracted.to_dict(),
        profile_evidence=profile_evidence.to_dict(),
        counts=counts,
        facts=facts,
        provenance=extracted.provenance,
    )


# ---------------------------------------------------------------------------
# Requirement-specific matching
# ---------------------------------------------------------------------------


def _match_requirement(requirement: Requirement, evidence: ProfileEvidence, *, today: date) -> RequirementMatch:
    key = requirement.key
    if key == "source_validity":
        return _source_validity_match(requirement)
    if key == "role_family_compatibility":
        return _role_family_match(requirement, evidence)
    if key in DIRECT_EVIDENCE_KEYS:
        return _direct_match(requirement, evidence, DIRECT_EVIDENCE_KEYS[key])
    if key.endswith("_experience_years") or key == "general_experience_years":
        return _years_match(requirement, evidence)
    if key == "gender_requirement":
        return _gender_match(requirement, evidence)
    if key == "nationality_requirement":
        return _nationality_match(requirement, evidence)
    if key == "residency_requirement":
        return _residency_match(requirement, evidence)
    if key == "location_requirement":
        return _location_match(requirement, evidence)
    if key == "closing_date":
        return _closing_date_match(requirement, today=today)
    return RequirementMatch(
        key=key,
        label=requirement.label,
        required=requirement.required,
        status=NEEDS_VERIFICATION,
        explanation="This requirement was found in the vacancy, but no deterministic profile rule exists yet. Please review it manually.",
        evidence=[],
        required_evidence=requirement.evidence,
        value=requirement.value,
        criticality=requirement.criticality,
    )


def _source_validity_match(requirement: Requirement) -> RequirementMatch:
    value = requirement.value if isinstance(requirement.value, dict) else {}
    problems = value.get("problems") or []
    evidence = [item for item in requirement.evidence if item]
    if value.get("source_valid") and value.get("is_actionable"):
        return _met(requirement, evidence, "The vacancy has a named source, valid source URL, official vacancy/application route, employer, and title.")
    explicit_unknown = str(value.get("source_name") or "").strip().upper() == "UNKNOWN"
    status = NOT_MET if explicit_unknown or "malformed_application_route" in problems else NEEDS_VERIFICATION
    explanation = "Source/application metadata is incomplete or invalid; this vacancy must not be treated as an actionable job until the official source and route are verified."
    return RequirementMatch(
        key=requirement.key,
        label=requirement.label,
        required=requirement.required,
        status=status,
        explanation=explanation + (f" Problems: {', '.join(problems)}." if problems else ""),
        evidence=evidence,
        required_evidence=requirement.evidence,
        value=requirement.value,
        criticality=requirement.criticality,
    )


def _role_family_match(requirement: Requirement, evidence: ProfileEvidence) -> RequirementMatch:
    value = requirement.value if isinstance(requirement.value, dict) else {}
    classification = str(value.get("classification") or "")
    snippets = [str(value.get("evidence") or "").strip()] if value.get("evidence") else []
    if classification == "incompatible_professional_role":
        return _not_met(
            requirement,
            snippets,
            value.get("explanation") or "This role requires a different professional license/qualification and does not state that MD/physician credentials are accepted.",
        )
    if classification == "specialist_qualification_required":
        specialist_keys = value.get("specialist_evidence_keys")
        keys = [str(key) for key in specialist_keys] if isinstance(specialist_keys, list) else []
        specialist_evidence: list[str] = []
        for key in keys:
            specialist_evidence.extend(evidence.evidence_text(key, verified_only=True))
        if specialist_evidence:
            return _met(requirement, specialist_evidence[:3], "Verified canonical-profile evidence supports the specialist qualification required for this role.")
        return _needs_verification(
            requirement,
            "The title requires a specialist credential. A verified general MD is not treated as equivalent; verify the actual specialty qualification before applying.",
        )
    if classification == "md_physician_role":
        if evidence.has_verified("md_degree"):
            return _met(requirement, evidence.evidence_text("md_degree", verified_only=True)[:3] or snippets, "Verified profile evidence supports the MD/medical-doctor qualification required or accepted for this role.")
        return _needs_verification(requirement, "The role accepts/requires an MD/physician qualification, but the MD degree is not verified in the profile.")
    if classification == "health_public_health_compatible":
        compatible_keys = [
            "md_degree",
            "clinical_experience_years",
            "public_health_experience_years",
            "ngo_experience_years",
            "management_experience_years",
            "hmis",
            "nutrition",
            "imam",
            "supervision_management",
        ]
        matched_evidence: list[str] = []
        for key in compatible_keys:
            matched_evidence.extend(evidence.evidence_text(key, verified_only=True))
        if matched_evidence or evidence.has_verified("md_degree"):
            return _met(requirement, matched_evidence[:4] or evidence.evidence_text("md_degree", verified_only=True)[:3] or snippets, "The role family is compatible with verified medical/public-health/health-nutrition evidence in the profile.")
        return _needs_verification(requirement, "The role appears health/public-health/nutrition compatible, but matching experience/qualification evidence is not yet verified in the profile.")
    if classification == "ambiguous_health_words":
        return _needs_verification(requirement, value.get("explanation") or "Health/medical/nutrition words alone are insufficient; verify actual role, qualification, credential, and duties before treating this as a match.")
    return _not_met(requirement, snippets, value.get("explanation") or "The actual role family does not appear compatible with an MD/public-health profile.")


def _direct_match(requirement: Requirement, evidence: ProfileEvidence, keys: list[str]) -> RequirementMatch:
    snippets: list[str] = []
    for key in keys:
        snippets.extend(evidence.evidence_text(key, verified_only=True))
    if snippets:
        return RequirementMatch(
            key=requirement.key,
            label=requirement.label,
            required=requirement.required,
            status=MET,
            explanation="Verified canonical-profile evidence supports this requirement.",
            evidence=snippets[:4],
            required_evidence=requirement.evidence,
            value=requirement.value,
            criticality=requirement.criticality,
        )
    return RequirementMatch(
        key=requirement.key,
        label=requirement.label,
        required=requirement.required,
        status=NEEDS_VERIFICATION,
        explanation="No verified canonical-profile evidence was found. This is not treated as absent; please verify it in My Profile.",
        evidence=[],
        required_evidence=requirement.evidence,
        value=requirement.value,
        criticality=requirement.criticality,
    )


def _years_match(requirement: Requirement, evidence: ProfileEvidence) -> RequirementMatch:
    """Compare experience without converting a lower bound into an exact total.

    A verified ``> 3``/``3+`` claim proves a three-year requirement, but not a
    five-year requirement. In the latter case the applicant may in fact have
    five years; the canonical profile simply does not prove it, so the only
    honest status is ``Needs verification`` rather than ``Not met``.
    """
    required_years = float(requirement.value or 0)
    candidate_keys = [requirement.key]
    if requirement.key == "general_experience_years":
        candidate_keys.extend([
            "clinical_experience_years", "health_nutrition_experience_years",
            "frontline_experience_years", "public_health_experience_years",
            "ngo_experience_years", "management_experience_years",
        ])
    elif requirement.key == "afghanistan_health_experience_years":
        candidate_keys.extend(["public_health_experience_years", "clinical_experience_years"])

    known_values: list[tuple[float, bool]] = []
    snippets: list[str] = []
    for key in candidate_keys:
        for item in evidence.items.get(key, []):
            if not item.verified:
                continue
            try:
                known_values.append((float(item.value), item.lower_bound))
            except (TypeError, ValueError):
                continue
            if item.quote:
                snippets.append(item.quote)

    if not known_values:
        return RequirementMatch(
            key=requirement.key,
            label=requirement.label,
            required=requirement.required,
            status=NEEDS_VERIFICATION,
            explanation=f"The vacancy asks for at least {required_years:g} years, but the verified profile does not contain a comparable years value.",
            evidence=[],
            required_evidence=requirement.evidence,
            value=requirement.value,
            criticality=requirement.criticality,
        )

    best = max(value for value, _ in known_values)
    if any(value >= required_years for value, _ in known_values):
        matching_lower_bounds = [value for value, lower_bound in known_values if lower_bound and value >= required_years]
        wording = (
            f"A verified lower-bound claim establishes at least {max(matching_lower_bounds):g} years, meeting the {required_years:g}-year requirement."
            if matching_lower_bounds
            else f"Verified experience is {best:g} years, meeting the {required_years:g}-year requirement."
        )
        return RequirementMatch(
            key=requirement.key,
            label=requirement.label,
            required=requirement.required,
            status=MET,
            explanation=wording,
            evidence=snippets[:4] or [f"{best:g} years in canonical profile"],
            required_evidence=requirement.evidence,
            value=requirement.value,
            criticality=requirement.criticality,
        )

    if any(lower_bound for _, lower_bound in known_values):
        return RequirementMatch(
            key=requirement.key,
            label=requirement.label,
            required=requirement.required,
            status=NEEDS_VERIFICATION,
            explanation=(
                f"Verified profile evidence establishes at least {best:g} years, but it is a lower-bound claim "
                f"and cannot prove the {required_years:g}-year requirement. Confirm the exact duration before applying."
            ),
            evidence=snippets[:4] or [f"more than {best:g} years in canonical profile"],
            required_evidence=requirement.evidence,
            value=requirement.value,
            criticality=requirement.criticality,
        )

    return RequirementMatch(
        key=requirement.key,
        label=requirement.label,
        required=requirement.required,
        status=NOT_MET,
        explanation=f"Verified experience is {best:g} years, below the {required_years:g}-year requirement.",
        evidence=snippets[:4] or [f"{best:g} years in canonical profile"],
        required_evidence=requirement.evidence,
        value=requirement.value,
        criticality=requirement.criticality,
    )


def _gender_match(requirement: Requirement, evidence: ProfileEvidence) -> RequirementMatch:
    # Only genuinely verified gender evidence may satisfy or conflict with a
    # gender requirement -- an unverified (e.g. CV-derived or unconfirmed)
    # value must never produce a MET or NOT_MET (exclusion) decision.
    required = str(requirement.value or "").lower()
    verified_genders = [str(v).lower() for v in evidence.verified_values("gender")]
    profile_gender = verified_genders[0] if verified_genders else ""
    profile_gender_norm = "female" if profile_gender in {"female", "woman", "women", "f"} else "male" if profile_gender in {"male", "man", "men", "m"} else profile_gender
    if required.endswith("encouraged"):
        base = required.replace("_encouraged", "")
        matches = bool(profile_gender_norm and base == profile_gender_norm)
        return RequirementMatch(
            key=requirement.key,
            label=requirement.label,
            required=requirement.required,
            status=MET,
            explanation=(
                "Profile gender evidence matches this preference."
                if matches
                else "This appears to be a preference or encouragement, not a hard eligibility requirement."
            ),
            evidence=evidence.evidence_text("gender", verified_only=True),
            required_evidence=requirement.evidence,
            value=requirement.value,
            criticality=requirement.criticality,
        )
    if not profile_gender:
        return _needs_verification(requirement, "The vacancy has a gender requirement, but gender is not verified in the profile.")
    if required == profile_gender_norm:
        return _met(requirement, evidence.evidence_text("gender", verified_only=True), "Profile gender matches this requirement.")
    return _not_met(requirement, evidence.evidence_text("gender", verified_only=True), "Profile gender conflicts with this requirement.")


def _nationality_match(requirement: Requirement, evidence: ProfileEvidence) -> RequirementMatch:
    required = str(requirement.value or "").lower()
    verified_nationalities = [str(v).lower() for v in evidence.verified_values("nationality")]
    nationality = verified_nationalities[0] if verified_nationalities else ""
    if not nationality:
        return _needs_verification(requirement, "The vacancy has a nationality requirement, but nationality is not verified in the profile.")
    if required == "afghan" and ("afghan" in nationality or "afghanistan" in nationality):
        return _met(requirement, evidence.evidence_text("nationality", verified_only=True), "Profile nationality matches this requirement.")
    if required == "international" and "afghan" not in nationality:
        return _met(requirement, evidence.evidence_text("nationality", verified_only=True), "Profile nationality appears compatible with an international role.")
    return _not_met(requirement, evidence.evidence_text("nationality", verified_only=True), "Profile nationality appears to conflict with this requirement.")


def _residency_match(requirement: Requirement, evidence: ProfileEvidence) -> RequirementMatch:
    required = str(requirement.value or "").lower()
    locations = [str(v).lower() for v in evidence.verified_values("location") + evidence.verified_values("preferred_location")]
    if not locations:
        return _needs_verification(requirement, "The vacancy has a residency requirement, but current/preferred location is not verified.")
    if any(loc and loc in required or required in loc for loc in locations):
        return _met(requirement, evidence.evidence_text("location", verified_only=True) + evidence.evidence_text("preferred_location", verified_only=True), "Profile location appears to match the residency requirement.")
    return _needs_verification(requirement, "Profile location does not clearly prove local residency. Please verify before applying.")


def _location_match(requirement: Requirement, evidence: ProfileEvidence) -> RequirementMatch:
    required_locations = [str(v).lower() for v in (requirement.value or [])]
    current = [str(v).lower() for v in evidence.verified_values("location") + evidence.verified_values("preferred_location")]
    # Strict semantics: only an explicitly verified literal True answer may
    # satisfy a deployment/relocation constraint. Never truthiness, never the
    # first (possibly unverified) recorded value.
    field_ok = any(value is True for value in evidence.verified_values("field_deployment"))
    relocation_ok = any(value is True for value in evidence.verified_values("willing_to_relocate"))
    afghan_provinces = {p.lower() for p in AFGHAN_PROVINCES}
    required_is_afghan = any(req in afghan_provinces for req in required_locations)
    if not required_locations:
        return _met(requirement, [], "No specific location constraint was extracted.")
    if current and any(any(req in loc or loc in req for loc in current) for req in required_locations):
        return _met(requirement, evidence.evidence_text("location", verified_only=True) + evidence.evidence_text("preferred_location", verified_only=True), "Profile location/preference matches the vacancy location.")
    if required_is_afghan and any("afghanistan" in loc for loc in current):
        return _met(requirement, evidence.evidence_text("location", verified_only=True) + evidence.evidence_text("preferred_location", verified_only=True), "Profile lists Afghanistan as a location preference for Afghan vacancies.")
    if (any("field" in req or "district" in req for req in required_locations) or required_is_afghan) and field_ok:
        return _met(requirement, evidence.evidence_text("field_deployment", verified_only=True), "Profile indicates willingness for field/district deployment in Afghanistan.")
    if relocation_ok:
        return _met(requirement, evidence.evidence_text("willing_to_relocate", verified_only=True), "Profile indicates willingness to relocate/deploy.")
    if current:
        return _needs_verification(requirement, "The vacancy location is not listed in profile preferences. Verify willingness and feasibility before applying.")
    return _needs_verification(requirement, "No verified location preference is available.")


def _closing_date_match(requirement: Requirement, *, today: date) -> RequirementMatch:
    value = str(requirement.value or "")
    try:
        closing = date.fromisoformat(value)
    except ValueError:
        return _needs_verification(requirement, "Closing date could not be parsed reliably.")
    if closing < today:
        return _not_met(requirement, [value], f"The closing date {value} has passed.")
    return _met(requirement, [value], f"The vacancy appears open until {value}.")


def _match_application_subject(facts: dict[str, Any]) -> RequirementMatch:
    subject = facts.get("application_subject")
    if subject:
        return RequirementMatch(
            key="application_subject",
            label="Required application subject",
            required="Required",
            status=MET,
            explanation="A required email subject/reference was found or can be deterministically formed from the job title instruction.",
            evidence=[str(subject)],
            required_evidence=[],
            value=subject,
            criticality="essential",
        )
    return RequirementMatch(
        key="application_subject",
        label="Required application subject",
        required="Required",
        status=NEEDS_VERIFICATION,
        explanation="The vacancy requires a subject/reference, but no exact subject or vacancy number was found. Verify before applying.",
        evidence=[],
        required_evidence=[],
        value=None,
        criticality="essential",
    )


def _match_application_destination(facts: dict[str, Any]) -> RequirementMatch:
    email = facts.get("apply_email") or facts.get("application_email")
    url = facts.get("apply_url") or facts.get("application_url")
    method = str(facts.get("application_method") or "").upper()
    official_route = facts.get("official_route") or facts.get("vacancy_url") or facts.get("source_url")
    if not email and isinstance(url, str) and url.lower().startswith("mailto:"):
        email = url.split(":", 1)[1].split("?", 1)[0].strip()
    email_text = str(email or "").strip()
    if email_text and is_valid_email(email_text):
        return RequirementMatch(
            key="application_destination",
            label="Application email / destination",
            required="Required",
            status=MET,
            explanation="A direct application email was found in the official vacancy/source data. Use the required subject if one is provided.",
            evidence=[email_text] + ([f"Subject: {facts.get('application_subject')}"] if facts.get("application_subject") else []),
            required_evidence=[],
            value=email_text,
            criticality="essential",
        )
    url_text = str(url or "").strip()
    if is_valid_application_url(url_text):
        return RequirementMatch(
            key="application_destination",
            label="Application URL",
            required="Required",
            status=MET,
            explanation="A valid direct application URL/form was found and retained from the source.",
            evidence=[url_text],
            required_evidence=[],
            value=url_text,
            criticality="essential",
        )
    if method == "UNAVAILABLE" and official_route:
        return RequirementMatch(
            key="application_destination",
            label="Official vacancy page / application route verification",
            required="Required",
            status=NEEDS_VERIFICATION,
            explanation="Only the official vacancy page is available; no direct application email/form was deterministically extracted. Open the official page and verify the application route before applying.",
            evidence=[str(official_route)],
            required_evidence=[],
            value=official_route,
            criticality="essential",
        )
    invalid_route = facts.get("apply_url") or url
    return RequirementMatch(
        key="application_destination",
        label="Application route",
        required="Required",
        status=NOT_MET if invalid_route else NEEDS_VERIFICATION,
        explanation="No reliable application URL/email was found. This vacancy is not ready to apply until the official route is verified.",
        evidence=[str(invalid_route)] if invalid_route else [],
        required_evidence=[],
        value=invalid_route,
        criticality="essential",
    )


# ---------------------------------------------------------------------------
# Small constructors
# ---------------------------------------------------------------------------


def _met(requirement: Requirement, snippets: list[str], explanation: str) -> RequirementMatch:
    return RequirementMatch(
        key=requirement.key,
        label=requirement.label,
        required=requirement.required,
        status=MET,
        explanation=explanation,
        evidence=snippets[:4],
        required_evidence=requirement.evidence,
        value=requirement.value,
        criticality=requirement.criticality,
    )


def _not_met(requirement: Requirement, snippets: list[str], explanation: str) -> RequirementMatch:
    return RequirementMatch(
        key=requirement.key,
        label=requirement.label,
        required=requirement.required,
        status=NOT_MET,
        explanation=explanation,
        evidence=snippets[:4],
        required_evidence=requirement.evidence,
        value=requirement.value,
        criticality=requirement.criticality,
    )


def _needs_verification(requirement: Requirement, explanation: str) -> RequirementMatch:
    return RequirementMatch(
        key=requirement.key,
        label=requirement.label,
        required=requirement.required,
        status=NEEDS_VERIFICATION,
        explanation=explanation,
        evidence=[],
        required_evidence=requirement.evidence,
        value=requirement.value,
        criticality=requirement.criticality,
    )


# ---------------------------------------------------------------------------
# Strict application readiness
# ---------------------------------------------------------------------------


def classify_application_readiness(report_or_matches: MatchReport | dict[str, Any] | list[RequirementMatch] | list[dict[str, Any]]) -> str:
    """Classify strict readiness for applying.

    READY_TO_APPLY is returned only when every mandatory/required requirement is
    Met.  A missing mandatory fact is NEEDS_VERIFICATION, not ready.  A proven
    conflict, insufficient years, or passed closing date is NOT_ELIGIBLE.
    Preferred/informational open items do not block readiness.
    """
    raw_matches: Any
    if isinstance(report_or_matches, MatchReport):
        raw_matches = report_or_matches.requirement_matches
    elif isinstance(report_or_matches, dict):
        raw_matches = report_or_matches.get("requirement_matches", [])
    else:
        raw_matches = report_or_matches
    matches: list[Any] = raw_matches if isinstance(raw_matches, list) else []

    def field(item: Any, key: str, default: Any = None) -> Any:
        return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)

    required_items = []
    for item in matches:
        if field(item, "required") == "Required" or field(item, "criticality") == "essential":
            required_items.append(item)

    for item in required_items:
        if field(item, "status") == NOT_MET:
            return NOT_ELIGIBLE_STATUS
    for item in required_items:
        if field(item, "status") == NEEDS_VERIFICATION:
            return NEEDS_VERIFICATION_STATUS
    return READY_TO_APPLY


# ---------------------------------------------------------------------------
# Priority/recommendation (not a hiring probability)
# ---------------------------------------------------------------------------


def _priority(matches: list[RequirementMatch], facts: dict[str, Any]) -> str:
    essential_not_met = [m for m in matches if m.status == NOT_MET and m.criticality == "essential"]
    required_not_met = [m for m in matches if m.status == NOT_MET and m.required == "Required"]
    closed = any(m.key == "closing_date" and m.status == NOT_MET for m in matches)
    if closed:
        return "Closed"
    if essential_not_met or required_not_met:
        return "Low priority"
    essential_needs = [m for m in matches if m.status == NEEDS_VERIFICATION and m.criticality == "essential"]
    needs = [m for m in matches if m.status == NEEDS_VERIFICATION]
    if essential_needs:
        return "Needs verification"
    if needs:
        return "Review soon"
    if not facts.get("is_medical"):
        return "Low priority"
    return "Review first"


def _recommendation(priority: str, matches: list[RequirementMatch], facts: dict[str, Any]) -> str:
    if priority == "Closed":
        return "Do not apply unless the closing date is wrong on the source page."
    if priority == "Low priority":
        return "Review only if you have a strong reason; at least one important verified requirement does not match."
    if priority == "Needs verification":
        return "Verify the missing evidence in My Profile before preparing the application."
    if priority == "Review soon":
        return "Worth reviewing today, but verify the open items before applying."
    return "Look at this today and prepare the application for review."


def _summary(priority: str, matches: list[RequirementMatch], facts: dict[str, Any]) -> str:
    met = sum(1 for m in matches if m.status == MET)
    needs = sum(1 for m in matches if m.status == NEEDS_VERIFICATION)
    not_met = sum(1 for m in matches if m.status == NOT_MET)
    medical_note = "medical vacancy" if facts.get("is_medical") else "not clearly a medical vacancy"
    return f"{priority}: {met} met, {needs} need verification, {not_met} not met; source appears to be a {medical_note}."
