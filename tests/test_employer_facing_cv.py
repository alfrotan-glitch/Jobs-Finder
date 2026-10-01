import copy
import re
import zipfile
from datetime import date
from pathlib import Path

import pdfplumber

from utils.documents import generate_tailored_documents, prepare_application_bundle
from utils.medical_matcher import match_job_against_profile


def six_role_profile():
    return {
        "personal": {
            "first_name": "Ahmad", "last_name": "Example",
            "email": "ahmad@example.af", "phone": "+93 70 123 4567",
            "location": "Afghanistan", "professional_title": "Medical Doctor",
            "verified": True,
        },
        "medical_education": [{"degree": "Doctor of Medicine (MD)", "institution": "Medical University", "year": "2018", "verified": True}],
        "license_registration": {"authority": "Medical Council", "status": "Registered", "verified": True},
        "medical_exit_exam": {"status": "Completed", "verified": True},
        "work_history": [
            {
                "title": "Medical Doctor & Safeguarding/PSEA Focal Point", "organization": "ACF",
                "start": "2023", "end": "2025", "verified": True,
                "bullets": [
                    "Provided clinical care and coordinated patient referrals",
                    "Maintained HMIS records and prepared health reports",
                    "Supported clinical audit and quality improvement activities",
                    "Coached health workers and supported clinical supervision",
                    "Served as Safeguarding/PSEA Focal Point",
                ],
            },
            {
                "title": "Health & Nutrition Supervisor", "organization": "ACF", "start": "2022", "end": "2022", "verified": True,
                "bullets": [
                    "Supervised health and nutrition program activities",
                    "Reviewed health data and supported community health reporting",
                    "Provided training and support to health workers",
                ],
            },
            {
                "title": "Public Relations & Communications Advisor", "organization": "Daikundi Governor's Office",
                "start": "2020", "end": "2021", "verified": True,
                "bullets": ["Prepared public communications and coordinated public information activities"],
            },
            {
                "title": "COVID-19 Rapid Response Team Leader / Medical Doctor",
                "organization": "Daikundi Provincial Public Health Directorate", "start": "2020", "end": "2020", "verified": True,
                "bullets": ["Led the COVID-19 rapid response team", "Provided medical support and public-health reporting"],
            },
            {
                "title": "Administrative & Finance Officer", "organization": "Trend for a Better Tomorrow NGO",
                "start": "2019", "end": "2019", "verified": True,
                "bullets": ["Supported administrative and finance operations"],
            },
            {
                "title": "Public Awareness Officer / Public Awareness Promoter", "organization": "IEC",
                "start": "2013", "end": "2014", "verified": True,
                "bullets": ["Delivered public awareness activities with communities"],
            },
        ],
        "skills": {
            "medical": [{"name": "Clinical care", "verified": True}, {"name": "Patient referral coordination", "verified": True}],
            "public_health": [{"name": "HMIS and health data management", "verified": True}, {"name": "Clinical audit and quality improvement", "verified": True}],
            "management": [{"name": "Supportive supervision and mentorship", "verified": True}],
        },
        "certificates": [{"name": "Safeguarding and PSEA training", "verified": True}],
        "languages": [{"name": "Dari", "level": "Native", "verified": True}, {"name": "English", "level": "Professional", "verified": True}],
    }


def clinical_mentor_job():
    return {
        "id": "clinical-mentor", "title": "Clinical Mentor", "company": "Health NGO", "location": "Afghanistan",
        "url": "https://example.org/clinical-mentor", "apply_url": "hr@example.org",
        "description": "Clinical care, patient referral, supportive supervision, coaching, HMIS, health data management, reporting, quality improvement and training of health workers. Apply to hr@example.org by 2026-12-31.",
        "metadata": {"closing_date": "2026-12-31"},
    }


def docs_for(profile, job):
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    return generate_tailored_documents(job, profile, report), report


def test_all_six_verified_roles_survive_tailoring_and_profile_is_not_mutated():
    profile = six_role_profile()
    before = copy.deepcopy(profile)
    docs, _ = docs_for(profile, clinical_mentor_job())
    cv = docs["tailored_cv_text"]
    for organization in ["ACF", "Daikundi Governor's Office", "Daikundi Provincial Public Health Directorate", "Trend for a Better Tomorrow NGO", "IEC"]:
        assert organization in cv
    for role in ["Medical Doctor & Safeguarding/PSEA Focal Point", "Health & Nutrition Supervisor", "COVID-19 Rapid Response Team Leader / Medical Doctor", "Administrative & Finance Officer", "Public Awareness Officer / Public Awareness Promoter"]:
        assert role in cv
    assert profile == before


def test_clinical_mentor_keeps_all_relevant_verified_duties_and_tailors_order():
    profile = six_role_profile()
    clinical_docs, _ = docs_for(profile, clinical_mentor_job())
    generic_job = dict(clinical_mentor_job(), title="General Program Officer", description="General program administration and coordination. Apply to hr@example.org by 2026-12-31.")
    generic_docs, _ = docs_for(profile, generic_job)
    clinical = clinical_docs["tailored_cv_text"]
    generic = generic_docs["tailored_cv_text"]
    acf_section = clinical.split("Medical Doctor & Safeguarding/PSEA Focal Point", 1)[1].split("Health & Nutrition Supervisor", 1)[0]
    for duty in profile["work_history"][0]["bullets"]:
        assert duty in acf_section
    assert clinical != generic
    assert clinical.index("Medical Doctor & Safeguarding/PSEA Focal Point") < clinical.index("Administrative & Finance Officer")


def test_cv_has_no_internal_labels_or_fabricated_year_totals():
    docs, _ = docs_for(six_role_profile(), clinical_mentor_job())
    cv = docs["tailored_cv_text"]
    forbidden = [
        "TARGET", "APPLICATION FOCUS", "VERIFIED MEDICAL BASIS", "reviewed role-relevant evidence",
        "package status", "match evidence", "Jobs-Finder",
    ]
    for token in forbidden:
        assert token.lower() not in cv.lower()
    summary = cv.split("PROFESSIONAL SUMMARY", 1)[1].split("\n\n", 1)[0]
    assert not re.search(r"\b\d+(?:\.\d+)?\s+years\b", summary, flags=re.I)
    assert "conducted randomized trials" not in cv.lower()


def test_pdf_docx_render_complete_content_without_two_page_truncation(tmp_path):
    profile = six_role_profile()
    job = clinical_mentor_job()
    docs, report = docs_for(profile, job)
    bundle = prepare_application_bundle(job, profile, report, out_dir=tmp_path)
    paths = bundle["generated_paths"]["tailored_cv"]
    assert zipfile.is_zipfile(paths["docx"])
    with zipfile.ZipFile(paths["docx"]) as archive:
        docx_xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    with pdfplumber.open(paths["pdf"]) as pdf:
        pdf_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        assert len(pdf.pages) >= 2
    for rendered in [Path(paths["txt"]).read_text(encoding="utf-8"), docx_xml, pdf_text]:
        assert "Medical Doctor &amp; Safeguarding/PSEA Focal Point" in rendered or "Medical Doctor & Safeguarding/PSEA Focal Point" in rendered
        assert "Public Awareness Officer / Public Awareness Promoter" in rendered
        assert "Verified Medical Basis" not in rendered
        assert "Application Focus" not in rendered
        assert "Page 1 / 2" not in rendered
    # Competency phrases must remain intact in the source and rendered formats.
    assert "HMIS and health data management" in pdf_text.replace("\n", " ")
    assert "Clinical audit and quality improvement" in pdf_text.replace("\n", " ")


def test_long_verified_history_flows_beyond_two_pages_without_content_loss(tmp_path):
    profile = six_role_profile()
    extra = [f"Verified clinical responsibility number {number} with patient care documentation" for number in range(1, 46)]
    profile["work_history"][0]["bullets"].extend(extra)
    job = clinical_mentor_job()
    _, report = docs_for(profile, job)
    bundle = prepare_application_bundle(job, profile, report, out_dir=tmp_path)
    paths = bundle["generated_paths"]["tailored_cv"]
    with pdfplumber.open(paths["pdf"]) as pdf:
        pdf_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        assert len(pdf.pages) >= 3
    with zipfile.ZipFile(paths["docx"]) as archive:
        docx_xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    assert extra[-1] in pdf_text.replace("\n", " ")
    assert extra[-1] in docx_xml
