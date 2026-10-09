"""Regression tests for the final cover-letter refinements.

1. The Medical Doctor letter's subject carries the vacancy reference the posting
   asks for, and does not repeat the job title that the heading already states.
2. The Health & Nutrition Supervisor letter's opening leads with the applicant's
   verified supervision, health/nutrition, BPHS/EPHS, supply and coordination
   experience, and the medical identity follows. The Medical Doctor letter keeps
   its established opening.
3. Evidence bullets are verified profile lines, stripped of attribution. They
   carry no parentheses, pipes, or dates, so they read without redundant
   role/employer/date text.
"""

from __future__ import annotations

import re
from pathlib import Path

from utils import discovery
from utils.documents import (
    _profile_evidence_lines,
    _without_attribution,
    generate_tailored_documents,
)
from utils.medical_matcher import match_job_against_profile
from utils.profile import load_canonical_profile

FIXTURES = Path(__file__).parent / "fixtures" / "discovery"

HN_TEXT = (
    "Health & Nutrition Supervisor required. Mobile health and nutrition teams; "
    "community-based BPHS/EPHS; IMAM/CMAM; SAM and TFU; team supervision and "
    "capacity building; HMIS/DHIS2 reporting; medical supply forecasting. "
    "Apply to recruitment@example.org by 2026-12-31."
)


def _acbar_medical_doctor() -> dict:
    listing = discovery._parse_acbar_listing(
        (FIXTURES / "acbar_listing.html").read_text(encoding="utf-8"),
        "https://www.acbar.org/en/jobs?page=2",
    )
    summary = next(job for job in listing if job.title == "Medical Doctor (MD)")
    return discovery._parse_acbar_detail(
        (FIXTURES / "acbar_detail.html").read_text(encoding="utf-8"), summary
    ).to_dict()


def _constructed_health_nutrition() -> dict:
    return {
        "id": "review-health-nutrition-supervisor",
        "title": "Health & Nutrition Supervisor",
        "company": "Example Employer",
        "location": "Kabul, Afghanistan",
        "url": "https://example.org/review/health-nutrition-supervisor",
        "description": HN_TEXT,
        "metadata": {},
    }


def _documents(job: dict) -> dict:
    profile = load_canonical_profile(required=True)
    report = match_job_against_profile(job, profile).to_dict()
    return generate_tailored_documents(job, profile, report)


def _letter_lines(job: dict) -> list[str]:
    return _documents(job)["cover_letter"].splitlines()


def _bullets(lines: list[str]) -> list[str]:
    return [line[2:].strip() for line in lines if line.startswith("- ")]


# 1. Subject: the vacancy reference only, no repeated job title.


def test_medical_doctor_subject_is_the_vacancy_reference_only():
    subject_line = _letter_lines(_acbar_medical_doctor())[0]
    assert subject_line == "Subject: HNTPO-MD-1012026"


def test_medical_doctor_subject_does_not_repeat_the_job_title():
    subject_line = _letter_lines(_acbar_medical_doctor())[0]
    assert "Medical Doctor" not in subject_line
    assert "—" not in subject_line


def test_suggested_subject_is_the_reference_when_no_subject_is_requested():
    documents = _documents(_acbar_medical_doctor())
    assert documents["suggested_subject"] == "HNTPO-MD-1012026"


# 2. Opening paragraph.


def _opening_paragraph(lines: list[str]) -> str:
    # Body order: "Dear ...", blank, "I am writing to apply ...", blank, opening paragraph.
    writing = next(index for index, line in enumerate(lines) if line.startswith("I am writing to apply"))
    return lines[writing + 2]


def test_health_nutrition_opening_leads_with_verified_supervision_experience():
    paragraph = _opening_paragraph(_letter_lines(_constructed_health_nutrition()))
    assert paragraph.startswith("I bring more than three years of combined supervisory,"), paragraph


def test_health_nutrition_opening_orders_the_verified_clauses_before_the_identity():
    paragraph = _opening_paragraph(_letter_lines(_constructed_health_nutrition()))
    order = [
        "team supervision and capacity building",
        "health and nutrition service delivery",
        "BPHS/EPHS-related service delivery",
        "medical supply forecasting and logistics",
        "MoPH and health-authority coordination",
    ]
    positions = [paragraph.index(clause) for clause in order]
    assert positions == sorted(positions), positions
    assert paragraph.index("I am a Medical Doctor (MD)") > positions[-1]


def test_medical_doctor_opening_keeps_its_established_identity_lead():
    paragraph = _opening_paragraph(_letter_lines(_acbar_medical_doctor()))
    assert paragraph.startswith("I am a Medical Doctor (MD) qualified in Curative Medicine")


def test_health_nutrition_opening_uses_only_verified_clause_keys(monkeypatch):
    # Every clause in the supervisory opening is gated on verified evidence. With
    # supervision evidence removed, its clause must disappear, not be asserted.
    from utils import documents
    from utils.profile import build_profile_evidence

    profile = load_canonical_profile(required=True)
    evidence = build_profile_evidence(profile)
    assert evidence.has_verified("supervision_management")
    clauses = documents._supervisory_lead_clauses(evidence)
    assert "team supervision and capacity building" in clauses

    class _NoSupervision:
        def has_verified(self, key):
            return key != "supervision_management" and evidence.has_verified(key)

    assert "team supervision and capacity building" not in documents._supervisory_lead_clauses(_NoSupervision())


# 3. Evidence bullets.


def test_evidence_bullets_are_verified_profile_lines_without_attribution():
    profile = load_canonical_profile(required=True)
    verified_lines = {_without_attribution(line) for line in _profile_evidence_lines(profile)}
    for job in (_acbar_medical_doctor(), _constructed_health_nutrition()):
        bullets = _bullets(_letter_lines(job))
        assert bullets, job["title"]
        for bullet in bullets:
            assert bullet in verified_lines, (job["title"], bullet)


def test_evidence_bullets_carry_no_parentheses_pipes_or_dates():
    for job in (_acbar_medical_doctor(), _constructed_health_nutrition()):
        for bullet in _bullets(_letter_lines(job)):
            assert "(" not in bullet and ")" not in bullet, bullet
            assert "|" not in bullet, bullet
            assert not re.search(r"\b(?:19|20)\d{2}\b", bullet), bullet


# 4. Email-subject requirement, subject consistency, and heading duplication.


def _prepared_bundle(job: dict, tmp_path) -> dict:
    from utils.documents import prepare_application_bundle

    profile = load_canonical_profile(required=True)
    report = match_job_against_profile(job, profile).to_dict()
    return prepare_application_bundle(job, profile, report, out_dir=tmp_path)


def test_posting_asking_for_vacancy_number_in_subject_is_a_subject_requirement():
    from utils.medical_requirements import (
        application_subject_required,
        extract_application_subject,
    )

    text = "Send CV with vacancy number in the subject line to recruitment@example.org."
    assert application_subject_required(text) is True
    assert extract_application_subject(f"Vacancy Number: HNTPO-MD-1012026. {text}") == "HNTPO-MD-1012026"


def test_plain_application_route_is_not_a_subject_requirement():
    from utils.medical_requirements import application_subject_required

    assert application_subject_required("Send your CV to recruitment@example.org by 2026-10-10.") is False


def test_medical_doctor_email_subject_is_the_vacancy_number(tmp_path):
    draft = _prepared_bundle(_acbar_medical_doctor(), tmp_path)["application_package"]["email_draft"]
    assert draft["subject"] == "HNTPO-MD-1012026"


def test_letter_subject_and_email_subject_are_identical(tmp_path):
    for job in (_acbar_medical_doctor(), _constructed_health_nutrition()):
        bundle = _prepared_bundle(job, tmp_path)
        letter_subject = _letter_lines(job)[0].removeprefix("Subject: ")
        assert bundle["application_package"]["email_draft"]["subject"] == letter_subject, job["title"]


def test_health_nutrition_subject_is_the_standard_role_subject_without_a_reference():
    assert _letter_lines(_constructed_health_nutrition())[0] == "Subject: Application – Health & Nutrition Supervisor"


def test_heading_reference_is_omitted_when_the_subject_already_carries_it():
    from utils.document_design import _reference_shown_in_heading

    assert _reference_shown_in_heading({"reference": "HNTPO-MD-1012026", "subject": "HNTPO-MD-1012026"}) is False
    assert _reference_shown_in_heading({"reference": "HNTPO-MD-1012026", "subject": "Application – X"}) is True
    assert _reference_shown_in_heading({"reference": "", "subject": "Application"}) is False


def _docx_text(path) -> str:
    import zipfile

    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf8")
    return re.sub(r"<[^>]+>", " ", xml)


def test_medical_doctor_cover_letter_docx_states_the_reference_once(tmp_path):
    paths = _prepared_bundle(_acbar_medical_doctor(), tmp_path)["generated_paths"]
    docx = paths["cover_letter"]["docx"]
    assert _docx_text(docx).count("HNTPO-MD-1012026") == 1


# 5. Role-specific evidence selection for the supervisory health/nutrition letter.


def test_health_nutrition_bullets_lead_with_supervision_logistics_and_coordination():
    from utils.documents import _supervisory_tier

    bullets = _bullets(_letter_lines(_constructed_health_nutrition()))
    assert bullets[0].startswith("Supervised mobile health and nutrition teams"), bullets
    assert any("logistics" in bullet.lower() for bullet in bullets), bullets
    assert all(_supervisory_tier(bullet) <= 2 for bullet in bullets), bullets


def test_health_nutrition_bullets_drop_clinical_and_safeguarding_when_stronger_evidence_exists():
    bullets = _bullets(_letter_lines(_constructed_health_nutrition()))
    assert not any("SAM" in bullet or "Safeguarding" in bullet for bullet in bullets), bullets


def test_supervisory_ordering_prefers_experience_then_tier_and_selects_only_existing_lines():
    from utils.documents import _supervisory_letter_highlights

    items = [
        "Team supervision/capacity building",
        "Delivered clinical assessment, diagnosis, treatment, and follow-up care for children with SAM (Medical Doctor | ACF | Sang-e-Takht)",
        "Maintained accurate HMIS records and served as Safeguarding Focal Point (TFU Medical Doctor | ACF | Sang-e-Takht)",
        "Supported administrative operations, procurement processes, and program logistics (Administrative and Finance Officer | TBT)",
        "Supervised mobile health and nutrition teams delivering community-based BPHS/EPHS-related services (Health & Nutrition Supervisor | ACF)",
    ]
    selected = _supervisory_letter_highlights(items, limit=3)
    assert selected[0].startswith("Supervised mobile"), selected
    assert selected[1].startswith("Supported administrative"), selected
    assert "Team supervision/capacity building" not in selected
    assert set(selected) <= set(items)


def test_medical_doctor_bullets_keep_their_established_order():
    bullets = _bullets(_letter_lines(_acbar_medical_doctor()))
    assert bullets[0].startswith("Coordinated with Ministry of Public Health"), bullets
