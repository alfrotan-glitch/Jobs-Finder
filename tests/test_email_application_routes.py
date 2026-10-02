from datetime import date
from pathlib import Path

from utils.documents import prepare_application_bundle
from utils.medical_matcher import match_job_against_profile
from utils.medical_requirements import canonical_source_fields, has_actionable_source


def md_profile():
    return {
        "personal": {
            "first_name": "Ahmad",
            "last_name": "Rahimi",
            "email": "ahmad.rahimi@example.af",
            "phone": "+93 70 222 3344",
            "location": "Kabul",
            "gender": "male",
            "nationality": "Afghan",
            "verification": {"first_name": True, "last_name": True, "email": True, "phone": True, "location": True, "nationality": True, "gender": True, "professional_title": True},
        },
        "medical_education": [
            {
                "degree": "Doctor of Medicine (MD)",
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
        "license_registration": {"status": "Valid medical professional registration/license", "verified": True},
        "medical_exit_exam": {"status": "Completed", "verified": True},
        "clinical_experience": {"years": 4},
        "ngo_humanitarian_experience": {"years": 2},
        "preferences": {"locations": ["Kabul", "Afghanistan"], "field_deployment": "yes", "willing_to_relocate": "yes"},
        "work_history": [
            {
                "title": "Medical Doctor",
                "organization": "Kabul Provincial Clinic",
                "location": "Kabul",
                "start": "2022-01",
                "end": "Present",
                "description": "Provided clinical consultations. Conducted patient assessment, diagnosis and treatment. Coordinated referrals and HMIS reporting.",
                "verified": True,
            },
            {
                "title": "Health and Nutrition Supervisor",
                "organization": "Humanitarian Health NGO",
                "location": "Afghanistan",
                "start": "2020-01",
                "end": "2021-12",
                "description": "Supervised health and nutrition teams. Supported SAM, IMAM and therapeutic feeding services. Reviewed HMIS data and monthly reports.",
                "verified": True,
            },
        ],
        "skills": {
            "medical": [
                {"name": "Clinical care", "verified": True},
                {"name": "HMIS reporting", "verified": True},
                {"name": "Health and nutrition supervision", "verified": True},
            ]
        },
        "languages": [
            {"name": "Dari", "level": "Native", "verified": True},
            {"name": "English", "level": "Professional", "verified": True},
            {"name": "Pashto", "level": "Fluent", "verified": True},
        ],
    }


def email_job(company="Afghanistan Health Organization"):
    return {
        "id": "email-md",
        "title": "Medical Doctor (MD)",
        "company": company,
        "location": "Kabul",
        "url": "https://jobs.example.org/vacancies/email-md",
        "apply_url": "recruitment@example.org",
        "description": "Medical Doctor (MD) required. Clinical care, referrals and HMIS reporting. Send CV and cover letter to recruitment@example.org by 2026-12-31.",
        "metadata": {
            "source_name": "ACBAR",
            "source_url": "https://jobs.example.org/source",
            "vacancy_url": "https://jobs.example.org/vacancies/email-md",
            "reference_number": "MD-2026-01",
        },
    }


def web_job():
    return {
        "id": "web-md",
        "title": "Health and Nutrition Coordinator",
        "company": "Afghanistan Health Organization",
        "location": "Kabul",
        "url": "https://jobs.example.org/vacancies/web-md",
        "apply_url": "https://apply.example.org/forms/web-md",
        "description": "Medical Doctor accepted. Health and nutrition coordination, team supervision, HMIS monitoring and quality improvement. Apply online by 2026-12-31.",
        "metadata": {
            "source_name": "ACBAR",
            "source_url": "https://jobs.example.org/source",
            "vacancy_url": "https://jobs.example.org/vacancies/web-md",
            "application_method": "WEB",
        },
    }


def test_valid_email_route_is_canonical_email_and_never_localhost():
    source = canonical_source_fields(email_job())
    assert source["application_method"] == "EMAIL"
    assert source["apply_email"] == "recruitment@example.org"
    assert source["apply_url"] is None
    assert "localhost" not in str(source)
    assert source["source_url"] == "https://jobs.example.org/source"
    assert source["source_url"] != source["apply_email"]


def test_valid_web_route_is_canonical_web():
    source = canonical_source_fields(web_job())
    assert source["application_method"] == "WEB"
    assert source["apply_url"] == "https://apply.example.org/forms/web-md"
    assert source["apply_email"] == ""


def test_no_direct_route_is_unavailable_but_keeps_vacancy_page():
    job = email_job()
    job["apply_url"] = ""
    job["metadata"].pop("reference_number", None)
    job["description"] = "Medical Doctor (MD) required. See the official vacancy page for application instructions."
    source = canonical_source_fields(job)
    assert source["application_method"] == "UNAVAILABLE"
    assert source["apply_email"] == ""
    assert source["apply_url"] is None
    assert source["vacancy_url"] == "https://jobs.example.org/vacancies/email-md"


def test_unknown_source_is_not_actionable():
    job = email_job()
    job["metadata"]["source_name"] = "UNKNOWN"
    job["metadata"]["source_url"] = ""
    assert has_actionable_source(job) is False


def test_email_application_draft_is_generated_and_clean(tmp_path):
    profile = md_profile()
    job = email_job()
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    bundle = prepare_application_bundle(job, profile, report, out_dir=tmp_path)
    package = bundle["application_package"]
    draft = package["email_draft"]

    assert package["application_method"] == "EMAIL"
    assert package["apply_email"] == "recruitment@example.org"
    assert package["apply_url"] is None
    assert draft["to"] == "recruitment@example.org"
    assert draft["subject"] == "Application – Medical Doctor (MD) – Ref: MD-2026-01"
    assert "Medical Doctor (MD)" in draft["body"]
    assert "Kabul Provincial Clinic" in draft["body"] or "clinical" in draft["body"].lower()
    assert "Ahmad Rahimi" in draft["body"]
    assert "ahmad.rahimi@example.af" in draft["body"]
    assert "+93 70 222 3344" in draft["body"]
    assert any("cv" in item.lower() for item in draft["attachments_to_include"])
    assert any("cover" in item.lower() for item in draft["attachments_to_include"])
    forbidden = ["Jobs-Finder", "matching score", "eligibility", "evidence", "verification", "source", "job ID", "READY_TO_APPLY", "NEEDS_VERIFICATION", "package status"]
    for token in forbidden:
        assert token.lower() not in draft["body"].lower()


def test_unknown_organization_not_written_into_employer_facing_email(tmp_path):
    profile = md_profile()
    job = email_job(company="Unknown")
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    bundle = prepare_application_bundle(job, profile, report, out_dir=tmp_path)
    draft = bundle["application_package"]["email_draft"]
    assert "Unknown" not in draft["subject"]
    assert "Unknown" not in draft["body"]
    assert "Application – Medical Doctor (MD)" in draft["subject"]


def test_cv_cover_letter_and_md_identity_are_clean_and_include_high_school(tmp_path):
    profile = md_profile()
    job = email_job()
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    bundle = prepare_application_bundle(job, profile, report, out_dir=tmp_path)
    cv = Path(bundle["generated_paths"]["tailored_cv"]["txt"]).read_text(encoding="utf-8")
    cover = Path(bundle["generated_paths"]["cover_letter"]["txt"]).read_text(encoding="utf-8")

    assert "Medical Doctor" in cv.splitlines()[1]
    assert "Doctor of Medicine (MD) — Verified Medical Science University — 2013–2020" in cv
    assert "Verified High School — 2000–2012" in cv
    assert cv.index("Medical Doctor") < cv.index("Health and Nutrition Supervisor")
    for text in [cv, cover]:
        for token in ["Unknown", "Jobs-Finder", "evidence", "verification", "match", "eligibility", "READY_TO_APPLY", "NEEDS_VERIFICATION", "email-md"]:
            assert token.lower() not in text.lower()
    assert "Medical Doctor (MD)" in cover
    assert "Afghanistan Health Organization" in cover


def test_web_application_package_has_no_email_draft(tmp_path):
    profile = md_profile()
    job = web_job()
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    bundle = prepare_application_bundle(job, profile, report, out_dir=tmp_path)
    package = bundle["application_package"]
    assert package["application_method"] == "WEB"
    assert package["email_draft"] is None
    assert package["online_application"]["url"] == "https://apply.example.org/forms/web-md"
