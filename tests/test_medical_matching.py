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
