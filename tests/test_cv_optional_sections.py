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
        "Registered (Example Medical Council)"
    ]
    assert "Not supplied" not in text
    assert "To be completed" not in text
    assert "License number" not in text
