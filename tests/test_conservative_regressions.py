"""Focused regressions for the conservative canonical-profile contract."""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

from utils.documents import prepare_application_bundle
from utils.medical_matcher import MET, NEEDS_VERIFICATION, match_job_against_profile
from utils.profile import build_profile_evidence
from utils.profile_builder import build_profile_from_cv_text
from utils.recommendations import collect_scan_recommendations

TODAY = date(2026, 10, 1)


def _profile(*, experience: object = "> 3") -> dict:
    return {
        "personal": {
            "first_name": "Test",
            "last_name": "Applicant",
            "professional_title": "Medical Doctor (MD) | Health & Nutrition Specialist",
            "email": "test.applicant@example.org",
            "phone": "+93700111222",
            "location": "Kabul, Afghanistan",
            "verification": {
                "first_name": True,
                "last_name": True,
                "professional_title": True,
                "email": True,
                "phone": True,
                "location": True,
            },
        },
        "professional_summary": {"text": "Medical Doctor with health and nutrition experience.", "verified": True},
        "medical_education": [{"degree": "Doctor of Medicine (MD)", "verified": True}],
        "license_registration": {
            "authority": "Afghan Medical Council / applicable registration authority",
            "status": "Valid medical professional registration/license",
            "verified": True,
        },
        "medical_exit_exam": {"status": "Completed", "verified": True},
        "clinical_experience": {"years": experience, "verified": True},
        "work_history": [
            {
                "title": "TFU Medical Doctor & Safeguarding Focal Point",
                "organization": "Confirmed NGO",
                "location": "Daikundi, Afghanistan",
                "bullets": [
                    "Supported TFU, SAM/MAM, IMAM/CMAM, HMIS/DHIS2 reporting, clinical audit, and quality improvement.",
                    "Supported PSEA, safeguarding, supply forecasting, and logistics.",
                ],
                "verified": True,
            },
            {
                "title": "Health and Nutrition Supervisor",
                "organization": "Confirmed NGO",
                "location": "Daikundi, Afghanistan",
                "bullets": [
                    "Supervised mobile health and nutrition teams and monitoring activities.",
                    "Supported BPHS/EPHS and coordination with MoPH and community stakeholders.",
                ],
                "verified": True,
            },
        ],
        "skills": {
            "medical": [{"name": "HMIS/DHIS2 reporting", "verified": True}],
            "public_health": [{"name": "IMAM/CMAM", "verified": True}],
        },
        "languages": [
            {"name": "Dari", "level": "Native", "verified": True},
            {"name": "English", "level": "Fluent", "verified": True},
            {"name": "Pashto", "level": "Intermediate", "verified": True},
        ],
        "preferences": {"locations": [{"name": "Kabul", "verified": True}, {"name": "Afghanistan", "verified": True}]},
    }


def _job(identifier: str, title: str, description: str) -> dict:
    return {
        "id": identifier,
        "title": title,
        "company": "Confirmed Health Organization",
        "location": "Kabul",
        "url": f"https://jobs.example.org/vacancies/{identifier}",
        "apply_url": "recruitment@example.org",
        "description": f"{description} Apply to recruitment@example.org by 2026-12-31.",
        "metadata": {
            "source_name": "ACBAR",
            "source_url": "https://jobs.example.org/source",
            "vacancy_url": f"https://jobs.example.org/vacancies/{identifier}",
        },
    }


def _requirement(report: dict, key: str) -> dict:
    return next(item for item in report["requirement_matches"] if item["key"] == key)


def test_verified_lower_bound_experience_meets_three_but_never_proves_five_years():
    profile = _profile(experience="> 3")
    evidence = build_profile_evidence(profile, today=TODAY)
    years = evidence.items["clinical_experience_years"]
    assert years[0].value == 3.0
    assert years[0].lower_bound is True

    three_year_report = match_job_against_profile(
        _job("three-years", "Medical Officer", "Medical Doctor required. At least 3 years of clinical experience required."),
        profile,
        today=TODAY,
    ).to_dict()
    assert _requirement(three_year_report, "clinical_experience_years")["status"] == MET

    five_year_report = match_job_against_profile(
        _job("five-years", "Medical Officer", "Medical Doctor required. At least 5 years of clinical experience required."),
        profile,
        today=TODAY,
    ).to_dict()
    five_years = _requirement(five_year_report, "clinical_experience_years")
    assert five_years["status"] == NEEDS_VERIFICATION
    assert "cannot prove" in five_years["explanation"]


def test_medical_council_exam_is_not_satisfied_by_medical_exit_exam():
    profile = _profile()
    council_report = match_job_against_profile(
        _job("council", "Medical Officer", "Medical Doctor required. Medical Council Exam required."),
        profile,
        today=TODAY,
    ).to_dict()
    council = _requirement(council_report, "medical_council_exam")
    assert council["status"] == NEEDS_VERIFICATION
    assert not any(item["key"] == "medical_exit_exam" for item in council_report["requirement_matches"])

    exit_report = match_job_against_profile(
        _job("exit", "Medical Officer", "Medical Doctor required. Medical Exit Exam required."),
        profile,
        today=TODAY,
    ).to_dict()
    assert _requirement(exit_report, "medical_exit_exam")["status"] == MET


def test_cv_import_is_ephemeral_and_never_mutates_the_canonical_mapping():
    canonical = _profile()
    before = copy.deepcopy(canonical)
    preview = build_profile_from_cv_text(
        "Imported Person\nMedical Doctor (MD)\nimported@example.org\n"
        "Medical Council registration and exit exam. Five years clinical experience."
    )
    assert preview["profile_status"] == "DRAFT"
    assert canonical == before
    assert all(item.verified is False for items in build_profile_evidence(preview).items.values() for item in items)


def test_three_tailored_roles_never_mutate_the_position_neutral_master_profile(tmp_path):
    profile = _profile()
    before = json.dumps(profile, sort_keys=True)
    jobs = [
        _job("clinical", "Medical Officer", "Medical Doctor required. Clinical care and HMIS reporting required."),
        _job("nutrition", "Health and Nutrition Supervisor", "Nutrition supervision, IMAM/CMAM, mobile teams, and HMIS required."),
        _job("quality", "Clinical Quality Mentor", "Clinical audit, quality improvement, case review, and MoPH coordination required."),
    ]
    generated_texts: list[str] = []
    for job in jobs:
        report = match_job_against_profile(job, profile, today=TODAY).to_dict()
        bundle = prepare_application_bundle(job, profile, report, out_dir=tmp_path / job["id"])
        generated_texts.append(Path(bundle["generated_paths"]["tailored_cv"]["txt"]).read_text(encoding="utf-8"))
        assert json.dumps(profile, sort_keys=True) == before

    assert len(set(generated_texts)) > 1
    assert json.dumps(profile, sort_keys=True) == before


def test_recommendation_collection_count_is_the_authoritative_invariant():
    compatible = _job("recommend", "Medical Officer", "Medical Doctor required.")
    generic = _job("generic", "Project Manager", "Manage a health project budget and donor reporting.")
    pairs = [
        (compatible, {"readiness_status": "READY_TO_APPLY"}),
        (generic, {"readiness_status": "NEEDS_VERIFICATION"}),
    ]
    recommendations = collect_scan_recommendations(pairs)
    assert len(recommendations) == 1
    assert recommendations[0]["id"] == "recommend"
