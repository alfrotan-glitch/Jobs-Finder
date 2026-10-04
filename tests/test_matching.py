from datetime import date

from utils.medical_matcher import (
    NEEDS_VERIFICATION_STATUS,
    NOT_ELIGIBLE_STATUS,
    READY_TO_APPLY,
    match_job_against_profile,
)
from utils.profile import build_profile_evidence


def base_profile(**updates):
    profile = {
        "personal": {"first_name": "Jane", "last_name": "Doe", "email": "doctor@example.org", "gender": "male", "nationality": "Afghan", "verification": {"first_name": True, "last_name": True, "email": True, "phone": True, "location": True, "nationality": True, "gender": True, "professional_title": True}},
        "medical_education": [{"degree": "MD", "verified": True}],
        "license_registration": {"status": "Valid medical professional registration/license", "verified": True},
        "medical_exit_exam": {"status": "Completed", "verified": True},
        "clinical_experience": {"years": 2, "verified": True},
        "preferences": {"locations": [{"name": "Kabul", "verified": True}, {"name": "Afghanistan", "verified": True}]},
        "languages": [
            {"name": "Dari", "level": "Native", "verified": True},
            {"name": "Pashto", "level": "Fluent", "verified": True},
            {"name": "English", "level": "Professional", "verified": True},
        ],
    }
    profile.update(updates)
    return profile


def job(description, title="Medical Officer", apply_url="hr@example.org", source_name="ACBAR"):
    return {
        "id": "j",
        "title": title,
        "company": "FMIC",
        "location": "Kabul",
        "url": "https://example.org/jobs/j",
        "apply_url": apply_url,
        "description": description,
        "metadata": {
            "source_name": source_name,
            "source_url": "https://example.org/jobs",
            "vacancy_url": "https://example.org/jobs/j",
            "application_method": "email" if "@" in str(apply_url) else "online_form" if apply_url else "none",
        },
    }


def test_ready_to_apply_when_required_facts_are_verified():
    report = match_job_against_profile(
        job("Medical Degree required. Registered with Afghan Medical Council. 1 year clinical experience. English required. Apply by email hr@example.org before 2026-12-31."),
        base_profile(),
        today=date(2026, 10, 1),
    ).to_dict()

    assert report["readiness_status"] == READY_TO_APPLY
    assert report["counts"]["Met"] >= 4


def test_needs_verification_for_unverified_experience_years():
    profile = base_profile(clinical_experience={"years": "", "verified": False})
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


def test_unverified_gender_claim_needs_verification_not_silently_excluded():
    """An unconfirmed gender value (e.g. fresh from a CV import) must never
    be used to decide a gender-restricted requirement either way -- it must
    stay NEEDS_VERIFICATION, never NOT_MET or MET.
    """
    profile = base_profile(personal={"first_name": "Jane", "last_name": "Doe", "email": "doctor@example.org", "gender": "male", "nationality": "Afghan"})
    report = match_job_against_profile(
        job("Female Medical Doctor required. Apply to hr@example.org by 2026-12-31.", title="Female Medical Doctor"),
        profile,
        today=date(2026, 10, 1),
    ).to_dict()

    assert report["readiness_status"] == NEEDS_VERIFICATION_STATUS
    gender_item = next(item for item in report["requirement_matches"] if item["key"] == "gender_requirement")
    assert gender_item["status"] == "Needs verification"


def test_verified_gender_mismatch_is_not_eligible():
    report = match_job_against_profile(
        job("Female Medical Doctor required. Apply to hr@example.org by 2026-12-31.", title="Female Medical Doctor"),
        base_profile(),
        today=date(2026, 10, 1),
    ).to_dict()

    assert report["readiness_status"] == NOT_ELIGIBLE_STATUS
    gender_item = next(item for item in report["requirement_matches"] if item["key"] == "gender_requirement")
    assert gender_item["status"] == "Not met"


def test_gender_is_never_inferred_from_name_title_or_pronouns():
    """Only personal.verification.gender makes gender evidence.

    A feminine first name, a gendered job title, and pronouns in the vacancy
    text must never produce profile gender evidence, so a female-only
    vacancy stays NEEDS_VERIFICATION instead of being decided either way.
    """
    profile = base_profile(personal={
        "first_name": "Fatima",
        "last_name": "Ahmadi",
        "email": "doctor@example.org",
        "professional_title": "Lady Medical Doctor",
        "nationality": "Afghan",
        "verification": {"first_name": True, "last_name": True, "email": True, "professional_title": True, "nationality": True},
    })
    evidence = build_profile_evidence(profile)
    assert not evidence.has("gender")
    assert not evidence.has_verified("gender")

    report = match_job_against_profile(
        job("She will lead the clinic. Only qualified female candidates will be considered. "
            "Apply to hr@example.org by 2026-12-31.", title="Female Medical Doctor"),
        profile,
        today=date(2026, 10, 1),
    ).to_dict()
    assert report["readiness_status"] == NEEDS_VERIFICATION_STATUS
    gender_item = next(item for item in report["requirement_matches"] if item["key"] == "gender_requirement")
    assert gender_item["status"] == "Needs verification"


def test_unverified_nationality_claim_needs_verification():
    profile = base_profile(personal={"first_name": "Jane", "last_name": "Doe", "email": "doctor@example.org", "gender": "male", "nationality": "International"})
    report = match_job_against_profile(
        job("Afghan nationality required. Apply to hr@example.org by 2026-12-31."),
        profile,
        today=date(2026, 10, 1),
    ).to_dict()

    nationality_item = next((item for item in report["requirement_matches"] if item["key"] == "nationality_requirement"), None)
    if nationality_item is not None:
        assert nationality_item["status"] == "Needs verification"


def test_md_vacancy_with_valid_source_and_route_is_ready():
    report = match_job_against_profile(
        job("MD/Medical Doctor required. Registered with Afghan Medical Council. 1 year clinical experience. Apply to hr@example.org by 2026-12-31."),
        base_profile(),
        today=date(2026, 10, 1),
    ).to_dict()
    assert report["readiness_status"] == READY_TO_APPLY


def test_nurse_vacancy_is_not_eligible_for_md_unless_md_accepted():
    report = match_job_against_profile(
        job("Registered nurse with valid nursing license required. Apply to hr@example.org by 2026-12-31.", title="Staff Nurse"),
        base_profile(),
        today=date(2026, 10, 1),
    ).to_dict()
    assert report["readiness_status"] == NOT_ELIGIBLE_STATUS
    assert any(item["key"] == "role_family_compatibility" and item["status"] == "Not met" for item in report["requirement_matches"])


def test_pharmacist_vacancy_is_not_eligible_for_md_unless_md_accepted():
    report = match_job_against_profile(
        job("Bachelor degree in pharmacy and pharmacy license required. Apply to hr@example.org by 2026-12-31.", title="Pharmacist"),
        base_profile(),
        today=date(2026, 10, 1),
    ).to_dict()
    assert report["readiness_status"] == NOT_ELIGIBLE_STATUS


def test_nutrition_promoter_is_not_eligible_when_md_not_accepted():
    report = match_job_against_profile(
        job("Community nutrition promoter experience required. Conduct household nutrition promotion. Apply to hr@example.org by 2026-12-31.", title="Nutrition Promoter"),
        base_profile(),
        today=date(2026, 10, 1),
    ).to_dict()
    assert report["readiness_status"] == NOT_ELIGIBLE_STATUS


def test_female_only_and_male_only_constraints_are_deterministic():
    male_profile = base_profile()
    female_profile = base_profile(personal={"first_name": "Jane", "last_name": "Doe", "email": "doctor@example.org", "gender": "female", "nationality": "Afghan", "verification": {"first_name": True, "last_name": True, "email": True, "phone": True, "location": True, "nationality": True, "gender": True, "professional_title": True}})
    female_only = match_job_against_profile(job("Women only. Medical Doctor required. Apply to hr@example.org by 2026-12-31.", title="Female Medical Doctor"), male_profile, today=date(2026, 10, 1)).to_dict()
    male_only = match_job_against_profile(job("Male only. Medical Doctor required. Apply to hr@example.org by 2026-12-31.", title="Male Medical Doctor"), female_profile, today=date(2026, 10, 1)).to_dict()
    assert female_only["readiness_status"] == NOT_ELIGIBLE_STATUS
    assert male_only["readiness_status"] == NOT_ELIGIBLE_STATUS


def test_no_gender_restriction_is_not_rejected_for_gender_words():
    report = match_job_against_profile(
        job("Medical Doctor required. Provide care for women and men in the clinic. Female candidates are strongly encouraged to apply. Apply to hr@example.org by 2026-12-31."),
        base_profile(),
        today=date(2026, 10, 1),
    ).to_dict()
    gender_item = next((item for item in report["requirement_matches"] if item["key"] == "gender_requirement"), None)
    assert gender_item is None or gender_item["status"] != "Not met"
    assert report["readiness_status"] != NOT_ELIGIBLE_STATUS


def test_missing_direct_application_route_is_not_ready_even_with_official_vacancy_page():
    vacancy_page_only = job(
        "Medical Doctor required. Registered with Afghan Medical Council. 1 year clinical experience. See official vacancy page for instructions.",
        apply_url="https://example.org/jobs/j",
    )
    vacancy_page_only["metadata"]["application_method"] = "vacancy_page"
    report = match_job_against_profile(vacancy_page_only, base_profile(), today=date(2026, 10, 1)).to_dict()
    assert report["readiness_status"] != READY_TO_APPLY
    destination = next(item for item in report["requirement_matches"] if item["key"] == "application_destination")
    assert destination["status"] == "Needs verification"
