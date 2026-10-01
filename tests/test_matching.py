from datetime import date

from utils.medical_matcher import NEEDS_VERIFICATION_STATUS, NOT_ELIGIBLE_STATUS, READY_TO_APPLY, match_job_against_profile


def base_profile(**updates):
    profile = {
        "personal": {"first_name": "Jane", "last_name": "Doe", "email": "doctor@example.org", "gender": "male", "nationality": "Afghan"},
        "medical_education": [{"degree": "MD", "verified": True}],
        "license_registration": {"status": "Valid medical professional registration/license", "verified": True},
        "medical_exit_exam": {"status": "Completed", "verified": True},
        "clinical_experience": {"years": 2},
        "preferences": {"locations": ["Kabul", "Afghanistan"]},
        "languages": [
            {"name": "Dari", "level": "Native", "verified": True},
            {"name": "Pashto", "level": "Fluent", "verified": True},
            {"name": "English", "level": "Professional", "verified": True},
        ],
    }
    profile.update(updates)
    return profile


def job(description, title="Medical Officer"):
    return {"id": "j", "title": title, "company": "FMIC", "location": "Kabul", "url": "https://example.org", "apply_url": "hr@example.org", "description": description, "metadata": {}}


def test_ready_to_apply_when_required_facts_are_verified():
    report = match_job_against_profile(
        job("Medical Degree required. Registered with Afghan Medical Council. 1 year clinical experience. English required. Apply by email hr@example.org before 2026-12-31."),
        base_profile(),
        today=date(2026, 10, 1),
    ).to_dict()

    assert report["readiness_status"] == READY_TO_APPLY
    assert report["counts"]["Met"] >= 4


def test_needs_verification_for_unverified_experience_years():
    profile = base_profile(clinical_experience={"years": ""})
    report = match_job_against_profile(job("Medical Doctor required. Minimum 3 years clinical experience. Apply to hr@example.org by 2026-12-31."), profile, today=date(2026, 10, 1)).to_dict()

    assert report["readiness_status"] == NEEDS_VERIFICATION_STATUS
    assert any(item["status"] == "Needs verification" for item in report["requirement_matches"])


def test_not_eligible_for_known_gender_restriction_mismatch():
    report = match_job_against_profile(job("Female Medical Doctor required. Apply to hr@example.org by 2026-12-31.", title="Female Medical Doctor"), base_profile(), today=date(2026, 10, 1)).to_dict()

    assert report["readiness_status"] == NOT_ELIGIBLE_STATUS
    assert any(item["key"] == "gender_requirement" and item["status"] == "Not met" for item in report["requirement_matches"])


def test_missing_application_route_is_visible_blocker():
    no_route = {"id": "j", "title": "Medical Doctor", "company": "Org", "location": "Kabul", "url": "", "apply_url": "", "description": "MD required. 1 year experience."}
    report = match_job_against_profile(no_route, base_profile(), today=date(2026, 10, 1)).to_dict()

    assert any(item["key"] == "application_destination" and item["status"] == "Needs verification" for item in report["requirement_matches"])
