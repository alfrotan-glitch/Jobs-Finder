"""Regression tests for strict matcher semantics.

Every weakness covered here was either found in this audit or is a trap the
canonical contract explicitly forbids: Python truthiness standing in for
semantic verification, unverified evidence producing MET/NOT_MET, and
string/number look-alike booleans ("true", "no", 1, 0, placeholders).
"""

from datetime import date

from utils.medical_matcher import (
    MET,
    NEEDS_VERIFICATION,
    NEEDS_VERIFICATION_STATUS,
    _location_match,
    match_job_against_profile,
)
from utils.medical_requirements import Requirement
from utils.profile import ProfileEvidence, build_profile_evidence


def _location_requirement(locations):
    return Requirement(key="location_requirement", label="Duty station", required="Required", value=locations)


def test_unverified_field_deployment_evidence_cannot_satisfy_location():
    evidence = ProfileEvidence()
    # Unverified claim (e.g. CV text mention) -- must never produce MET.
    evidence.add("field_deployment", True, "cv", "available for field deployment", verified=False)
    match = _location_match(_location_requirement(["badghis districts field"]), evidence)
    assert match.status == NEEDS_VERIFICATION


def test_unverified_relocation_evidence_cannot_satisfy_location():
    evidence = ProfileEvidence()
    evidence.add("willing_to_relocate", True, "cv", "willing to relocate", verified=False)
    match = _location_match(_location_requirement(["herat"]), evidence)
    assert match.status == NEEDS_VERIFICATION


def test_verified_false_deployment_answer_cannot_satisfy_location():
    # A verified answer of "No" is resolved evidence, but it must not be
    # coerced into a positive deployment claim by truthiness anywhere.
    evidence = ProfileEvidence()
    evidence.add("field_deployment", False, "profile.preferences.field_deployment", "No", verified=True)
    match = _location_match(_location_requirement(["badghis districts field"]), evidence)
    assert match.status == NEEDS_VERIFICATION


def test_verified_true_deployment_answer_satisfies_afghan_field_location():
    evidence = ProfileEvidence()
    evidence.add("field_deployment", True, "profile.preferences.field_deployment", "Yes", verified=True)
    match = _location_match(_location_requirement(["badghis districts field"]), evidence)
    assert match.status == MET


def test_string_boolean_preferences_never_resolve_semantically():
    """"true"/"false"/"1"/"0" are not recognised yes/no answers; they must
    remain unresolved instead of being truthiness-coerced either way."""
    for raw in ["Needs verification", "1", "0", "maybe", "TRUE()", "none"]:
        profile = {"preferences": {"willing_to_relocate": raw, "field_deployment": raw}}
        evidence = build_profile_evidence(profile)
        assert not evidence.has("willing_to_relocate"), raw
        assert not evidence.has("field_deployment"), raw
    # Literal yes/no token strings DO resolve (that is their documented meaning).
    evidence = build_profile_evidence({"preferences": {"willing_to_relocate": "true", "field_deployment": "false"}})
    assert evidence.verified_values("willing_to_relocate") == [True]
    assert evidence.verified_values("field_deployment") == [False]


def test_license_copy_available_no_is_not_an_available_document():
    profile = {
        "license_registration": {
            "status": "Valid medical professional registration/license",
            "verified": True,
            "copy_available": "no",
        }
    }
    evidence = build_profile_evidence(profile)
    assert not evidence.has("license_document")


def test_license_copy_available_placeholder_is_not_an_available_document():
    profile = {
        "license_registration": {
            "status": "Valid medical professional registration/license",
            "verified": True,
            "copy_available": "Needs verification",
        }
    }
    evidence = build_profile_evidence(profile)
    assert not evidence.has("license_document")


def test_license_copy_available_yes_with_verification_counts():
    profile = {
        "license_registration": {
            "status": "Valid medical professional registration/license",
            "verified": True,
            "copy_available": "yes",
        }
    }
    evidence = build_profile_evidence(profile)
    assert evidence.has_verified("license_document")


def test_experience_years_from_unverified_cv_text_never_meet_requirements():
    profile = {
        "personal": {"first_name": "Jane", "last_name": "Doe", "email": "doctor@example.org", "verified": True},
        "medical_education": [{"degree": "MD", "verified": True}],
        "license_registration": {"status": "Valid", "verified": True},
    }
    report = match_job_against_profile(
        {
            "id": "j",
            "title": "Medical Officer",
            "company": "Org",
            "location": "Kabul",
            "url": "https://example.org",
            "apply_url": "hr@example.org",
            "description": "MD required. 3 years clinical experience required. Apply to hr@example.org by 2026-12-31.",
        },
        profile,
        resume_text="Experienced physician with 10 years of clinical experience in hospitals.",
        today=date(2026, 10, 1),
    ).to_dict()
    assert report["readiness_status"] == NEEDS_VERIFICATION_STATUS
    years_item = next(item for item in report["requirement_matches"] if item["key"].endswith("experience_years"))
    assert years_item["status"] == "Needs verification"
