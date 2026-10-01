import json
import zipfile
from pathlib import Path
from datetime import date

import pytest

from utils.documents import prepare_application_bundle
from utils.medical_matcher import NOT_ELIGIBLE_STATUS, match_job_against_profile


def profile():
    return {
        "personal": {"first_name": "Allah Yar", "last_name": "Frotan", "email": "alfrotan@gmail.com", "phone": "+93766462006", "location": "Kabul", "gender": "male", "nationality": "Afghan"},
        "medical_education": [{"degree": "MD", "verified": True}],
        "license_registration": {"status": "Valid medical professional registration/license", "verified": True},
        "medical_exit_exam": {"status": "Completed", "verified": True},
        "clinical_experience": {"years": 4, "settings": ["clinic", "hospital"]},
        "skills": {"medical": ["Clinical care", "Patient assessment"], "public_health": ["Nutrition", "TSFP", "HMIS"], "management": ["Supervision", "Reporting"]},
        "work_history": [
            {"title": "Medical Doctor", "organization": "Verified Clinic", "location": "Kabul", "start": "2022-01", "end": "Present", "description": "Clinical consultations, patient assessment, diagnosis, treatment, referral and HMIS reporting."},
            {"title": "Health and Nutrition Supervisor", "organization": "Verified NGO", "location": "Afghanistan", "start": "2020-01", "end": "2021-12", "description": "Nutrition screening, TSFP coordination, supervision, reporting and team mentoring."},
        ],
        "languages": [{"name": "Dari", "level": "Native"}, {"name": "Pashto", "level": "Fluent"}, {"name": "English", "level": "Professional"}],
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
    prof["clinical_experience"] = {"years": ""}
    prof["work_history"] = []
    job = make_job("Medical Doctor", "MD required. 3 years clinical experience. Send CV to hr@example.org by 2026-12-31.")
    report = match_job_against_profile(job, prof, today=date(2026, 10, 1)).to_dict()
    bundle = prepare_application_bundle(job, prof, report, out_dir=tmp_path)
    package_json = Path(bundle["generated_paths"]["application_package_json"])
    package = json.loads(package_json.read_text(encoding="utf-8"))

    assert package["missing_items"]
    assert any("Clinical" in item or "experience" in item for item in package["missing_items"])
