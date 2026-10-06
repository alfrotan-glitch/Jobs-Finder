"""Position-neutral master-CV and downstream-tailoring invariants.

These tests use an isolated synthetic canonical profile. They prove that a
vacancy can influence only a generated output, never the canonical YAML record
or its neutral master-CV presentation.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from utils import profile as profile_repository
from utils.documents import prepare_application_bundle, write_master_cv
from utils.medical_matcher import match_job_against_profile
from utils.profile import (
    canonical_profile_fingerprint,
    load_canonical_profile,
    save_canonical_profile,
)

POSITION_NEUTRAL_PROFILE = {
    "personal": {
        "first_name": "Audited",
        "last_name": "Applicant",
        "professional_title": "Medical Doctor (MD) | Health & Nutrition Specialist",
        "email": "applicant@local.invalid",
        "phone": "+93 700 111 222",
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
    "professional_summary": {
        "text": "Medical Doctor and Health & Nutrition Specialist with experience in clinical care, programme implementation, supervision, reporting, and coordination.",
        "verified": True,
    },
    "medical_education": [{"degree": "Doctor of Medicine (MD)", "field": "Curative Medicine", "institution": "Medical University", "start": "2013", "end": "2020", "verified": True}],
    "license_registration": {"status": "Valid medical professional registration/license", "verified": True},
    "medical_exit_exam": {"status": "Completed", "verified": True},
    "clinical_experience": {"years": "> 3", "verified": True},
    "work_history": [
        {
            "title": "Health and Nutrition Supervisor",
            "organization": "Health NGO",
            "location": "Afghanistan",
            "bullets": ["Supervised health and nutrition services.", "Supported IMAM/CMAM and HMIS reporting.", "Coordinated with health stakeholders."],
            "verified": True,
        },
        {
            "title": "Medical Doctor",
            "organization": "Public Health Directorate",
            "start": "2020-10",
            "end": "2020-12",
            "bullets": ["Provided clinical care and supported COVID-19 response."],
            "verified": True,
        },
    ],
    "skills": {
        "medical": [{"name": "Clinical care", "verified": True}, {"name": "IMAM / CMAM", "verified": True}],
        "public_health": [{"name": "HMIS / DHIS2 and reporting", "verified": True}, {"name": "Health and nutrition programme implementation", "verified": True}],
        "management": [{"name": "Team supervision and stakeholder coordination", "verified": True}],
    },
    "certificates": [{"name": "Safeguarding & PSEA training", "verified": True}],
    "languages": [{"name": "Dari", "level": "Native", "verified": True}, {"name": "English", "level": "Fluent", "verified": True}],
}


VACANCIES = [
    {
        "id": "provincial-coordinator",
        "title": "Provincial Coordinator",
        "company": "Health Organization",
        "location": "Afghanistan",
        "url": "https://jobs.example.org/provincial-coordinator",
        "apply_url": "recruitment@example.org",
        "description": "Medical Doctor accepted. Health programme coordination, supervision, stakeholder liaison, HMIS reporting and medical registration required. Apply to recruitment@example.org by 2026-12-31.",
        "metadata": {"source_name": "ACBAR", "source_url": "https://jobs.example.org", "vacancy_url": "https://jobs.example.org/provincial-coordinator"},
    },
    {
        "id": "medical-officer",
        "title": "Medical Officer",
        "company": "Health Organization",
        "location": "Afghanistan",
        "url": "https://jobs.example.org/medical-officer",
        "apply_url": "recruitment@example.org",
        "description": "Medical Doctor required. Clinical care, patient assessment, treatment, medical registration and Medical Exit Exam required. Apply to recruitment@example.org by 2026-12-31.",
        "metadata": {"source_name": "ACBAR", "source_url": "https://jobs.example.org", "vacancy_url": "https://jobs.example.org/medical-officer"},
    },
    {
        "id": "nutrition-officer",
        "title": "Nutrition Officer",
        "company": "Health Organization",
        "location": "Afghanistan",
        "url": "https://jobs.example.org/nutrition-officer",
        "apply_url": "recruitment@example.org",
        "description": "Medical Doctor accepted. Nutrition programme implementation, IMAM/CMAM, SAM, supervision and HMIS reporting required. Apply to recruitment@example.org by 2026-12-31.",
        "metadata": {"source_name": "ACBAR", "source_url": "https://jobs.example.org", "vacancy_url": "https://jobs.example.org/nutrition-officer"},
    },
]


def test_neutral_master_and_three_vacancy_outputs_never_mutate_canonical_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_repository, "CANONICAL_PROFILE_PATH", tmp_path / "profile.yaml")
    save_canonical_profile(POSITION_NEUTRAL_PROFILE)
    canonical_path = profile_repository.canonical_profile_path()
    before_bytes = canonical_path.read_bytes()
    before_fingerprint = canonical_profile_fingerprint()

    master = write_master_cv(load_canonical_profile(required=True), out_dir=tmp_path / "master")
    master_text = Path(master["generated_paths"]["txt"]).read_text(encoding="utf-8")
    assert master["position_neutral"] is True
    assert "Provincial Coordinator" not in master_text
    assert "Medical Officer" not in master_text
    assert "Nutrition Officer" not in master_text
    assert "Health and Nutrition Supervisor" in master_text

    output_paths: list[Path] = []
    output_texts: list[str] = []
    for vacancy in VACANCIES:
        current = load_canonical_profile(required=True)
        report = match_job_against_profile(vacancy, current, today=date(2026, 10, 1)).to_dict()
        bundle = prepare_application_bundle(vacancy, current, report, out_dir=tmp_path / vacancy["id"])
        cv_path = Path(bundle["generated_paths"]["tailored_cv"]["txt"])
        output_paths.append(cv_path)
        output_texts.append(cv_path.read_text(encoding="utf-8"))

        # The actual persisted canonical YAML—not just the in-memory mapping—
        # must remain byte-identical after each downstream tailoring run.
        assert canonical_path.read_bytes() == before_bytes
        assert canonical_profile_fingerprint() == before_fingerprint

    assert len(set(output_paths)) == len(VACANCIES)
    assert all(path.is_file() for path in output_paths)
    assert len(set(output_texts)) == len(VACANCIES)

    canonical_text = canonical_path.read_text(encoding="utf-8")
    for vacancy in VACANCIES:
        assert vacancy["title"] not in canonical_text
    assert yaml.safe_load(canonical_text) == POSITION_NEUTRAL_PROFILE
