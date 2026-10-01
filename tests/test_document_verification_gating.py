"""Regression tests: generated CV/cover letter text must never promote
unverified facts into confirmed claims (brief requirements #6-13).
"""

from datetime import date

from utils.documents import generate_tailored_documents
from utils.medical_matcher import match_job_against_profile


def _job(description, title="Medical Officer"):
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


def _unverified_profile():
    return {
        "personal": {"first_name": "Jane", "last_name": "Doe", "email": "doctor@example.org", "phone": "+93700000000", "location": "Kabul", "nationality": "Afghan"},
        # CV-import-shaped draft: everything present but NOT verified.
        "medical_education": [{"degree": "MD", "institution": "Needs verification", "verified": False}],
        "license_registration": {"status": "Mentioned in CV; verify details", "verified": False},
        "medical_exit_exam": {"status": "Mentioned in CV; verify details", "verified": False},
        "languages": [{"name": "English", "level": "Needs verification", "verified": False}],
        "work_history": [{"title": "Medical Officer", "organization": "Clinic", "start": "2018-01", "end": "2023-01", "description": "Clinical care", "verified": False}],
    }


def test_education_section_excludes_unverified_entries():
    job = _job("Medical Degree required. Apply to hr@example.org by 2026-12-31.")
    profile = _unverified_profile()
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    docs = generate_tailored_documents(job, profile, report)
    assert "EDUCATION" not in docs["tailored_cv_text"] or "MD" not in docs["tailored_cv_text"].split("EDUCATION", 1)[1].split("\n\n", 1)[0]


def test_education_section_includes_only_verified_entries():
    job = _job("Medical Degree required. Apply to hr@example.org by 2026-12-31.")
    profile = _unverified_profile()
    profile["medical_education"] = [{"degree": "MD", "verified": True}]
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    docs = generate_tailored_documents(job, profile, report)
    assert "EDUCATION" in docs["tailored_cv_text"]
    section = docs["tailored_cv_text"].split("EDUCATION", 1)[1]
    assert "MD" in section


def test_cover_letter_never_claims_verified_license_when_unverified():
    job = _job("Medical Degree required. Afghan Medical Council registration required. Apply to hr@example.org by 2026-12-31.")
    profile = _unverified_profile()
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    docs = generate_tailored_documents(job, profile, report)
    cover = docs["cover_letter"].lower()
    assert "verified medical professional registration" not in cover
    assert "my license" not in cover or "verified" not in cover


def test_cover_letter_never_claims_verified_exam_when_unverified():
    job = _job("Medical Exit Exam required. Apply to hr@example.org by 2026-12-31.")
    profile = _unverified_profile()
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    docs = generate_tailored_documents(job, profile, report)
    cover = docs["cover_letter"].lower()
    assert "verified" not in cover or "exit exam" not in cover.split("verified")[0][-40:]


def test_cover_letter_language_claim_is_neutral_when_not_verified():
    job = _job("Fluent English required. Apply to hr@example.org by 2026-12-31.")
    profile = _unverified_profile()
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    docs = generate_tailored_documents(job, profile, report)
    cover = docs["cover_letter"]
    assert "verified language profile" not in cover.lower()


def test_cover_letter_claims_verified_language_only_when_explicitly_verified():
    job = _job("Fluent English required. Apply to hr@example.org by 2026-12-31.")
    profile = _unverified_profile()
    profile["languages"] = [{"name": "English", "level": "Fluent", "verified": True}]
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    docs = generate_tailored_documents(job, profile, report)
    assert "verified language profile" in docs["cover_letter"].lower()


def test_generated_text_never_contains_raw_placeholder_tokens():
    job = _job("Medical Degree required. Apply to hr@example.org by 2026-12-31.")
    profile = _unverified_profile()
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    docs = generate_tailored_documents(job, profile, report)
    for text in [docs["tailored_cv_text"], docs["cover_letter"]]:
        assert "Needs verification" not in text
