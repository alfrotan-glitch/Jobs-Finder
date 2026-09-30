"""
Deterministic MD-first eligibility matching.

The matcher compares extracted vacancy requirements with verified profile/CV
evidence.  It does not produce a single arbitrary score.  Every important
requirement is shown as Required/Preferred/Information → Met / Not met /
Needs verification, with evidence and provenance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from utils.medical_requirements import AFGHAN_PROVINCES, ExtractedRequirements, Requirement, extract_requirements_from_job, is_valid_application_url
from utils.profile import ProfileEvidence, build_profile_evidence


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
    resume_text: str = "",
    *,
    today: date | None = None,
) -> MatchReport:
    extracted = extract_requirements_from_job(job, today=today)
    evidence = build_profile_evidence(profile, resume_text=resume_text, today=today)
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
    if facts.get("application_url") or facts.get("application_email"):
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


def _direct_match(requirement: Requirement, evidence: ProfileEvidence, keys: list[str]) -> RequirementMatch:
    snippets: list[str] = []
    for key in keys:
        snippets.extend(evidence.evidence_text(key))
    if snippets:
        return RequirementMatch(
            key=requirement.key,
            label=requirement.label,
            required=requirement.required,
            status=MET,
            explanation="Profile/CV evidence supports this requirement.",
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
        explanation="No verified profile or CV evidence was found. This is not treated as absent; please verify it in My Profile.",
        evidence=[],
        required_evidence=requirement.evidence,
        value=requirement.value,
        criticality=requirement.criticality,
    )


def _years_match(requirement: Requirement, evidence: ProfileEvidence) -> RequirementMatch:
    required_years = float(requirement.value or 0)
    candidate_keys = [requirement.key]
    if requirement.key == "general_experience_years":
        candidate_keys.extend(["clinical_experience_years", "public_health_experience_years", "ngo_experience_years", "management_experience_years"])
    elif requirement.key == "afghanistan_health_experience_years":
        candidate_keys.extend(["public_health_experience_years", "clinical_experience_years"])

    known_values: list[float] = []
    snippets: list[str] = []
    for key in candidate_keys:
        for value in evidence.values(key):
            try:
                known_values.append(float(value))
            except (TypeError, ValueError):
                pass
        snippets.extend(evidence.evidence_text(key))

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

    best = max(known_values)
    if best >= required_years:
        return RequirementMatch(
            key=requirement.key,
            label=requirement.label,
            required=requirement.required,
            status=MET,
            explanation=f"Verified experience is {best:g} years, meeting the {required_years:g}-year requirement.",
            evidence=snippets[:4] or [f"{best:g} years in profile/CV"],
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
        evidence=snippets[:4] or [f"{best:g} years in profile/CV"],
        required_evidence=requirement.evidence,
        value=requirement.value,
        criticality=requirement.criticality,
    )


def _gender_match(requirement: Requirement, evidence: ProfileEvidence) -> RequirementMatch:
    required = str(requirement.value or "").lower()
    profile_gender = str(evidence.first("gender", "") or "").lower()
    if required.endswith("encouraged"):
        base = required.replace("_encouraged", "")
        matches = bool(profile_gender and base in profile_gender)
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
            evidence=evidence.evidence_text("gender"),
            required_evidence=requirement.evidence,
            value=requirement.value,
            criticality=requirement.criticality,
        )
    if not profile_gender:
        return _needs_verification(requirement, "The vacancy has a gender requirement, but gender is not verified in the profile.")
    if required in profile_gender:
        return _met(requirement, evidence.evidence_text("gender"), "Profile gender matches this requirement.")
    return _not_met(requirement, evidence.evidence_text("gender"), "Profile gender conflicts with this requirement.")


def _nationality_match(requirement: Requirement, evidence: ProfileEvidence) -> RequirementMatch:
    required = str(requirement.value or "").lower()
    nationality = str(evidence.first("nationality", "") or "").lower()
    if not nationality:
        return _needs_verification(requirement, "The vacancy has a nationality requirement, but nationality is not verified in the profile.")
    if required == "afghan" and ("afghan" in nationality or "afghanistan" in nationality):
        return _met(requirement, evidence.evidence_text("nationality"), "Profile nationality matches this requirement.")
    if required == "international" and "afghan" not in nationality:
        return _met(requirement, evidence.evidence_text("nationality"), "Profile nationality appears compatible with an international role.")
    return _not_met(requirement, evidence.evidence_text("nationality"), "Profile nationality appears to conflict with this requirement.")


def _residency_match(requirement: Requirement, evidence: ProfileEvidence) -> RequirementMatch:
    required = str(requirement.value or "").lower()
    locations = [str(v).lower() for v in evidence.values("location") + evidence.values("preferred_location")]
    if not locations:
        return _needs_verification(requirement, "The vacancy has a residency requirement, but current/preferred location is not verified.")
    if any(loc and loc in required or required in loc for loc in locations):
        return _met(requirement, evidence.evidence_text("location") + evidence.evidence_text("preferred_location"), "Profile location appears to match the residency requirement.")
    return _needs_verification(requirement, "Profile location does not clearly prove local residency. Please verify before applying.")


def _location_match(requirement: Requirement, evidence: ProfileEvidence) -> RequirementMatch:
    required_locations = [str(v).lower() for v in (requirement.value or [])]
    current = [str(v).lower() for v in evidence.values("location") + evidence.values("preferred_location")]
    field_ok = bool(evidence.first("field_deployment", False))
    relocation_ok = bool(evidence.first("willing_to_relocate", False))
    afghan_provinces = {p.lower() for p in AFGHAN_PROVINCES}
    required_is_afghan = any(req in afghan_provinces for req in required_locations)
    if not required_locations:
        return _met(requirement, [], "No specific location constraint was extracted.")
    if current and any(any(req in loc or loc in req for loc in current) for req in required_locations):
        return _met(requirement, evidence.evidence_text("location") + evidence.evidence_text("preferred_location"), "Profile location/preference matches the vacancy location.")
    if required_is_afghan and any("afghanistan" in loc for loc in current):
        return _met(requirement, evidence.evidence_text("location") + evidence.evidence_text("preferred_location"), "Profile lists Afghanistan as a location preference for Afghan vacancies.")
    if (any("field" in req or "district" in req for req in required_locations) or required_is_afghan) and field_ok:
        return _met(requirement, evidence.evidence_text("field_deployment"), "Profile indicates willingness for field/district deployment in Afghanistan.")
    if relocation_ok:
        return _met(requirement, evidence.evidence_text("willing_to_relocate"), "Profile indicates willingness to relocate/deploy.")
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
    email = facts.get("application_email")
    url = facts.get("application_url")
    if not email and isinstance(url, str) and url.lower().startswith("mailto:"):
        email = url.split(":", 1)[1].split("?", 1)[0].strip()
    if email:
        return RequirementMatch(
            key="application_destination",
            label="Application email / destination",
            required="Required",
            status=MET,
            explanation="An application email was found. Use the required subject if one is provided.",
            evidence=[email] + ([f"Subject: {facts.get('application_subject')}"] if facts.get("application_subject") else []),
            required_evidence=[],
            value=email,
            criticality="essential",
        )
    if is_valid_application_url(url):
        return RequirementMatch(
            key="application_destination",
            label="Application URL",
            required="Required",
            status=MET,
            explanation="A valid application URL was found and retained from the source.",
            evidence=[url],
            required_evidence=[],
            value=url,
            criticality="essential",
        )
    return RequirementMatch(
        key="application_destination",
        label="Application URL",
        required="Required",
        status=NOT_MET if url else NEEDS_VERIFICATION,
        explanation="The application URL is invalid or missing. Open the original source page and verify manually.",
        evidence=[str(url)] if url else [],
        required_evidence=[],
        value=url,
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
    if isinstance(report_or_matches, MatchReport):
        matches = report_or_matches.requirement_matches
    elif isinstance(report_or_matches, dict):
        matches = report_or_matches.get("requirement_matches", [])
    else:
        matches = report_or_matches

    required_items = []
    for item in matches:
        get = item.get if isinstance(item, dict) else lambda key, default=None: getattr(item, key, default)
        if get("required") == "Required" or get("criticality") == "essential":
            required_items.append(item)

    for item in required_items:
        get = item.get if isinstance(item, dict) else lambda key, default=None: getattr(item, key, default)
        if get("status") == NOT_MET:
            return NOT_ELIGIBLE_STATUS
    for item in required_items:
        get = item.get if isinstance(item, dict) else lambda key, default=None: getattr(item, key, default)
        if get("status") == NEEDS_VERIFICATION:
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


def important_requirement_table(report: MatchReport | dict[str, Any]) -> list[dict[str, Any]]:
    """Return the UI-friendly Required → Status table."""
    data = report.to_dict() if isinstance(report, MatchReport) else report
    return [
        {
            "required": item.get("label"),
            "level": item.get("required"),
            "status": item.get("status"),
            "explanation": item.get("explanation"),
            "evidence": item.get("evidence", []),
            "vacancy_evidence": item.get("required_evidence", []),
        }
        for item in data.get("requirement_matches", [])
    ]
