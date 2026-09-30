from datetime import date

from utils.medical_matcher import MET, NEEDS_VERIFICATION, NOT_MET, match_job_against_profile


JOB = {
    "id": "job1",
    "title": "Medical Officer",
    "company": "Health NGO",
    "location": "Kabul",
    "url": "https://example.org/jobs/1",
    "apply_url": "https://example.org/apply/1",
    "platform": "test",
    "description": """
    Medical Officer required in Kabul. MD/MBBS and valid medical license required.
    Minimum 3 years clinical experience. BPHS, HMIS, reporting, English, Dari and Pashto required.
    Closing date: 30 September 2026.
    """,
    "metadata": {},
}


def profile(**overrides):
    base = {
        "personal": {"first_name": "A", "last_name": "Doctor", "email": "a@example.org", "location": "Kabul", "nationality": "Afghan"},
        "medical_education": [{"degree": "MD", "institution": "Kabul Medical University"}],
        "license_registration": {"authority": "MoPH", "number": "123"},
        "clinical_experience": {"years": 4},
        "skills": {"public_health": ["BPHS", "HMIS", "reporting"]},
        "languages": [{"name": "English", "level": "Good"}, {"name": "Dari", "level": "Native"}, {"name": "Pashto", "level": "Good"}],
        "preferences": {"locations": ["Kabul"], "willing_to_relocate": False},
    }
    base.update(overrides)
    return base


def statuses(report):
    return {item["key"]: item["status"] for item in report["requirement_matches"]}


def test_md_matching_met_with_profile_evidence():
    report = match_job_against_profile(JOB, profile(), today=date(2026, 9, 29)).to_dict()
    s = statuses(report)
    assert s["md_degree"] == MET
    assert s["license_registration"] == MET
    assert s["clinical_experience_years"] == MET
    assert report["priority"] in {"Review first", "Review soon"}


def test_missing_evidence_needs_verification_not_not_met():
    p = profile(license_registration={})
    report = match_job_against_profile(JOB, p, today=date(2026, 9, 29)).to_dict()
    assert statuses(report)["license_registration"] == NEEDS_VERIFICATION


def test_experience_requirement_not_met_when_verified_years_too_low():
    p = profile(clinical_experience={"years": 1})
    report = match_job_against_profile(JOB, p, today=date(2026, 9, 29)).to_dict()
    assert statuses(report)["clinical_experience_years"] == NOT_MET
    assert report["priority"] == "Low priority"


def test_invalid_application_url_is_not_met():
    job = dict(JOB, apply_url="not-a-url")
    report = match_job_against_profile(job, profile(), today=date(2026, 9, 29)).to_dict()
    app = [m for m in report["requirement_matches"] if m["key"] == "application_destination"][0]
    assert app["status"] == NOT_MET


def test_afghanistan_location_preference_satisfies_afghan_province():
    job = dict(JOB, location="Kunar", description="MD required. Deadline: 2026-10-10.")
    p = profile(preferences={"locations": ["Afghanistan", "Kabul"], "field_deployment": True})
    report = match_job_against_profile(job, p, today=date(2026, 9, 30)).to_dict()
    assert statuses(report)["location_requirement"] == MET


def test_missing_exit_exam_is_needs_verification():
    job = dict(JOB, description="Medical Doctor required. Successful completion of the required medical exit examination. Deadline: 2026-10-10.")
    report = match_job_against_profile(job, profile(), today=date(2026, 9, 30)).to_dict()
    assert statuses(report)["medical_exit_exam"] == NEEDS_VERIFICATION


def test_required_management_years_gap_makes_low_priority():
    job = dict(
        JOB,
        description="Medical Doctor required. Minimum 5 years of health program management experience. Deadline: 2026-10-10.",
    )
    p = profile(
        clinical_experience={"years": 6},
        work_history=[
            {
                "title": "Health Program Manager",
                "organization": "Health NGO",
                "start": "2025-01",
                "end": "2025-12",
                "description": "Managed health program activities.",
            }
        ],
    )
    report = match_job_against_profile(job, p, today=date(2026, 9, 30)).to_dict()
    assert statuses(report)["management_experience_years"] == NOT_MET
    assert report["priority"] == "Low priority"


def test_strict_readiness_requires_all_mandatory_requirements_met():
    from utils.medical_matcher import READY_TO_APPLY, NEEDS_VERIFICATION_STATUS, NOT_ELIGIBLE_STATUS, classify_application_readiness

    ready = match_job_against_profile(
        dict(JOB, description="Medical Doctor required. At least 2 years clinical experience. Apply at https://example.org/apply. Deadline: 2026-10-10."),
        profile(clinical_experience={"years": 3}),
        today=date(2026, 9, 30),
    ).to_dict()
    assert ready["readiness_status"] == READY_TO_APPLY
    assert classify_application_readiness(ready) == READY_TO_APPLY

    verify = match_job_against_profile(
        dict(JOB, description="Medical Doctor and valid medical license required. Apply at https://example.org/apply. Deadline: 2026-10-10."),
        profile(license_registration={}),
        today=date(2026, 9, 30),
    ).to_dict()
    assert verify["readiness_status"] == NEEDS_VERIFICATION_STATUS

    not_eligible = match_job_against_profile(
        dict(JOB, description="Female Medical Doctor required. Apply at https://example.org/apply. Deadline: 2026-10-10."),
        profile(personal={"gender": "male"}),
        today=date(2026, 9, 30),
    ).to_dict()
    assert not_eligible["readiness_status"] == NOT_ELIGIBLE_STATUS


def test_missing_required_application_subject_blocks_ready_to_apply():
    from utils.medical_matcher import NEEDS_VERIFICATION_STATUS

    job = dict(
        JOB,
        description="Medical Doctor required. Indicate the job title and vacancy number in the email subject line. Email / Application Form: jobs@example.org. Deadline: 2026-10-10.",
    )
    report = match_job_against_profile(job, profile(), today=date(2026, 9, 30)).to_dict()
    assert report["readiness_status"] == NEEDS_VERIFICATION_STATUS
    assert statuses(report)["application_subject"] == NEEDS_VERIFICATION


def test_owner_confirmed_medical_license_and_exit_exam_are_met_without_number():
    from utils.medical_matcher import READY_TO_APPLY

    job = dict(
        JOB,
        description="Medical Doctor required. Valid medical license required. Successful completion of the required medical exit examination. Apply at https://example.org/apply. Deadline: 2026-10-10.",
    )
    p = profile(
        license_registration={
            "authority": "Afghan Medical Council / medical professional registration",
            "number": "",
            "status": "Verified — holds valid medical professional registration/license",
            "verified": True,
            "source": "owner-confirmed on 2026-09-30",
        },
        medical_exit_exam={
            "status": "Verified — completed the required Medical Exit Exam",
            "verified": True,
            "source": "owner-confirmed on 2026-09-30",
        },
    )
    report = match_job_against_profile(job, p, today=date(2026, 9, 30)).to_dict()
    s = statuses(report)
    assert s["license_registration"] == MET
    assert s["medical_exit_exam"] == MET
    assert "license_number" not in s
    assert report["readiness_status"] == READY_TO_APPLY


def test_license_number_specific_requirement_stays_needs_verification_without_number():
    from utils.medical_matcher import NEEDS_VERIFICATION_STATUS

    job = dict(
        JOB,
        description="Medical Doctor required. Valid medical registration required. Enter the medical registration number in the application form. Apply at https://example.org/apply. Deadline: 2026-10-10.",
    )
    p = profile(
        license_registration={
            "authority": "Afghan Medical Council / medical professional registration",
            "number": "",
            "status": "Verified — holds valid medical professional registration/license",
            "verified": True,
        }
    )
    report = match_job_against_profile(job, p, today=date(2026, 9, 30)).to_dict()
    s = statuses(report)
    assert s["license_registration"] == MET
    assert s["license_number"] == NEEDS_VERIFICATION
    assert report["readiness_status"] == NEEDS_VERIFICATION_STATUS


def test_license_number_specific_requirement_is_met_when_number_is_in_profile():
    job = dict(
        JOB,
        description="Medical Doctor required. Valid medical registration required. Enter the medical registration number in the application form. Apply at https://example.org/apply. Deadline: 2026-10-10.",
    )
    p = profile(license_registration={"authority": "MoPH", "number": "AMC-123", "verified": True})
    report = match_job_against_profile(job, p, today=date(2026, 9, 30)).to_dict()
    s = statuses(report)
    assert s["license_registration"] == MET
    assert s["license_number"] == MET


def test_phc_requirement_can_be_met_by_bphs_ephs_profile_evidence():
    job = dict(
        JOB,
        description="Medical Doctor required. Strong knowledge of primary healthcare principles and practices. Apply at https://example.org/apply. Deadline: 2026-10-10.",
    )
    p = profile(skills={"public_health": ["BPHS", "EPHS", "HMIS"]})
    report = match_job_against_profile(job, p, today=date(2026, 9, 30)).to_dict()
    assert statuses(report)["phc"] == MET


def test_dari_required_email_title_and_position_code_blocks_ready_without_exact_code():
    from utils.medical_matcher import NEEDS_VERIFICATION_STATUS

    job = dict(
        JOB,
        apply_url="",
        description="Medical Doctor required. Email / Application Form: hr@example.org. هنگام ارسال اسناد از طریق ایمیل، درج عنوان و کُد بست مربوطه الزامی است. Deadline: 2026-10-10.",
    )
    report = match_job_against_profile(job, profile(), today=date(2026, 9, 30)).to_dict()
    assert statuses(report)["application_subject"] == NEEDS_VERIFICATION
    assert report["readiness_status"] == NEEDS_VERIFICATION_STATUS
