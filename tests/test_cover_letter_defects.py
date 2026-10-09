"""Regression tests for two cover-letter defects found in the final visual review.

1. The email subject line captured the application route ("to recruitment@...")
   instead of the vacancy reference that the posting actually asks for.
2. Evidence bullets carried a nested attribution ``(... (2020-10 – 2020-12))``
   because the attribution stripper could not match a parenthesised date range.
"""

from __future__ import annotations

from pathlib import Path

from utils import discovery
from utils.documents import generate_tailored_documents
from utils.medical_matcher import match_job_against_profile
from utils.profile import load_canonical_profile

FIXTURES = Path(__file__).parent / "fixtures" / "discovery"

HN_TEXT = (
    "Health & Nutrition Supervisor required. Mobile health and nutrition teams; "
    "community-based BPHS/EPHS; IMAM/CMAM; SAM and TFU; team supervision and "
    "capacity building; HMIS/DHIS2 reporting; medical supply forecasting. "
    "Apply to recruitment@example.org by 2026-12-31."
)


def _acbar_medical_doctor():
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


def _cover_letter(job: dict) -> str:
    profile = load_canonical_profile(required=True)
    report = match_job_against_profile(job, profile).to_dict()
    return generate_tailored_documents(job, profile, report)["cover_letter"]


def test_email_route_is_never_captured_as_subject():
    assert discovery._extract_subject(
        "Send CV with vacancy number in the subject line to recruitment@example.org."
    ) == ""


def test_acbar_subject_metadata_is_not_the_contact_route():
    subject = _acbar_medical_doctor()["metadata"].get("application_subject", "")
    assert "@" not in subject
    assert not subject.lower().startswith("to ")


def test_cover_letter_subject_is_the_vacancy_reference():
    subject_line = _cover_letter(_acbar_medical_doctor()).splitlines()[0]
    assert subject_line.startswith("Subject: ")
    assert "@" not in subject_line
    assert "HNTPO-MD-1012026" in subject_line


def test_cover_letter_bullets_carry_no_nested_parentheses():
    for letter in (_cover_letter(_acbar_medical_doctor()), _cover_letter(_constructed_health_nutrition())):
        assert "))" not in letter
        assert "((" not in letter
