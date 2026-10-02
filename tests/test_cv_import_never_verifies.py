"""Importing a CV must never produce verified facts by itself.

Uses a synthetic CV claiming an MD, license/registration, fluent English,
5 years experience, and certificates -- none of this may become
`verified: true` anywhere in the resulting profile.
"""

from utils.profile import build_profile_evidence
from utils.profile_builder import build_profile_from_cv_text

SYNTHETIC_CV = """
Jane Doe
Medical Doctor (MD)
Email: jane.doe@example.org
Phone: +93 70 000 0000
Kabul, Afghanistan

Education:
Doctor of Medicine (MD), Example Medical University, 2016

License:
Afghan Medical Council registration, valid medical license

Medical Exit Exam: Completed in 2017

Languages: English (fluent), Dari (native), Pashto (fluent)

Work Experience:
2018-2023 Medical Officer, Example Clinic, Kabul
- Provided clinical consultations for 5 years

Certificates: Basic Life Support, Advanced Cardiac Life Support
"""


def _walk_verified_flags(node, path=""):
    """Yield (path, value) for every `verified` key found anywhere in node."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            sub_path = f"{path}.{key}" if path else key
            if key == "verified":
                found.append((sub_path, value))
            found.extend(_walk_verified_flags(value, sub_path))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(_walk_verified_flags(item, f"{path}[{index}]"))
    return found


def test_cv_import_sets_profile_status_draft():
    profile = build_profile_from_cv_text(SYNTHETIC_CV, resume_path="cv.txt")
    assert str(profile.get("profile_status", "")).upper() == "DRAFT"
    assert profile.get("profile_status_note")


def test_cv_import_never_sets_any_verified_flag_true():
    profile = build_profile_from_cv_text(SYNTHETIC_CV, resume_path="cv.txt")
    verified_flags = _walk_verified_flags(profile)
    # There must be at least some verified fields present (schema demo), but
    # none may be True from a CV-only import.
    assert verified_flags, "expected verified fields in the generated schema"
    assert all(value is False for _, value in verified_flags), verified_flags


def test_cv_import_evidence_has_no_verified_medical_facts():
    profile = build_profile_from_cv_text(SYNTHETIC_CV, resume_path="cv.txt")
    evidence = build_profile_evidence(profile)
    for key in ["md_degree", "license_registration", "medical_exit_exam", "language_english", "clinical_experience_years"]:
        assert not evidence.has_verified(key), f"{key} must not be verified from CV import alone"


def test_cv_import_never_verifies_identity_or_contact_evidence():
    """Even though the synthetic CV has a real name, email, and phone number
    that profile_builder.py DOES extract into personal.first_name/last_name/
    email/phone, none of that may be represented as verified evidence --
    explicit confirmation by the profile owner is the only route.
    """
    profile = build_profile_from_cv_text(SYNTHETIC_CV, resume_path="cv.txt")
    assert profile["personal"]["email"]  # sanity: the extractor did find one
    assert profile["personal"]["verified"] is False
    evidence = build_profile_evidence(profile)
    for key in ["first_name", "last_name", "email", "phone"]:
        assert not evidence.has_verified(key), f"{key} must not be verified from CV import alone"


def test_cv_import_location_preference_is_not_silently_verified():
    """profile_builder.py must not manufacture a ready-made 'verified'
    location preference the user never typed."""
    profile = build_profile_from_cv_text(SYNTHETIC_CV, resume_path="cv.txt")
    evidence = build_profile_evidence(profile)
    assert not evidence.has_verified("preferred_location")


def test_cv_import_does_not_satisfy_matcher_requirements():
    from utils.medical_matcher import NOT_ELIGIBLE_STATUS, READY_TO_APPLY, match_job_against_profile

    profile = build_profile_from_cv_text(SYNTHETIC_CV, resume_path="cv.txt")
    job = {
        "id": "j",
        "title": "Medical Officer",
        "company": "Org",
        "location": "Kabul",
        "url": "https://example.org",
        "apply_url": "hr@example.org",
        "description": "Medical Degree required. Afghan Medical Council registration required. 3 years clinical experience required. Apply to hr@example.org by 2026-12-31.",
    }
    report = match_job_against_profile(job, profile).to_dict()
    assert report["readiness_status"] != READY_TO_APPLY
    assert report["readiness_status"] != NOT_ELIGIBLE_STATUS
