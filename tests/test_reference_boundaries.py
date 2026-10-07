"""References are private metadata, not applicant evidence or default CV text."""

from __future__ import annotations

import json

from utils.documents import (
    generate_application_package,
    generate_master_cv,
    generate_tailored_documents,
)
from utils.medical_matcher import match_job_against_profile
from utils.profile import build_profile_evidence

PROFILE_WITH_PRIVATE_REFERENCES = {
    "personal": {
        "first_name": "Reference",
        "last_name": "Boundary",
        "professional_title": "Medical Doctor",
        "email": "candidate@example.test",
        "phone": "+93 700 111 222",
        "location": "Kabul",
        "verification": {
            "first_name": True,
            "last_name": True,
            "professional_title": True,
            "email": True,
            "phone": True,
            "location": True,
        },
    },
    "medical_education": [{"degree": "Doctor of Medicine (MD)", "verified": True}],
    "license_registration": {"status": "Valid medical professional registration/license", "verified": True},
    "medical_exit_exam": {"status": "Completed", "verified": True},
    "clinical_experience": {"years": "> 3", "verified": True},
    "work_history": [{"title": "Medical Doctor", "organization": "Health Organization", "bullets": ["Provided clinical care and HMIS reporting."], "verified": True}],
    "skills": {"medical": [{"name": "Clinical care", "verified": True}]},
    "languages": [{"name": "English", "level": "Fluent", "verified": True}],
    "professional_references": {
        "entries": [
            {"name": "Reference Person", "role": "Former Supervisor", "phone": "+93 700 999 111", "email": "reference.person@example.test", "verified": True},
        ],
        "count": 1,
        "verified": True,
    },
}


JOB_REQUIRING_REFERENCES = {
    "id": "references-required",
    "title": "Medical Doctor",
    "company": "Health Organization",
    "location": "Afghanistan",
    "url": "https://jobs.example.org/references-required",
    "apply_url": "recruitment@example.org",
    "description": "Medical Doctor required. Valid medical registration and three professional references are required. Apply to recruitment@example.org by 2026-12-31.",
    "metadata": {"source_name": "ACBAR", "source_url": "https://jobs.example.org", "vacancy_url": "https://jobs.example.org/references-required"},
}


def test_private_references_are_excluded_from_evidence_and_default_documents():
    evidence = build_profile_evidence(PROFILE_WITH_PRIVATE_REFERENCES)
    master = generate_master_cv(PROFILE_WITH_PRIVATE_REFERENCES)
    report = match_job_against_profile(JOB_REQUIRING_REFERENCES, PROFILE_WITH_PRIVATE_REFERENCES).to_dict()
    tailored = generate_tailored_documents(JOB_REQUIRING_REFERENCES, PROFILE_WITH_PRIVATE_REFERENCES, report)
    package = generate_application_package(JOB_REQUIRING_REFERENCES, PROFILE_WITH_PRIVATE_REFERENCES, report, tailored)

    private_tokens = ["Reference Person", "Former Supervisor", "+93 700 999 111", "reference.person@example.test"]
    for rendered in [
        json.dumps(evidence.to_dict()),
        master["master_cv_text"],
        tailored["tailored_cv_text"],
        tailored["cover_letter"],
        json.dumps(package),
    ]:
        for token in private_tokens:
            assert token not in rendered

    # A reference requirement can surface a generic manual checklist item, but
    # the system never releases contact metadata automatically.
    checklist = package["required_documents_checklist"] + package["form_fields_checklist"] + package["user_required_actions"]
    assert any("reference" in item.lower() for item in checklist)
