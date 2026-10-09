"""Regression tests: an application-email subject instruction must be answered
with the field the posting actually names.

A posting that asks for the *vacancy number* in the subject requires the
vacancy identifier. A posting that asks for the *job title* (or *position
title*) requires the role title. The vacancy-number pattern used to list
``title`` among its qualifiers, so "job title in the subject line" was read as
a vacancy-number instruction and the extracted subject silently replaced the
role title with the vacancy reference.

These tests cover the three layers:

1. classification (:func:`classify_application_subject_requirement`),
2. extraction (:func:`extract_application_subject`),
3. the real application-drafting pipeline (email draft and cover letter).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from utils import discovery
from utils.documents import prepare_application_bundle
from utils.medical_matcher import match_job_against_profile
from utils.medical_requirements import (
    BOTH_SUBJECT_FIELDS,
    JOB_TITLE_SUBJECT,
    VACANCY_NUMBER_SUBJECT,
    application_subject_required,
    classify_application_subject_requirement,
    extract_application_subject,
)
from utils.profile import load_canonical_profile

FIXTURES = Path(__file__).parent / "fixtures" / "discovery"

# Real ACBAR/HealthNet TPO vacancy reference, used only as a regression
# fixture. No application is submitted and no employer is contacted.
REFERENCE = "HNTPO-MD-1012026"

ROLE_TITLE = "Medical Doctor (MD)"
APPLY_EMAIL = "recruitment@example.org"

_VACANCY_PREAMBLE = (
    "HealthNet TPO provides primary health services in Nangarhar. "
    "Job Summary The Medical Doctor diagnoses and treats patients and supports "
    "the BPHS/EPHS service package. "
    f"Vacancy Number: {REFERENCE} "
    "Deadline: 2026-12-31 "
    "Job Requirements Medical Doctor degree and Afghanistan Medical Council "
    "registration. Two years clinical experience. "
    "Submission Guideline "
)

VACANCY_NUMBER_TEXT = _VACANCY_PREAMBLE + f"Send CV with vacancy number in the subject line to {APPLY_EMAIL}."

JOB_TITLE_TEXT = _VACANCY_PREAMBLE + f"Send CV with job title in the subject line to {APPLY_EMAIL}."

POSITION_TITLE_TEXT = (
    "A national NGO requires a Medical Doctor for its Kabul clinic. "
    f"Vacancy Number: {REFERENCE} "
    "Please include the position title in the subject line of your email."
)

BOTH_REQUIRED_TEXT = (
    _VACANCY_PREAMBLE
    + f"Please write the vacancy number and the job title in the subject line, then email your CV to {APPLY_EMAIL}."
)

GENERIC_SUBJECT_TEXT = (
    "A national NGO requires a Medical Doctor for its Kabul clinic. "
    f"Please mention the position you are applying for in the email subject and send your CV to {APPLY_EMAIL}."
)


def _acbar_medical_doctor() -> dict:
    listing = discovery._parse_acbar_listing(
        (FIXTURES / "acbar_listing.html").read_text(encoding="utf-8"),
        "https://www.acbar.org/en/jobs?page=2",
    )
    summary = next(job for job in listing if job.title == ROLE_TITLE)
    return discovery._parse_acbar_detail(
        (FIXTURES / "acbar_detail.html").read_text(encoding="utf-8"), summary
    ).to_dict()


def _constructed_job(description: str) -> dict:
    """A realistic posting built from the ACBAR fixture, with our own wording."""
    job = _acbar_medical_doctor()
    job["description"] = description
    return job


def _bundle(job: dict, tmp_path) -> dict:
    profile = load_canonical_profile(required=True)
    report = match_job_against_profile(job, profile).to_dict()
    return prepare_application_bundle(job, profile, report, out_dir=tmp_path)


def _cover_letter_text(bundle: dict) -> str:
    path = Path(bundle["generated_paths"]["cover_letter"]["txt"])
    return path.read_text(encoding="utf-8")


# 1. Classification: which field does the posting name?


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(VACANCY_NUMBER_TEXT, VACANCY_NUMBER_SUBJECT, id="vacancy_number_wording"),
        pytest.param("Send CV with vacancy number in the subject line.", VACANCY_NUMBER_SUBJECT, id="minimal_vacancy_number"),
        pytest.param("Use the vacancy reference number in the email subject line.", VACANCY_NUMBER_SUBJECT, id="reference_number_wording"),
        pytest.param("The subject line must include the announcement code.", VACANCY_NUMBER_SUBJECT, id="reversed_vacancy_number"),
        pytest.param(JOB_TITLE_TEXT, JOB_TITLE_SUBJECT, id="job_title_wording"),
        pytest.param(POSITION_TITLE_TEXT, JOB_TITLE_SUBJECT, id="position_title_wording"),
        pytest.param("Please include the position title in the subject line.", JOB_TITLE_SUBJECT, id="minimal_position_title"),
        pytest.param("Please write the job title in the subject of your email.", JOB_TITLE_SUBJECT, id="job_title_in_email_subject"),
        pytest.param("The email subject line must state the post title.", JOB_TITLE_SUBJECT, id="reversed_job_title"),
        pytest.param(BOTH_REQUIRED_TEXT, BOTH_SUBJECT_FIELDS, id="both_fields_named"),
        pytest.param(GENERIC_SUBJECT_TEXT, None, id="generic_no_named_field"),
        pytest.param(f"Send your CV to {APPLY_EMAIL} by 2026-12-31.", None, id="plain_route"),
        pytest.param("The employee will be subject to organizational policies.", None, id="policy_prose"),
        pytest.param("The appointment is subject to the position title in the final contract.", None, id="subject_to_prose"),
    ],
)
def test_subject_field_is_classified_from_the_posting_wording(text, expected):
    assert classify_application_subject_requirement(text) == expected


def test_title_wording_is_never_classified_as_a_vacancy_number_requirement():
    """The original defect: 'title' was one of the vacancy-number qualifiers."""
    for text in (JOB_TITLE_TEXT, POSITION_TITLE_TEXT, "Send CV with job title in the subject."):
        assert classify_application_subject_requirement(text) == JOB_TITLE_SUBJECT
        assert classify_application_subject_requirement(text) != VACANCY_NUMBER_SUBJECT


@pytest.mark.parametrize(
    "text",
    [
        VACANCY_NUMBER_TEXT,
        JOB_TITLE_TEXT,
        POSITION_TITLE_TEXT,
        BOTH_REQUIRED_TEXT,
    ],
)
def test_named_field_instructions_are_subject_requirements(text):
    assert application_subject_required(text) is True


def test_plain_route_is_still_not_a_subject_requirement():
    assert application_subject_required(f"Send your CV to {APPLY_EMAIL} by 2026-12-31.") is False


# 2. Extraction: the subject carries the field the posting names.


def test_vacancy_number_required_uses_the_reference_and_not_the_title():
    assert extract_application_subject(VACANCY_NUMBER_TEXT, ROLE_TITLE) == REFERENCE


def test_job_title_required_uses_the_role_title_and_not_the_reference():
    """The regression: this returned the vacancy reference before the fix."""
    subject = extract_application_subject(JOB_TITLE_TEXT, ROLE_TITLE)
    assert subject == ROLE_TITLE
    assert REFERENCE not in subject


def test_position_title_required_uses_the_role_title():
    assert extract_application_subject(POSITION_TITLE_TEXT, ROLE_TITLE) == ROLE_TITLE


def test_title_required_without_a_role_title_falls_back_without_inventing_one():
    assert extract_application_subject(POSITION_TITLE_TEXT, "") is None


@pytest.mark.parametrize(
    "text",
    [
        "Send CV with the JOB TITLE in the Subject Line.",
        "Send CV with job title in the subject.",
        "Send CV with job   title in the email subject line.",
    ],
)
def test_title_required_is_case_and_punctuation_insensitive(text):
    assert extract_application_subject(f"Vacancy Number: {REFERENCE}. {text}", ROLE_TITLE) == ROLE_TITLE


def test_generic_subject_instruction_keeps_its_existing_behaviour():
    assert extract_application_subject(GENERIC_SUBJECT_TEXT, ROLE_TITLE) == ROLE_TITLE
    assert classify_application_subject_requirement(GENERIC_SUBJECT_TEXT) is None


def test_both_fields_required_keeps_both_and_drops_neither():
    subject = extract_application_subject(BOTH_REQUIRED_TEXT, ROLE_TITLE)
    assert REFERENCE in subject
    assert ROLE_TITLE in subject


def test_no_subject_instruction_returns_no_subject():
    text = f"Send your CV to {APPLY_EMAIL} by 2026-12-31."
    assert extract_application_subject(text, ROLE_TITLE) is None
    assert application_subject_required(text) is False


def test_vacancy_number_required_without_an_extractable_reference_is_not_a_title():
    assert extract_application_subject("Send CV with vacancy number in the subject line.", ROLE_TITLE) is None


# 3. The real application flow: email draft and cover letter agree.


def test_vacancy_number_posting_drafts_the_reference_as_subject(tmp_path):
    draft = _bundle(_acbar_medical_doctor(), tmp_path)["application_package"]["email_draft"]
    assert draft["subject"] == REFERENCE


def test_title_required_posting_drafts_the_role_title_as_subject(tmp_path):
    bundle = _bundle(_constructed_job(JOB_TITLE_TEXT), tmp_path)
    draft = bundle["application_package"]["email_draft"]
    assert draft["subject"] == ROLE_TITLE
    assert REFERENCE not in draft["subject"]


def test_both_required_posting_drafts_both_fields_as_subject(tmp_path):
    bundle = _bundle(_constructed_job(BOTH_REQUIRED_TEXT), tmp_path)
    subject = bundle["application_package"]["email_draft"]["subject"]
    assert subject.startswith(REFERENCE)
    assert ROLE_TITLE in subject


@pytest.mark.parametrize("description", [VACANCY_NUMBER_TEXT, JOB_TITLE_TEXT, BOTH_REQUIRED_TEXT])
def test_cover_letter_subject_matches_the_email_draft_subject(description, tmp_path):
    bundle = _bundle(_constructed_job(description), tmp_path)
    draft_subject = bundle["application_package"]["email_draft"]["subject"]
    letter_subject = _cover_letter_text(bundle).splitlines()[0].removeprefix("Subject: ")
    assert letter_subject == draft_subject


def test_reference_is_not_duplicated_in_the_cover_letter(tmp_path):
    bundle = _bundle(_acbar_medical_doctor(), tmp_path)
    draft_subject = bundle["application_package"]["email_draft"]["subject"]
    assert draft_subject == REFERENCE
    assert draft_subject.count(REFERENCE) == 1
    letter = _cover_letter_text(bundle)
    assert letter.count(REFERENCE) == 1


def test_heading_reference_is_omitted_when_the_subject_already_carries_it(tmp_path):
    from utils.document_design import _reference_shown_in_heading

    bundle = _bundle(_acbar_medical_doctor(), tmp_path)
    subject = bundle["application_package"]["email_draft"]["subject"]
    assert _reference_shown_in_heading({"reference": REFERENCE, "subject": subject}) is False
    assert _reference_shown_in_heading({"reference": REFERENCE, "subject": ROLE_TITLE}) is True


@pytest.mark.parametrize("description", [VACANCY_NUMBER_TEXT, JOB_TITLE_TEXT, BOTH_REQUIRED_TEXT])
def test_subject_is_never_the_application_route(description, tmp_path):
    bundle = _bundle(_constructed_job(description), tmp_path)
    subject = bundle["application_package"]["email_draft"]["subject"]
    assert "@" not in subject
    assert not re.search(r"\bto\b\s*$", subject)
    assert bundle["application_package"]["email_draft"]["to"] == APPLY_EMAIL
