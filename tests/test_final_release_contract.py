"""Adversarial final-release contract for the real Jobs-Finder profile.

These tests deliberately exercise the shipped Dr. Allah Yar Frotan profile and
boundary conditions that a green happy-path suite can otherwise miss.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from utils.documents import (
    generate_application_package,
    generate_master_cv,
    prepare_application_bundle,
)
from utils.medical_matcher import (
    NEEDS_VERIFICATION_STATUS,
    NOT_ELIGIBLE_STATUS,
    READY_TO_APPLY,
    match_job_against_profile,
)
from utils.medical_requirements import (
    analyze_professional_role,
    application_subject_required,
    canonical_source_fields,
)
from utils.private_references import (
    PrivateReferenceError,
    load_approved_private_references,
)
from utils.profile import (
    KNOWN_BUT_NON_PRECISE,
    NOT_PROVIDED,
    VERIFIED,
    assert_canonical_profile_complete,
    canonical_profile_fingerprint,
    load_canonical_profile,
)

TODAY = date(2026, 10, 1)


def _job(*, title: str = "Medical Doctor", description: str = "Medical Doctor (MD) required. Valid medical registration, Medical Exit Exam, 3 years of clinical experience, and fluent English required. Apply to recruitment@example.org by 2026-12-31.", source_url: str = "https://official.example/jobs", vacancy_url: str = "https://official.example/jobs/medical-doctor", apply_url: str = "recruitment@example.org", method: str = "EMAIL") -> dict:
    return {
        "id": "release-contract-job",
        "title": title,
        "company": "Verified Health Organization",
        "location": "Kabul",
        "url": vacancy_url,
        "apply_url": apply_url,
        "application_method": method,
        "description": description,
        "metadata": {
            "source_name": "ACBAR",
            "source_url": source_url,
            "vacancy_url": vacancy_url,
            "application_method": method,
        },
    }


def test_real_canonical_profile_is_complete_without_forcing_unsupported_precision():
    report = assert_canonical_profile_complete()
    statuses = {item["key"]: item["status"] for item in report["checks"]}
    assert report["release_ready"] is True
    assert statuses["identity"] == VERIFIED
    assert statuses["clinical_experience_lower_bound"] == KNOWN_BUT_NON_PRECISE
    assert statuses["acf_dates_non_precise"] == KNOWN_BUT_NON_PRECISE
    for key in ["license_number", "license_issue_date", "license_expiry_date", "license_document_path"]:
        assert statuses[key] == NOT_PROVIDED


def test_tracked_profile_has_no_reference_contact_pii_or_embedded_reference_store():
    profile_path = Path("profile.yaml")
    profile = load_canonical_profile(required=True)
    text = profile_path.read_text(encoding="utf-8")
    # The tracked profile exposes no reference-entry field. This proves the
    # public release does not carry contact records; actual supplied contacts
    # remain outside the repository and are not duplicated into tests either.
    assert "professional_references" not in text
    assert "professional_references" not in profile
    boundary = profile["private_reference_boundary"]
    assert boundary["release_requires_owner_approval"] is True
    assert boundary["external_private_store_required"] is True
    assert boundary["runtime_release_default"] == "NOT_RELEASED"


@pytest.mark.parametrize(
    ("source_url", "vacancy_url", "apply_url", "method", "expected_source", "expected_method", "actionable"),
    [
        ("https://official.example/listing", "https://official.example/vacancy", "apply@example.org", "EMAIL", "https://official.example/listing", "EMAIL", True),
        ("https://official.example/listing", "https://official.example/vacancy", "https://forms.example/apply/123", "WEB", "https://official.example/listing", "WEB", True),
        ("", "https://official.example/vacancy", "apply@example.org", "EMAIL", "", "EMAIL", False),
        ("https://official.example/listing", "https://official.example/vacancy", "", "UNAVAILABLE", "https://official.example/listing", "UNAVAILABLE", True),
    ],
)
def test_source_provenance_and_application_routes_are_independent(source_url, vacancy_url, apply_url, method, expected_source, expected_method, actionable):
    source = canonical_source_fields(_job(source_url=source_url, vacancy_url=vacancy_url, apply_url=apply_url, method=method))
    assert source["source_url"] == expected_source
    assert source["vacancy_url"] == vacancy_url
    assert source["application_method"] == expected_method
    assert source["is_actionable"] is actionable
    assert source["direct_application_route_actionable"] is (bool(source_url) and bool(apply_url))
    if not source_url:
        assert source["source_url"] != vacancy_url
        assert "missing_or_invalid_source_url" in source["problems"]


def test_vacancy_page_without_direct_route_cannot_be_ready_to_apply():
    profile = load_canonical_profile(required=True)
    job = _job(
        apply_url="",
        method="UNAVAILABLE",
        description="Medical Doctor (MD) required. Valid medical registration and Medical Exit Exam required. Closing date: 2026-12-31.",
    )
    report = match_job_against_profile(job, profile, today=TODAY).to_dict()
    route = next(item for item in report["requirement_matches"] if item["key"] == "application_destination")
    assert route["status"] == "Needs verification"
    assert report["readiness_status"] == NEEDS_VERIFICATION_STATUS


@pytest.mark.parametrize(
    "text",
    [
        "The employee will be subject to organizational policies.",
        "All personnel are subject to the safeguarding policy and code of conduct.",
        "This subject is covered during orientation.",
    ],
)
def test_subject_policy_language_is_not_misclassified_as_email_instruction(text):
    assert application_subject_required(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "Use the vacancy reference number in the email subject line.",
        "Please write the job title in the subject of your email.",
        "در عنوان ایمیل کد بست را درج نمایید.",
    ],
)
def test_real_subject_instructions_are_detected(text):
    assert application_subject_required(text) is True


@pytest.mark.parametrize(
    ("title", "description", "classification"),
    [
        ("Medical Doctor (MD)", "MD degree and medical registration required.", "md_physician_role"),
        ("Physician", "Medical degree and licence required.", "md_physician_role"),
        ("Medical Officer", "MBBS required.", "md_physician_role"),
        ("Health & Nutrition Supervisor", "Supervise IMAM and HMIS activities.", "health_public_health_compatible"),
        ("Nutrition Officer", "Nutrition and CMAM responsibilities.", "health_public_health_compatible"),
        ("Public Health Officer", "Public health and HMIS responsibilities.", "health_public_health_compatible"),
        ("Medical Coordinator", "Coordinate clinical services and MoPH liaison.", "health_public_health_compatible"),
        ("Health Project Manager", "Manage health programme delivery and HMIS.", "health_public_health_compatible"),
        ("TFU MHPSS Counsellor", "Psychology degree and counselling diploma required.", "incompatible_professional_role"),
        ("Pharmacist", "Pharmacy degree and pharmacy licence required.", "incompatible_professional_role"),
        ("Staff Nurse", "Nursing diploma and nursing licence required.", "incompatible_professional_role"),
        ("Midwife", "Midwifery diploma and registration required.", "incompatible_professional_role"),
        ("Finance Officer", "Accounting and finance duties.", "not_medical_or_public_health"),
        ("M&E Officer", "Monitoring and evaluation duties.", "not_medical_or_public_health"),
        ("Project Manager", "Manage a health project budget and donor reporting.", "not_medical_or_public_health"),
    ],
)
def test_professional_role_matrix(title, description, classification):
    assert analyze_professional_role(title, description)["classification"] == classification


@pytest.mark.parametrize("title", ["Pediatrician", "General Surgeon", "Specialist Physician"])
def test_specialist_roles_do_not_treat_general_md_as_specialist_qualification(title):
    profile = load_canonical_profile(required=True)
    role = analyze_professional_role(title, "Specialist licence and specialty qualification required.")
    assert role["classification"] == "specialist_qualification_required"
    report = match_job_against_profile(
        _job(
            title=title,
            description=f"{title} with specialist qualification and licence required. Apply to recruitment@example.org by 2026-12-31.",
        ),
        profile,
        today=TODAY,
    ).to_dict()
    assert report["readiness_status"] == NEEDS_VERIFICATION_STATUS
    assert next(item for item in report["requirement_matches"] if item["key"] == "role_family_compatibility")["status"] == "Needs verification"


def test_health_nutrition_lower_bound_is_used_for_that_dimension_not_public_health_years():
    profile = load_canonical_profile(required=True)
    health_nutrition = match_job_against_profile(
        _job(
            title="Health & Nutrition Supervisor",
            description="Health & Nutrition Supervisor role. At least 3 years of health and nutrition experience. Apply to recruitment@example.org by 2026-12-31.",
        ),
        profile,
        today=TODAY,
    ).to_dict()
    hn = next(item for item in health_nutrition["requirement_matches"] if item["key"] == "health_nutrition_experience_years")
    assert hn["status"] == "Met"

    public_health = match_job_against_profile(
        _job(
            title="Public Health Officer",
            description="Public Health Officer role. At least 3 years of public health experience. Apply to recruitment@example.org by 2026-12-31.",
        ),
        profile,
        today=TODAY,
    ).to_dict()
    ph = next(item for item in public_health["requirement_matches"] if item["key"] == "public_health_experience_years")
    assert ph["status"] == "Needs verification"


def test_missing_deadline_blocks_ready_state_instead_of_assuming_open():
    profile = load_canonical_profile(required=True)
    report = match_job_against_profile(
        _job(description="Medical Doctor (MD) required. Valid medical registration and Medical Exit Exam required. Apply to recruitment@example.org."),
        profile,
        today=TODAY,
    ).to_dict()
    deadline = next(item for item in report["requirement_matches"] if item["key"] == "closing_date")
    assert deadline["status"] == "Needs verification"
    assert report["readiness_status"] == NEEDS_VERIFICATION_STATUS


def test_real_profile_end_to_end_acceptance_is_truthful_and_immutable(tmp_path):
    profile = load_canonical_profile(required=True)
    canonical_before = canonical_profile_fingerprint(profile)
    master_before = generate_master_cv(profile)
    master_text = master_before["master_cv_text"]
    job = _job(
        title="Nutrition Officer",
        description=(
            "Nutrition Officer. Doctor of Medicine (MD), valid medical registration, Medical Exit Exam, "
            "at least 3 years of health and nutrition experience, HMIS, IMAM/CMAM, and fluent English required. "
            "Apply to recruitment@example.org by 2026-12-31."
        ),
    )
    report = match_job_against_profile(job, profile, today=TODAY).to_dict()
    assert report["readiness_status"] == READY_TO_APPLY
    bundle = prepare_application_bundle(job, profile, report, out_dir=tmp_path / "package")
    assert bundle["application_package"]["package_status"] == "READY_FOR_REVIEW"
    assert canonical_profile_fingerprint(profile) == canonical_before
    assert generate_master_cv(profile)["master_cv_text"] == master_text

    rendered = "\n".join(
        [
            master_text,
            Path(bundle["generated_paths"]["tailored_cv"]["txt"]).read_text(encoding="utf-8"),
            Path(bundle["generated_paths"]["cover_letter"]["txt"]).read_text(encoding="utf-8"),
            json.dumps(bundle["application_package"], ensure_ascii=False),
        ]
    )
    assert "Dr. Allah Yar Frotan" in rendered
    assert "Nutrition Officer" not in master_text  # neutral master CV has no target vacancy title
    sample_fixture_name = "Jane" + " " + "Doe"
    # Real supplied referee contacts are intentionally not copied into the
    # repository or its tests. Generic reference/sample values must not leak
    # into the generated public artifacts either.
    for forbidden in ["reference.person@example", sample_fixture_name]:
        assert forbidden not in rendered


def test_blocked_package_never_reports_review_ready():
    profile = load_canonical_profile(required=True)
    report = {"readiness_status": NOT_ELIGIBLE_STATUS}
    package = generate_application_package(_job(title="Pharmacist"), profile, report)
    assert package["package_status"] == "BLOCKED"
    assert package["email_draft"] is None
    assert package["no_submission_performed"] is True


def test_private_reference_loader_requires_vacancy_and_owner_approval(monkeypatch, tmp_path):
    with pytest.raises(PrivateReferenceError):
        load_approved_private_references(vacancy_requires_references=False, owner_approved=True)
    with pytest.raises(PrivateReferenceError):
        load_approved_private_references(vacancy_requires_references=True, owner_approved=False)

    store = tmp_path / "private-references.yaml"
    store.write_text("entries:\n  - name: Approved Referee\n    role: Supervisor\n    phone: '+93 700 000 001'\n    email: referee@example.test\n", encoding="utf-8")
    monkeypatch.setenv("JOBS_FINDER_PRIVATE_REFERENCES_PATH", str(store))
    assert load_approved_private_references(vacancy_requires_references=True, owner_approved=True) == [
        {"name": "Approved Referee", "role": "Supervisor", "phone": "+93 700 000 001", "email": "referee@example.test"}
    ]
