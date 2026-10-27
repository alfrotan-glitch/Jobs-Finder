"""Regression coverage for clean, employer-facing optional CV sections."""

from __future__ import annotations

from copy import deepcopy

from tests.test_cv_professional_quality import TODAY, _nutrition_job, _profile
from utils.documents import generate_master_cv, generate_tailored_documents
from utils.medical_matcher import match_job_against_profile


def test_references_are_omitted_by_default_in_master_and_tailored_cv():
    profile = deepcopy(_profile())
    profile.pop("document_preferences", None)
    master = generate_master_cv(profile)
    job = _nutrition_job()
    report = match_job_against_profile(job, profile, today=TODAY).to_dict()
    tailored = generate_tailored_documents(job, profile, report)

    for model, text in (
        (master["master_cv_model"], master["master_cv_text"]),
        (tailored["tailored_cv_model"], tailored["tailored_cv_text"]),
    ):
        assert model["references"] == []
        assert "\nREFERENCES\n" not in text
        assert "Available on request for shortlisted applications" not in text


def test_references_can_be_opted_in_without_leaking_referees():
    profile = deepcopy(_profile())
    profile["document_preferences"] = {"cv_references": "upon_request"}
    profile["professional_references"] = {
        "entries": [{"name": "PRIVATE PERSON", "phone": "PRIVATE NUMBER"}]
    }
    master = generate_master_cv(profile)

    assert master["master_cv_model"]["references"] == ["References available upon request."]
    assert "REFERENCES" in master["master_cv_text"]
    assert "References available upon request." in master["master_cv_text"]
    assert "PRIVATE PERSON" not in master["master_cv_text"]
    assert "PRIVATE NUMBER" not in master["master_cv_text"]


def test_incomplete_credential_statuses_disappear_from_all_cv_models():
    profile = deepcopy(_profile())
    profile["license_registration"] = {"status": "To be completed", "verified": True}
    profile["medical_exit_exam"] = {"status": "To be completed", "verified": True}
    profile["professional_summary"] = {"text": "", "verified": False}
    master = generate_master_cv(profile)
    job = _nutrition_job()
    report = match_job_against_profile(job, profile, today=TODAY).to_dict()
    tailored = generate_tailored_documents(job, profile, report)

    for model, text in (
        (master["master_cv_model"], master["master_cv_text"]),
        (tailored["tailored_cv_model"], tailored["tailored_cv_text"]),
    ):
        assert model["registration"] == []
        assert model["exit_exam"] == []
        assert "\nPROFESSIONAL REGISTRATION\n" not in text
        assert "\nMEDICAL EXIT EXAMINATION\n" not in text
        assert "To be completed" not in text


def test_verified_license_status_can_appear_without_optional_numbers_or_dates():
    profile = deepcopy(_profile())
    profile["license_registration"] = {
        "status": "Registered", "authority": "Example Medical Council",
        "number": "", "issue_date": "", "expiry_date": "", "verified": True,
    }
    master = generate_master_cv(profile)
    text = master["master_cv_text"]
    assert master["master_cv_model"]["registration"] == [
        "Registered with Example Medical Council"
    ]
    assert "Not supplied" not in text
    assert "To be completed" not in text
    assert "License number" not in text


def test_official_generic_license_statement_is_omitted_from_employer_cvs():
    profile = deepcopy(_profile())
    profile["license_registration"] = {
        "status": "Valid medical professional registration/license",
        "authority": "", "number": "", "verified": True,
    }
    job = _nutrition_job()
    report = match_job_against_profile(job, profile, today=TODAY).to_dict()
    for model, text in (
        (generate_master_cv(profile)["master_cv_model"], generate_master_cv(profile)["master_cv_text"]),
        (generate_tailored_documents(job, profile, report)["tailored_cv_model"],
         generate_tailored_documents(job, profile, report)["tailored_cv_text"]),
    ):
        assert model["registration"] == []
        assert "Valid medical professional registration/license" not in text
        assert "\\nPROFESSIONAL REGISTRATION\\n" not in text


def test_polio_vacancy_selects_verified_transferable_public_health_work():
    profile = deepcopy(_profile())
    profile["document_preferences"]["cv_depth"] = "focused"
    job = {"title": "Provincial Polio Officer", "company": "Example NGO",
           "description": "Provincial monitoring, coordination with health authorities, field supervision, reporting, community mobilization."}
    model = generate_tailored_documents(job, profile, {"facts": {}})["tailored_cv_model"]
    assert model["full_verified_duty_count"] == 24
    assert 12 <= model["selected_duty_count"] <= 20
    assert len(model["experience"]) == 5
    assert all(len(row["bullets"]) >= 2 for row in model["experience"])
    assert "polio campaign" not in " ".join(b for row in model["experience"] for b in row["bullets"]).lower()
    assert "Provincial Polio Officer" in model["application_focus"]
    assert model["registration"] == []


def test_polio_cv_renders_compact_searchable_pdf_without_trailing_page(tmp_path):
    import pdfplumber

    from utils.document_design import render_cv_pdf

    profile = deepcopy(_profile())
    profile["document_preferences"]["cv_depth"] = "focused"
    job = {
        "title": "Provincial Polio Officer",
        "company": "Example NGO",
        "description": "Coordinate provincial public health and surveillance reporting, supervise field activities and maintain data quality.",
    }
    result = generate_tailored_documents(job, profile, {"facts": {}})
    path = tmp_path / "polio_officer_cv.pdf"
    render_cv_pdf(result["tailored_cv_model"], path)
    with pdfplumber.open(path) as pdf:
        assert len(pdf.pages) <= 2
        assert all((page.extract_text() or "").strip() for page in pdf.pages)
        text = " ".join(page.extract_text() or "" for page in pdf.pages)
        assert "Provincial Polio Officer" in text
        assert "Valid medical professional registration/license" not in text
        assert "To be completed" not in text
