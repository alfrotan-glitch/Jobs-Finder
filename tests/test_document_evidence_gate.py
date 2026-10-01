"""Regression tests for the DOCUMENT EVIDENCE GATE and CONTACT/IDENTITY
CONTRACT.

Employer-facing generated documents (tailored CV / cover letter — TXT, and
the DOCX/PDF renders derived from the same text) must never promote
unverified profile data into factual content:

* unverified work history must not appear as factual experience;
* unverified skills must not become confirmed CV competencies;
* unverified certificates/training must not become confirmed credentials;
* unverified profile data must not enter vacancy-fit highlights;
* the professional summary must not carry hardcoded applicant claims;
* verified entries must still appear correctly;
* contact data follows one explicit rule: displayed for review even as a
  draft, never silently verified, placeholders replaced, and an unconfirmed
  personal block keeps a visible package blocker.
"""

import zipfile
from datetime import date
from pathlib import Path

from utils.documents import generate_application_package, generate_tailored_documents, prepare_application_bundle
from utils.medical_matcher import match_job_against_profile


def _job(description="MD required. Apply to hr@example.org by 2026-12-31.", title="Medical Officer"):
    return {
        "id": "j",
        "title": title,
        "company": "Health Org",
        "location": "Kabul",
        "url": "https://example.org/job",
        "apply_url": "hr@example.org",
        "description": description,
        "metadata": {"closing_date": "2026-12-31"},
    }


def _mixed_profile():
    """One verified and one unverified item in every verification-sensitive area."""
    return {
        "personal": {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane.real@clinic-example.af",
            "phone": "+93 70 123 4567",
            "location": "Kabul",
            "nationality": "Afghan",
            "gender": "female",
            "verified": True,
        },
        "medical_education": [
            {"degree": "MD", "institution": "Kabul Medical University", "verified": True},
            {"degree": "MD", "institution": "Unverified Diploma Mill", "verified": False},
        ],
        "license_registration": {"status": "Valid medical professional registration/license", "verified": True},
        "medical_exit_exam": {"status": "Completed", "verified": True},
        "clinical_experience": {"years": 4},
        "work_history": [
            {
                "title": "Medical Doctor",
                "organization": "Verified Clinic Alpha",
                "location": "Kabul",
                "start": "2022-01",
                "end": "Present",
                "description": "Clinical consultations, diagnosis, treatment, referral and HMIS reporting.",
                "verified": True,
            },
            {
                "title": "Regional Health Director",
                "organization": "Unverifiable Hospital Omega",
                "location": "Herat",
                "start": "2015-01",
                "end": "2021-12",
                "description": "Claimed supervision of forty clinics.",
                "verified": False,
            },
        ],
        "skills": {
            "medical": [
                {"name": "Clinical assessment and treatment", "verified": True},
                "Unverified neurosurgery expertise",
            ]
        },
        "certificates": [
            {"name": "IMNCI training (verified copy held)", "verified": True},
            "Unverified MBA diploma",
        ],
        "languages": [
            {"name": "Dari", "level": "Native", "verified": True},
            {"name": "English", "level": "Fluent", "verified": False},
        ],
    }


def _docs(profile, job=None):
    job = job or _job()
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    return generate_tailored_documents(job, profile, report), report


# ---------------------------------------------------------------------------
# Work history
# ---------------------------------------------------------------------------


def test_unverified_work_history_never_appears_as_factual_experience():
    docs, _ = _docs(_mixed_profile())
    for text in [docs["tailored_cv_text"], docs["cover_letter"]]:
        assert "Unverifiable Hospital Omega" not in text
        assert "Regional Health Director" not in text
        assert "forty clinics" not in text


def test_verified_work_history_still_appears():
    docs, _ = _docs(_mixed_profile())
    cv = docs["tailored_cv_text"]
    assert "PROFESSIONAL EXPERIENCE" in cv
    assert "Verified Clinic Alpha" in cv


def test_entirely_unverified_work_history_produces_no_experience_section():
    profile = _mixed_profile()
    profile["work_history"] = [dict(entry, verified=False) for entry in profile["work_history"]]
    docs, _ = _docs(profile)
    assert "PROFESSIONAL EXPERIENCE" not in docs["tailored_cv_text"]


def test_plain_string_work_history_entries_are_never_factual_experience():
    profile = _mixed_profile()
    profile["work_history"] = ["Self-reported: Chief Surgeon at Omega Hospital 2010-2020"]
    docs, _ = _docs(profile)
    assert "Chief Surgeon" not in docs["tailored_cv_text"]
    assert "Chief Surgeon" not in docs["cover_letter"]


# ---------------------------------------------------------------------------
# Skills / certificates / training
# ---------------------------------------------------------------------------


def test_unverified_skills_never_become_confirmed_competencies():
    docs, _ = _docs(_mixed_profile())
    for text in [docs["tailored_cv_text"], docs["cover_letter"]]:
        assert "neurosurgery" not in text.lower()


def test_verified_skills_appear_in_core_competencies():
    docs, _ = _docs(_mixed_profile())
    cv = docs["tailored_cv_text"]
    assert "CORE COMPETENCIES" in cv
    assert "Clinical assessment and treatment" in cv


def test_unverified_certificates_never_become_confirmed_credentials():
    docs, _ = _docs(_mixed_profile())
    for text in [docs["tailored_cv_text"], docs["cover_letter"]]:
        assert "MBA" not in text


def test_verified_certificates_appear():
    docs, _ = _docs(_mixed_profile())
    assert "IMNCI training (verified copy held)" in docs["tailored_cv_text"]


# ---------------------------------------------------------------------------
# Vacancy-fit highlights
# ---------------------------------------------------------------------------


def test_vacancy_fit_highlights_contain_only_verified_evidence():
    docs, _ = _docs(_mixed_profile())
    highlights = " ".join(docs["selected_vacancy_fit_evidence"])
    assert "Unverifiable Hospital Omega" not in highlights
    assert "neurosurgery" not in highlights.lower()
    assert "MBA" not in highlights
    # Verified evidence is still selectable.
    assert docs["selected_vacancy_fit_evidence"]
    assert any("Verified Clinic Alpha" in item or "Clinical" in item for item in docs["selected_vacancy_fit_evidence"])


# ---------------------------------------------------------------------------
# Professional summary / hardcoded claims
# ---------------------------------------------------------------------------


def test_summary_never_hardcodes_applicant_identity_when_nothing_verified():
    profile = {
        "personal": {"first_name": "Jane", "last_name": "Doe", "email": "jane.real@clinic-example.af"},
        "medical_education": [{"degree": "MD", "verified": False}],
        "work_history": [{"title": "Medical Officer", "organization": "Clinic", "verified": False}],
    }
    docs, _ = _docs(profile)
    cv = docs["tailored_cv_text"]
    summary = cv.split("PROFESSIONAL SUMMARY", 1)[1].split("\n\n", 1)[0]
    assert "Medical Doctor with Afghanistan health and nutrition" not in cv
    assert "Medical Doctor" not in summary
    assert "supervisory experience" not in summary


def test_summary_claims_medical_doctor_only_with_verified_md():
    docs, _ = _docs(_mixed_profile())
    summary = docs["tailored_cv_text"].split("PROFESSIONAL SUMMARY", 1)[1].split("\n\n", 1)[0]
    assert "Medical Doctor" in summary
    assert "years of verified clinical experience" in summary


# ---------------------------------------------------------------------------
# Languages
# ---------------------------------------------------------------------------


def test_unverified_language_not_listed_as_cv_fact():
    docs, _ = _docs(_mixed_profile())
    cv = docs["tailored_cv_text"]
    assert "LANGUAGES" in cv
    language_section = cv.split("LANGUAGES", 1)[1]
    assert "Dari" in language_section
    assert "English" not in language_section


def test_excluded_unverified_items_stay_visible_in_review_warnings():
    docs, _ = _docs(_mixed_profile())
    warnings = " ".join(docs["review_warnings"])
    assert "Unverifiable Hospital Omega" in warnings
    assert "neurosurgery" in warnings.lower()
    assert "MBA" in warnings
    assert "English" in warnings


# ---------------------------------------------------------------------------
# Contact/identity contract
# ---------------------------------------------------------------------------


def test_draft_contact_data_is_displayed_for_review_not_suppressed():
    profile = _mixed_profile()
    profile["personal"]["verified"] = False  # CV-import-like draft
    docs, _ = _docs(profile)
    cv = docs["tailored_cv_text"]
    assert "jane.real@clinic-example.af" in cv
    assert "+93 70 123 4567" in cv


def test_confirmed_contact_data_is_not_suppressed_or_replaced():
    docs, _ = _docs(_mixed_profile())
    cv = docs["tailored_cv_text"]
    assert "jane.real@clinic-example.af" in cv
    assert "CONFIRM BEFORE SUBMISSION" not in cv


def test_placeholder_contact_data_is_replaced_with_review_marker():
    profile = _mixed_profile()
    profile["personal"]["email"] = "doctor@example.org"
    profile["personal"]["phone"] = "+93 000 000 000"
    docs, _ = _docs(profile)
    cv = docs["tailored_cv_text"]
    assert "doctor@example.org" not in cv
    assert "CONFIRM BEFORE SUBMISSION" in cv


def test_unconfirmed_personal_block_keeps_visible_package_blocker():
    profile = _mixed_profile()
    profile["personal"]["verified"] = False
    job = _job()
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    docs = generate_tailored_documents(job, profile, report)
    package = generate_application_package(job, profile, report, docs)
    assert any("personal.verified" in item for item in package["missing_items"])
    assert package["package_status"] == "NEEDS_USER_INPUT"


def test_confirmed_personal_block_has_no_identity_blocker():
    profile = _mixed_profile()
    job = _job()
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    docs = generate_tailored_documents(job, profile, report)
    package = generate_application_package(job, profile, report, docs)
    assert not any("personal.verified" in item for item in package["missing_items"])


# ---------------------------------------------------------------------------
# DOCX / PDF artifacts (same gated source text)
# ---------------------------------------------------------------------------


def _docx_text(path):
    with zipfile.ZipFile(path) as archive:
        return archive.read("word/document.xml").decode("utf-8", errors="replace")


def _pdf_text(path):
    import pdfplumber

    chunks = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            chunks.append(page.extract_text() or "")
    return "\n".join(chunks)


def test_docx_and_pdf_artifacts_respect_the_evidence_gate(tmp_path):
    profile = _mixed_profile()
    job = _job()
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    bundle = prepare_application_bundle(job, profile, report, out_dir=tmp_path)
    for doc_key in ["tailored_cv", "cover_letter"]:
        paths = bundle["generated_paths"][doc_key]
        txt = Path(paths["txt"]).read_text(encoding="utf-8")
        docx = _docx_text(paths["docx"])
        pdf = _pdf_text(paths["pdf"])
        for rendered in [txt, docx, pdf]:
            assert "Unverifiable Hospital Omega" not in rendered
            assert "neurosurgery" not in rendered.lower()
            assert "MBA" not in rendered
            assert "Needs verification" not in rendered
    # Verified facts survive the full render chain.
    cv_docx = _docx_text(bundle["generated_paths"]["tailored_cv"]["docx"])
    cv_pdf = _pdf_text(bundle["generated_paths"]["tailored_cv"]["pdf"])
    assert "Verified Clinic Alpha" in cv_docx
    assert "Verified Clinic Alpha" in cv_pdf


def test_cv_import_draft_profile_produces_fully_gated_documents():
    """End-to-end regression: a complete CV-import draft (profile_builder
    output, which fills personal.location/nationality and languages with
    'Needs verification' placeholders) must yield employer-facing documents
    with no internal placeholder text, no unverified claims, and a neutral
    summary -- while still displaying draft contact data for review."""
    from utils.profile_builder import build_profile_from_cv_text

    cv_text = (
        "Jane Doe\nMedical Doctor (MD)\nEmail: jane.doe@example.org\n"
        "Phone: +93 70 111 2233\nLicense: Afghan Medical Council registration\n"
        "Languages: English (fluent), Dari (native)\n"
        "2018-2023 Medical Officer, Example Clinic, Kabul\n"
        "Certificates: BLS, ACLS\n"
    )
    profile = build_profile_from_cv_text(cv_text, resume_path="cv.txt")
    job = _job("MD required. Afghan Medical Council registration required. Fluent English. Apply to hr@example.org by 2026-12-31.")
    report = match_job_against_profile(job, profile, resume_text=cv_text, today=date(2026, 10, 1)).to_dict()
    docs = generate_tailored_documents(job, profile, report, resume_text=cv_text)
    for text in [docs["tailored_cv_text"], docs["cover_letter"]]:
        assert "Needs verification" not in text
        assert "Medical Doctor with Afghanistan" not in text
        assert "EDUCATION" not in text
        assert "LICENSE" not in text
        assert "LANGUAGES" not in text
        assert "English" not in text
    # Draft contact data is displayed for review (never suppressed).
    assert "jane.doe@example.org" in docs["tailored_cv_text"]
    # Neutral summary, no credential headline without a verified MD.
    assert "Applicant applying for the" in docs["tailored_cv_text"]
