import json
import zipfile
from datetime import date
from pathlib import Path

import pytest

from utils.documents import prepare_application_bundle
from utils.medical_matcher import NOT_ELIGIBLE_STATUS, match_job_against_profile


def profile():
    return {
        "personal": {"first_name": "Jane", "last_name": "Doe", "email": "doctor@example.org", "phone": "+93700000000", "location": "Kabul", "gender": "male", "nationality": "Afghan", "verification": {"first_name": True, "last_name": True, "email": True, "phone": True, "location": True, "nationality": True, "gender": True, "professional_title": True}},
        "medical_education": [{"degree": "MD", "verified": True}],
        "license_registration": {"status": "Valid medical professional registration/license", "verified": True},
        "medical_exit_exam": {"status": "Completed", "verified": True},
        "clinical_experience": {"years": 4, "settings": ["clinic", "hospital"], "verified": True},
        "skills": {"medical": ["Clinical care", "Patient assessment"], "public_health": ["Nutrition", "TSFP", "HMIS"], "management": ["Supervision", "Reporting"]},
        "work_history": [
            {"title": "Medical Doctor", "organization": "Verified Clinic", "location": "Kabul", "start": "2022-01", "end": "Present", "description": "Clinical consultations, patient assessment, diagnosis, treatment, referral and HMIS reporting.", "verified": True},
            {"title": "Health and Nutrition Supervisor", "organization": "Verified NGO", "location": "Afghanistan", "start": "2020-01", "end": "2021-12", "description": "Nutrition screening, TSFP coordination, supervision, reporting and team mentoring.", "verified": True},
        ],
        "languages": [
            {"name": "Dari", "level": "Native", "verified": True},
            {"name": "Pashto", "level": "Fluent", "verified": True},
            {"name": "English", "level": "Professional", "verified": True},
        ],
    }


def make_job(title, description):
    return {"id": title.lower().replace(" ", "_"), "title": title, "company": "Health Org", "location": "Kabul", "url": "https://example.org/job", "apply_url": "hr@example.org", "description": description, "metadata": {"closing_date": "2026-12-31"}}


def assert_valid_outputs(paths):
    cv = paths["tailored_cv"]
    cover = paths["cover_letter"]
    assert Path(cv["txt"]).read_text(encoding="utf-8")
    assert Path(cover["txt"]).read_text(encoding="utf-8")
    assert Path(cv["pdf"]).read_bytes().startswith(b"%PDF")
    assert Path(cover["pdf"]).read_bytes().startswith(b"%PDF")
    assert zipfile.is_zipfile(cv["docx"])
    assert zipfile.is_zipfile(cover["docx"])


def test_application_package_outputs_pdf_docx_txt_and_preserves_route(tmp_path):
    prof = profile()
    job = make_job("Medical Officer", "MD required. Afghan Medical Council registration. 2 years clinical experience. Send CV to hr@example.org by 2026-12-31.")
    report = match_job_against_profile(job, prof, today=date(2026, 10, 1)).to_dict()

    bundle = prepare_application_bundle(job, prof, report, out_dir=tmp_path)

    assert bundle["no_submission_performed"] is True
    assert bundle["application_package"]["application_route"] == "hr@example.org"
    assert_valid_outputs(bundle["generated_paths"])


def test_not_eligible_vacancy_cannot_receive_package(tmp_path):
    prof = profile()
    job = make_job("Female Medical Doctor", "Female Medical Doctor required. Send CV to hr@example.org by 2026-12-31.")
    report = match_job_against_profile(job, prof, today=date(2026, 10, 1)).to_dict()
    assert report["readiness_status"] == NOT_ELIGIBLE_STATUS

    with pytest.raises(ValueError):
        prepare_application_bundle(job, prof, report, out_dir=tmp_path)


def test_tailoring_changes_between_clinical_and_nutrition_roles(tmp_path):
    prof = profile()
    medical = make_job("Medical Officer", "Clinical patient care, diagnosis, treatment, OPD, referral and medical documentation required. Apply hr@example.org by 2026-12-31.")
    nutrition = make_job("TSFP Project Supervisor", "MD required. TSFP nutrition management, supervision, HMIS reporting and team coordination required. Apply hr@example.org by 2026-12-31.")
    medical_report = match_job_against_profile(medical, prof, today=date(2026, 10, 1)).to_dict()
    nutrition_report = match_job_against_profile(nutrition, prof, today=date(2026, 10, 1)).to_dict()

    medical_bundle = prepare_application_bundle(medical, prof, medical_report, out_dir=tmp_path / "m")
    nutrition_bundle = prepare_application_bundle(nutrition, prof, nutrition_report, out_dir=tmp_path / "n")

    medical_cv = Path(medical_bundle["generated_paths"]["tailored_cv"]["txt"]).read_text(encoding="utf-8")
    nutrition_cv = Path(nutrition_bundle["generated_paths"]["tailored_cv"]["txt"]).read_text(encoding="utf-8")
    assert medical_cv != nutrition_cv
    assert "TSFP" in nutrition_cv or "Nutrition" in nutrition_cv
    assert "license number" not in medical_cv.lower()


def test_package_json_contains_review_warnings_for_verification(tmp_path):
    prof = profile()
    prof["clinical_experience"] = {"years": "", "verified": False}
    prof["work_history"] = []
    job = make_job("Medical Doctor", "MD required. 3 years clinical experience. Send CV to hr@example.org by 2026-12-31.")
    report = match_job_against_profile(job, prof, today=date(2026, 10, 1)).to_dict()
    bundle = prepare_application_bundle(job, prof, report, out_dir=tmp_path)
    package_json = Path(bundle["generated_paths"]["application_package_json"])
    package = json.loads(package_json.read_text(encoding="utf-8"))

    assert package["missing_items"]
    assert any("Clinical" in item or "experience" in item for item in package["missing_items"])


def test_design_fonts_are_always_renderable_on_this_platform():
    """Every name returned by _register_fonts must be renderable on the
    current platform: either an actually registered TTF font or a ReportLab
    built-in standard font, so PDF export works on Windows, Linux, and
    macOS."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.pdfmetrics import standardFonts

    from utils.document_design import _register_fonts

    for name in _register_fonts():
        assert name in set(pdfmetrics.getRegisteredFontNames()) | set(standardFonts)


def test_cv_and_cover_letter_contain_no_application_system_branding_or_metadata(tmp_path):
    import pdfplumber

    prof = profile()
    job = make_job("Medical Officer", "MD required. Clinical care, HMIS reporting and supervision. Send CV to hr@example.org by 2026-12-31.")
    report = match_job_against_profile(job, prof, today=date(2026, 10, 1)).to_dict()
    bundle = prepare_application_bundle(job, prof, report, out_dir=tmp_path)
    cv_paths = bundle["generated_paths"]["tailored_cv"]
    cover_paths = bundle["generated_paths"]["cover_letter"]
    rendered = [
        Path(cv_paths["txt"]).read_text(encoding="utf-8"),
        Path(cover_paths["txt"]).read_text(encoding="utf-8"),
    ]
    for paths in [cv_paths, cover_paths]:
        with zipfile.ZipFile(paths["docx"]) as archive:
            rendered.append(archive.read("word/document.xml").decode("utf-8", errors="replace"))
        with pdfplumber.open(paths["pdf"]) as pdf:
            rendered.append("\n".join(page.extract_text() or "" for page in pdf.pages))
    forbidden = ["Jobs-Finder", "Created by", "Application generated", "matching score", "readiness", "internal job ID", "source metadata"]
    for text in rendered:
        for token in forbidden:
            assert token.lower() not in text.lower()


def test_cv_experience_is_reverse_chronological_and_substantive(tmp_path):
    prof = profile()
    prof["work_history"] = [
        {"title": "Older Medical Doctor", "organization": "Old Clinic", "location": "Kabul", "start": "2019-01", "end": "2020-12", "description": "Provided clinical consultations. Managed referrals. Completed HMIS reports.", "verified": True},
        {"title": "Current Health and Nutrition Supervisor", "organization": "Current NGO", "location": "Kabul", "start": "2021-01", "end": "Present", "description": "Supervised health and nutrition teams. Supported SAM and IMAM services. Reviewed HMIS data and monthly reports.", "verified": True},
    ]
    job = make_job("Health and Nutrition Supervisor", "MD required. Nutrition supervision, SAM/IMAM and HMIS reporting. Send CV to hr@example.org by 2026-12-31.")
    report = match_job_against_profile(job, prof, today=date(2026, 10, 1)).to_dict()
    bundle = prepare_application_bundle(job, prof, report, out_dir=tmp_path)
    cv = Path(bundle["generated_paths"]["tailored_cv"]["txt"]).read_text(encoding="utf-8")
    assert cv.index("Current NGO") < cv.index("Old Clinic")
    current_section = cv.split("Current Health and Nutrition Supervisor", 1)[1].split("Older Medical Doctor", 1)[0]
    assert current_section.count("\n-") >= 3
    assert "forty" not in cv.lower()


def test_tailored_cv_does_not_invent_non_md_qualifications(tmp_path):
    prof = profile()
    job = make_job("Pharmacist", "Medical Doctor or pharmacist accepted. Pharmacy license preferred. Send CV to hr@example.org by 2026-12-31.")
    report = match_job_against_profile(job, prof, today=date(2026, 10, 1)).to_dict()
    bundle = prepare_application_bundle(job, prof, report, out_dir=tmp_path)
    cv = Path(bundle["generated_paths"]["tailored_cv"]["txt"]).read_text(encoding="utf-8")
    assert "PharmD" not in cv
    lower_cv = cv.lower()
    assert "pharmacist" not in lower_cv.split("professional summary", 1)[1].split("\n\n", 1)[0]


def test_cover_letter_contains_no_internal_metadata(tmp_path):
    prof = profile()
    job = make_job("Medical Officer", "MD required. Clinical care and HMIS reporting. Send CV to hr@example.org by 2026-12-31.")
    report = match_job_against_profile(job, prof, today=date(2026, 10, 1)).to_dict()
    bundle = prepare_application_bundle(job, prof, report, out_dir=tmp_path)
    cover = Path(bundle["generated_paths"]["cover_letter"]["txt"]).read_text(encoding="utf-8")
    forbidden = ["Jobs-Finder", "match", "readiness", "source URL", "job_id", "profile/CV evidence", "verification warnings"]
    for token in forbidden:
        assert token.lower() not in cover.lower()
