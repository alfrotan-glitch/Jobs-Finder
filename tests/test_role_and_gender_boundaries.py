"""The discovery to recommendation boundary.

Every case below is a real ACBAR vacancy shape that must never reach the
recommendation list for a verified male MD profile, because the role family
is incompatible or the vacancy is female-only:

* A duty phrase ("Work closely with the medical doctor...", "Contact the
  physician for inaccuracy in prescription order...") was treated as "MD
  accepted", cancelling the nurse/pharmacist professional blocker.
* ACBAR's structured quick-summary row renders as "Gender Female" (label and
  value in separate elements, no colon) and was never extracted as a hard
  gender requirement; likewise "(Female)" title markers and "qualified female
  candidates can submit" submission guidelines.
* Psychology/psychosocial-counselling roles (MHPSS Counsellor, Mental Health
  Promoter) had no professional-role family at all and fell through to
  "ambiguous health words".

The fixes must never loosen the opposite direction: genuine MD vacancies stay
matchable, explicit MD acceptance still overrides a blocker, and unverified
profile gender still never excludes anyone.
"""

from datetime import date

from utils.medical_matcher import (
    NEEDS_VERIFICATION_STATUS,
    NOT_ELIGIBLE_STATUS,
    READY_TO_APPLY,
    match_job_against_profile,
)
from utils.medical_requirements import (
    analyze_professional_role,
    extract_gender_requirement,
    extract_labeled_gender_requirement,
)

TODAY = date(2026, 10, 1)


def md_profile(**updates):
    profile = {
        "personal": {"first_name": "Jane", "last_name": "Doe", "email": "doctor@example.org", "gender": "male", "nationality": "Afghan", "verified": True},
        "medical_education": [{"degree": "MD (Doctor of Medicine)", "verified": True}],
        "license_registration": {"status": "Valid medical professional registration/license", "verified": True},
        "medical_exit_exam": {"status": "Completed", "verified": True},
        "clinical_experience": {"years": 6},
        "ngo_humanitarian_experience": {"years": 5},
        "work_history": [
            {
                "title": "TFU Medical Doctor and PSEA focal point",
                "organization": "Action Against Hunger (ACF)",
                "start": "2021-01",
                "end": "2023-06",
                "verified": True,
                "skills": ["SAM", "IMAM", "CMAM", "TFU", "HMIS", "reporting", "supervision", "safeguarding"],
            }
        ],
        "preferences": {"locations": ["Afghanistan"], "field_deployment": True},
        "languages": [
            {"name": "Dari", "level": "Native", "verified": True},
            {"name": "Pashto", "level": "Fluent", "verified": True},
            {"name": "English", "level": "Professional", "verified": True},
        ],
    }
    profile.update(updates)
    return profile


def job(description, title, apply_url="hr@example.org", location="Kabul"):
    return {
        "id": "j",
        "title": title,
        "company": "Example Org",
        "location": location,
        "url": "https://example.org/jobs/j",
        "apply_url": apply_url,
        "description": description,
        "metadata": {
            "source_name": "ACBAR",
            "source_url": "https://example.org/jobs",
            "vacancy_url": "https://example.org/jobs/j",
            "application_method": "EMAIL" if "@" in str(apply_url) else "WEB",
        },
    }


def role_family_status(report):
    return next(item["status"] for item in report["requirement_matches"] if item["key"] == "role_family_compatibility")


# ---------------------------------------------------------------------------
# 1. Genuine MD role stays eligible (HealthNet TPO wording).
# ---------------------------------------------------------------------------


def test_real_md_vacancy_remains_ready_when_requirements_verified():
    report = match_job_against_profile(
        job(
            "Job Requirements Graduated from a registered and recognized medical faculty, passed the exit exam. "
            "Having 3 years of relevant work experience in similar health facilities. HMIS reporting. "
            "Fluency in local languages, and proficiency in English language. "
            "Submission Guideline send CV to recruitment@example.org by 2026-10-10.",
            title="Medical Doctor (MD)",
            apply_url="recruitment@example.org",
        ),
        md_profile(),
        today=TODAY,
    ).to_dict()
    assert role_family_status(report) == "Met"
    assert report["readiness_status"] == READY_TO_APPLY


# ---------------------------------------------------------------------------
# 2. Female-only MD vacancies are discovered but blocked for a verified male.
# ---------------------------------------------------------------------------


def test_female_marker_in_title_blocks_verified_male_profile():
    # Real case: CHA "Medical Doctor (Female) (Re Announced)" -- the body text
    # never says "female only"; the restriction lives in the title marker.
    report = match_job_against_profile(
        job(
            "Job Requirements Graduated from recognized medical university. At least 1 year of experience "
            "in the management of health and nutrition at clinics/HFs. Apply to hr@example.org by 2026-10-08.",
            title="Medical Doctor (Female) (Re Announced)",
        ),
        md_profile(),
        today=TODAY,
    ).to_dict()
    assert report["readiness_status"] == NOT_ELIGIBLE_STATUS
    assert any(item["key"] == "gender_requirement" and item["status"] == "Not met" for item in report["requirement_matches"])


def test_acbar_quick_summary_gender_row_without_colon_blocks_verified_male():
    # Real case: ACBAR detail pages render the structured field as
    # "Gender Female" (label/value in separate elements, no colon) ABOVE the
    # "Job Summary" marker, i.e. outside the requirement-scoped text.
    report = match_job_against_profile(
        job(
            "Quick Summary Type Full Time Location Kandahar - Nawa Category Program Nationality Afghan "
            "Gender Female Salary As per salary scale Vacancy Number 162-2026 "
            "Job Summary Provide outpatient care. "
            "Job Requirements Medical Doctor (MD degree) required. Apply to hr@example.org by 2026-10-10.",
            title="Medical Doctor",
            location="Kandahar",
        ),
        md_profile(),
        today=TODAY,
    ).to_dict()
    assert report["readiness_status"] == NOT_ELIGIBLE_STATUS
    assert any(item["key"] == "gender_requirement" and item["status"] == "Not met" for item in report["requirement_matches"])


def test_female_only_submission_guideline_blocks_verified_male():
    # Real case: YVO "Nutrition Trainer" -- "Interested and qualified female
    # candidates can submit their application..."
    report = match_job_against_profile(
        job(
            "Job Requirements Bachelor's degree in Nutrition, Public Health, Food and Nutrition, Nursing, "
            "Midwifery, Medicine, or another closely related field. Minimum 3 years of relevant professional "
            "experience in nutrition education. Submission Guideline Interested and qualified female candidates "
            "can submit their application by completing the online form: https://forms.gle/example by 2026-10-07.",
            title="Nutrition Trainer",
            apply_url="https://forms.gle/example",
        ),
        md_profile(),
        today=TODAY,
    ).to_dict()
    assert report["readiness_status"] == NOT_ELIGIBLE_STATUS
    assert any(item["key"] == "gender_requirement" and item["status"] == "Not met" for item in report["requirement_matches"])


def test_per_field_verified_gender_blocks_incompatible_gender_requirement():
    profile = md_profile(
        personal={
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "doctor@example.org",
            "gender": "male",
            "nationality": "Afghan",
            "verification": {"gender": True, "nationality": True},
        }
    )
    report = match_job_against_profile(
        job(
            "Job Requirements Graduated from recognized medical university. Apply to hr@example.org by 2026-10-08.",
            title="Medical Doctor (Female)",
        ),
        profile,
        today=TODAY,
    ).to_dict()
    assert report["readiness_status"] == NOT_ELIGIBLE_STATUS
    assert any(item["key"] == "gender_requirement" and item["status"] == "Not met" for item in report["requirement_matches"])


def test_unverified_gender_still_never_excludes():
    # Strictness must not flip the other way: with an UNVERIFIED gender the
    # same female-only vacancy is NEEDS_VERIFICATION, never NOT_MET/MET.
    profile = md_profile(personal={"first_name": "Jane", "last_name": "Doe", "email": "doctor@example.org", "gender": "male", "nationality": "Afghan"})
    report = match_job_against_profile(
        job(
            "Job Requirements Graduated from recognized medical university. Apply to hr@example.org by 2026-10-08.",
            title="Medical Doctor (Female)",
        ),
        profile,
        today=TODAY,
    ).to_dict()
    gender_item = next(item for item in report["requirement_matches"] if item["key"] == "gender_requirement")
    assert gender_item["status"] == "Needs verification"
    assert report["readiness_status"] == NEEDS_VERIFICATION_STATUS


def test_gender_male_female_and_any_rows_are_not_restrictions():
    assert extract_labeled_gender_requirement("Quick Summary Gender Male/Female Salary ...") is None
    assert extract_labeled_gender_requirement("Quick Summary Gender Any Salary ...") is None
    assert extract_labeled_gender_requirement("Quick Summary Gender Female Salary ...") == "female"
    assert extract_labeled_gender_requirement("Quick Summary Gender Male Salary ...") == "male"
    # Generic diversity boilerplate must never become a gender restriction.
    assert extract_gender_requirement("non-discrimination based on race, gender, age, or any other protected characteristic") is None
    assert extract_gender_requirement("workforce diversity in terms of gender, nationality and culture") is None


# ---------------------------------------------------------------------------
# 3/4. Pharmacist and Nurse blockers survive incidental doctor mentions.
# ---------------------------------------------------------------------------


def test_pharmacist_duty_mention_of_physician_does_not_unlock_md():
    # Real case: FMIC "Pharmacist" -- a duty phrase such as "Contact the
    # physician for inaccuracy in prescription order..." is not an MD role.
    report = match_job_against_profile(
        job(
            "Job Summary Review and check prescriptions. Contact the physician for inaccuracy in prescription "
            "order, proper documentation & communication of it to the nursing & pharmacy staff. "
            "Job Requirements B.Sc. in Pharmacy or Pharm D from a recognized university or institute. "
            "2-3 years of working experience. Apply via https://forms.gle/example by 2026-10-12.",
            title="Pharmacist",
            apply_url="https://forms.gle/example",
        ),
        md_profile(),
        today=TODAY,
    ).to_dict()
    assert role_family_status(report) == "Not met"
    assert report["readiness_status"] == NOT_ELIGIBLE_STATUS


def test_nurse_duty_mention_of_medical_doctor_does_not_unlock_md():
    # Real case: INTERSOS "Nurse Nutrition" -- "Work closely with the medical
    # doctor in the planning..." must not cancel the nursing blocker.
    report = match_job_against_profile(
        job(
            "Job Summary Provide nursing and nutritional care in the TFU. Duties: Work closely with the medical "
            "doctor in the planning and organizing OTP/SFP services at Health Facility level. In coordination "
            "with the medical doctor and Medical Unit, ensure adequate availability of all food supplies. "
            "Job Requirements Nursing/Midwifery certificate is required. 2+ years of relevant work experience. "
            "Apply via https://forms.gle/example by 2026-10-10.",
            title="Nurse Nutrition",
            apply_url="https://forms.gle/example",
        ),
        md_profile(),
        today=TODAY,
    ).to_dict()
    assert role_family_status(report) == "Not met"
    assert report["readiness_status"] == NOT_ELIGIBLE_STATUS


def test_explicit_md_acceptance_still_overrides_professional_blocker():
    # The protection must not become absolute: a vacancy that EXPLICITLY
    # accepts MD/physician credentials in its qualifications stays compatible.
    role = analyze_professional_role(
        "Nutrition Nurse",
        "Job Requirements Medical Doctor (MD) degree or Nursing diploma is required for this position.",
    )
    assert role["classification"] == "md_physician_role"


def test_qualification_section_md_acceptance_is_detected():
    # Real case: RI "Clinical mentor" -- "Specialist of oby/gyn, Female MD,
    # Midwife, master's degree in public health is preferred".
    role = analyze_professional_role(
        "Clinical mentor",
        "Job Requirements Specialist of oby/gyn, Female MD, Midwife, master's degree in public health is "
        "preferred (the shortlist candidates must be female). Minimum of three (3) years' experiences.",
    )
    assert role["classification"] == "md_physician_role"


def test_clinical_mentor_shortlist_must_be_female_blocks_verified_male():
    report = match_job_against_profile(
        job(
            "Job Requirements Specialist of oby/gyn, Female MD, Midwife, master's degree in public health is "
            "preferred (the shortlist candidates must be female). Minimum of three (3) years' experiences in "
            "implementing, clinical support, quality management. Apply to hr@example.org by 2026-10-03.",
            title="Clinical mentor",
        ),
        md_profile(),
        today=TODAY,
    ).to_dict()
    assert report["readiness_status"] == NOT_ELIGIBLE_STATUS
    assert any(item["key"] == "gender_requirement" and item["status"] == "Not met" for item in report["requirement_matches"])


# ---------------------------------------------------------------------------
# 5-8. Counselling/psychology roles and nutrition-trainer boundaries.
# ---------------------------------------------------------------------------


def test_mhpss_counsellor_with_psychology_degree_requirement_is_not_eligible():
    # Real case: ACF "TFU MHPSS Counsellor" -- "Bachelor`s degree or above in
    # psychology, and counselling / MoPH approved 2 years diploma in
    # psychosocial counselling."
    report = match_job_against_profile(
        job(
            "Job Summary Responsible for the implementation of MHPSS and care practice integrated with nutrition "
            "and health intervention. Job Requirements Bachelor`s degree or above in psychology, and counselling "
            "/ MoPH approved 2 years diploma in psychosocial counselling. At least 2 years of experience in "
            "mental health and psychosocial support in emergency is mandatory. Apply to hr@example.org by 2026-10-06.",
            title="TFU MHPSS Counsellor (Local Recruitment)",
        ),
        md_profile(),
        today=TODAY,
    ).to_dict()
    assert role_family_status(report) == "Not met"
    assert report["readiness_status"] == NOT_ELIGIBLE_STATUS


def test_mental_health_promoter_counsellor_role_is_not_eligible():
    # Real case: INTERSOS "Mental Health Promoter" -- "3+ years of as
    # counsellor dealing with CP, GBV and/or PwSN at least."
    report = match_job_against_profile(
        job(
            "Job Summary Ensure correct individual psychological support for cases referred by case workers. "
            "Job Requirements 3+ years of as counsellor dealing with CP, GBV and/or PwSN at least. English, "
            "Pashto and Dari skills are required. Apply via https://forms.gle/example by 2026-10-13.",
            title="Mental Health Promoter",
            apply_url="https://forms.gle/example",
        ),
        md_profile(),
        today=TODAY,
    ).to_dict()
    assert role_family_status(report) == "Not met"
    assert report["readiness_status"] == NOT_ELIGIBLE_STATUS


def test_nutrition_trainer_accepting_medicine_degree_is_not_hard_blocked():
    # Real case: YVO "Nutrition Trainer" explicitly lists "Medicine" among the
    # accepted degrees, so it is NOT an inherently incompatible role family --
    # it must stay reviewable (never silently Met on generic words alone).
    role = analyze_professional_role(
        "Nutrition Trainer",
        "Job Requirements Bachelor's degree in Nutrition, Public Health, Food and Nutrition, Nursing, "
        "Midwifery, Medicine, or another closely related field. Minimum 3 years of relevant professional "
        "experience in nutrition education.",
    )
    assert role["classification"] != "incompatible_professional_role"
    assert role["classification"] != "not_medical_or_public_health"


# ---------------------------------------------------------------------------
# 9/10. Generic health words never qualify; NEEDS_VERIFICATION never bypasses
# a hard professional incompatibility.
# ---------------------------------------------------------------------------


def test_generic_health_words_alone_never_make_role_family_met():
    report = match_job_against_profile(
        job(
            "Job Summary Support hospital nutrition and health activities in the community. "
            "Job Requirements Relevant experience. Apply to hr@example.org by 2026-12-31.",
            title="Community Support Worker",
        ),
        md_profile(),
        today=TODAY,
    ).to_dict()
    assert role_family_status(report) != "Met"
    assert report["readiness_status"] != READY_TO_APPLY


def test_needs_verification_items_cannot_bypass_hard_role_incompatibility():
    # Even when everything else is merely unverified, a proven professional
    # mismatch keeps the whole vacancy NOT_ELIGIBLE.
    sparse_profile = {
        "personal": {"first_name": "Jane", "last_name": "Doe", "email": "doctor@example.org", "verified": True},
        "medical_education": [{"degree": "MD", "verified": True}],
    }
    report = match_job_against_profile(
        job(
            "Job Requirements B.Sc. in Pharmacy or Pharm D required. 2-3 years of working experience. "
            "Contact the physician for prescription clarification. Apply to hr@example.org by 2026-12-31.",
            title="Pharmacist",
        ),
        sparse_profile,
        today=TODAY,
    ).to_dict()
    assert any(item["status"] == "Needs verification" for item in report["requirement_matches"])
    assert report["readiness_status"] == NOT_ELIGIBLE_STATUS
