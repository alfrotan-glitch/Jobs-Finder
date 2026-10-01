from datetime import date
from pathlib import Path

from utils.documents import prepare_application_bundle
from utils.medical_matcher import match_job_against_profile


SYNTHETIC_FIXTURE_IDENTITY = [
    "Ahmad Rahimi",
    "ahmad.rahimi@example.af",
    "+93 70 222 3344",
]


def confirmed_profile():
    """A production-shaped, explicitly verified profile that is not a fixture default.

    The exact identity/contact values are deliberately neutral test values so
    private user profile data is not committed, while still proving that the
    generator must use the supplied profile object rather than any synthetic
    fixture identity.
    """
    return {
        "personal": {
            "first_name": "VERIFIED",
            "last_name": "PROFILE OWNER",
            "professional_title": "Medical Doctor | Health & Nutrition Program Coordination",
            "email": "verified.owner@profile.example.org",
            "phone": "+93700111222",
            "location": "Kabul, Afghanistan",
            "nationality": "Afghan",
            "gender": "Male",
            "verified": True,
        },
        "professional_summary": {
            "text": "Medical Doctor with clinical, health and nutrition program experience in Afghanistan.",
            "verified": True,
        },
        "medical_education": [
            {
                "degree": "MD",
                "institution": "Verified Medical Science University",
                "start": "2013",
                "end": "2020",
                "verified": True,
            }
        ],
        "education": [
            {
                "institution": "Verified High School",
                "start": "2000",
                "end": "2012",
                "verified": True,
            }
        ],
        "work_history": [
            {
                "title": "TFU Doctor & Safeguarding/PSEA Focal Point",
                "organization": "Verified Humanitarian Health Organization",
                "location": "Daikundi, Afghanistan",
                "start": "May 2023",
                "end": "July 2025",
                "bullets": [
                    "Provided clinical assessment, diagnosis, treatment and follow-up for severe acute malnutrition and related medical complications.",
                    "Supported HMIS reporting, clinical monitoring, case reviews and quality-improvement activities.",
                ],
                "verified": True,
            },
            {
                "title": "Health & Nutrition Supervisor",
                "organization": "Verified Humanitarian Health Organization",
                "location": "Daikundi, Afghanistan",
                "start": "February 2022",
                "end": "December 2022",
                "bullets": [
                    "Supervised and supported mobile health and nutrition teams in field settings.",
                    "Supported SAM/MAM screening, referral, OTP activities and nutrition case follow-up.",
                ],
                "verified": True,
            },
        ],
        "skills": {
            "clinical": [
                {"name": "Therapeutic Feeding Unit (TFU) operations", "verified": True},
                {"name": "HMIS reporting", "verified": True},
            ]
        },
        "languages": [
            {"name": "Dari", "level": "Native", "verified": True},
            {"name": "English", "level": "Fluent", "verified": True},
        ],
        "preferences": {"locations": ["Kabul", "Afghanistan"]},
    }


def representative_md_email_job():
    return {
        "id": "confirmed-profile-md-email",
        "title": "Medical Doctor (MD)",
        "company": "Afghanistan Health Organization",
        "location": "Kabul",
        "url": "https://jobs.example.org/vacancies/confirmed-profile-md-email",
        "apply_url": "recruitment@example.org",
        "description": "Medical Doctor (MD) required for clinical care, nutrition services, HMIS reporting and quality improvement. Apply by email to recruitment@example.org by 2026-12-31.",
        "metadata": {
            "source_name": "ACBAR",
            "source_url": "https://jobs.example.org/source",
            "vacancy_url": "https://jobs.example.org/vacancies/confirmed-profile-md-email",
        },
    }


def test_confirmed_profile_identity_does_not_inherit_synthetic_fixture_identity(tmp_path):
    profile = confirmed_profile()
    job = representative_md_email_job()
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    bundle = prepare_application_bundle(job, profile, report, out_dir=tmp_path)

    cv = Path(bundle["generated_paths"]["tailored_cv"]["txt"]).read_text(encoding="utf-8")
    cover = Path(bundle["generated_paths"]["cover_letter"]["txt"]).read_text(encoding="utf-8")
    email = bundle["application_package"]["email_draft"]
    email_text = f"{email['to']}\n{email['subject']}\n{email['body']}"

    for text in [cv, cover, email_text]:
        assert "VERIFIED PROFILE OWNER" in text
        assert "verified.owner@profile.example.org" in text
        assert "+93700111222" in text
        for synthetic in SYNTHETIC_FIXTURE_IDENTITY:
            assert synthetic not in text
        for forbidden in ["Jobs-Finder", "READY_TO_APPLY", "NEEDS_VERIFICATION", "matching score", "internal job ID"]:
            assert forbidden.lower() not in text.lower()

    assert "Medical Doctor | Health & Nutrition Program Coordination" in cv
    assert "Email: verified.owner@profile.example.org" in cv
    assert "Phone: +93700111222" in cv
    assert "Location: Kabul, Afghanistan" in cv
    assert "Email: verified.owner@profile.example.org" in email["body"]
    assert "Phone: +93700111222" in email["body"]
    assert "MD — Verified Medical Science University — 2013–2020" in cv
    assert "Verified High School — 2000–2012" in cv
    assert cv.index("TFU Doctor & Safeguarding/PSEA Focal Point") < cv.index("Health & Nutrition Supervisor")
    assert email["to"] == "recruitment@example.org"
    assert bundle["application_package"]["application_method"] == "EMAIL"
    assert bundle["application_package"]["apply_email"] == "recruitment@example.org"
    assert bundle["application_package"]["apply_url"] is None
