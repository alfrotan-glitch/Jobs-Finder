"""Final application handover regressions: genuine letters and correct Apply path."""

from __future__ import annotations

import copy

import pytest

from utils.documents import _infer_required_documents
from utils.email_drafts import EmailDraftError, build_email_draft


@pytest.mark.parametrize(("description", "expected"), [
    ("Submit ONLY a cover letter to apply.", ["Tailored cover letter / application letter"]),
    ("Attach your CV only.", ["Tailored CV / resume"]),
    ("Attach your curriculum vitae and cover letter.", [
        "Tailored CV / resume", "Tailored cover letter / application letter",
    ]),
    ("Submit an application by email.", ["Tailored CV / resume"]),
])
def test_employer_document_selection_does_not_create_extra_files(description, expected):
    job = {"title": "Clinical Officer", "description": description}
    assert _infer_required_documents(job) == expected


@pytest.fixture
def ready_email_job(tmp_path):
    folder = tmp_path / "documents" / "applications"
    folder.mkdir(parents=True)
    cv = folder / "cv.pdf"
    letter = folder / "letter.pdf"
    cv.write_bytes(b"%PDF-1.4\n" + b"X" * 300)
    letter.write_bytes(b"%PDF-1.4\n" + b"Y" * 300)
    job = {
        "id": "vac-1",
        "title": "Head of TFU",
        "metadata": {
            "application_method": "EMAIL",
            "apply_email": "hiring@example.org",
            "source_name": "ACBAR",
            "source_url": "https://www.acbar.org",
            "vacancy_url": "https://www.acbar.org/en/jobs/details/42",
        },
        "package": {
            "route_type": "email",
            "package_status": "READY_FOR_REVIEW",
            "required_documents_checklist": ["CV and cover letter"],
            "email_draft": {
                "to": "hiring@example.org",
                "subject": "Head of TFU",
                "body": "Please find my application attached.",
            },
        },
        "documents": {"generated_paths": {
            "tailored_cv": {"pdf": str(cv)},
            "cover_letter": {"pdf": str(letter)},
        }},
    }
    return tmp_path, job


def test_combined_cv_cover_request_is_both_attachments(ready_email_job):
    from email import policy
    from email.parser import BytesParser

    root, job = ready_email_job
    _, payload = build_email_draft(job, project_root=root)
    email = BytesParser(policy=policy.default).parsebytes(payload)
    assert [part.get_filename() for part in email.iter_attachments()] == [
        "cv.pdf", "letter.pdf"
    ]


def test_current_web_route_cannot_be_sent_to_old_saved_email(ready_email_job):
    root, job = ready_email_job
    job["metadata"]["application_method"] = "WEB"
    job["metadata"]["apply_url"] = "https://organization.org/application"
    with pytest.raises(EmailDraftError, match="online form|web form|WEB|online"):
        build_email_draft(job, project_root=root)


def test_email_recipient_must_agree_with_current_advertised_destination(ready_email_job):
    root, job = ready_email_job
    job["package"]["email_draft"]["to"] = "contact@example.org"
    with pytest.raises(EmailDraftError, match="no longer matches|match"):
        build_email_draft(job, project_root=root)


def test_already_submitted_vacancy_cannot_open_fresh_draft(ready_email_job):
    root, job = ready_email_job
    job["status"] = "APPLIED_MANUALLY"
    with pytest.raises(EmailDraftError, match="already submitted"):
        build_email_draft(job, project_root=root)


def test_cover_letter_uses_only_employment_evidence_for_role_narrative():
    from utils.documents import generate_tailored_documents
    from utils.medical_matcher import match_job_against_profile
    from utils.profile import load_canonical_profile

    profile = copy.deepcopy(load_canonical_profile(required=True))
    job = {
        "id": "test-verified-nutrition",
        "title": "Head of TFU",
        "company": "Illustrative Health Organization",
        "location": "Afghanistan",
        "description": (
            "Medical doctor leading therapeutic feeding unit management, "
            "SAM/CMAM case management, nutrition supervision, "
            "quality of care and reporting."
        ),
        "source": "ACBAR",
        "source_url": "https://www.acbar.org",
        "url": "https://www.acbar.org/en/jobs/details/999",
    }
    report = match_job_against_profile(job, profile).to_dict()
    docs = generate_tailored_documents(job, profile, report)
    letter = docs["cover_letter"]
    assert "Dear Hiring Committee" in letter
    assert "Head of TFU" in letter
    # The letter mentions a real employer/role rather than fabricating a
    # newly acquired job title or years/metrics.
    roles = [entry for entry in docs["tailored_cv_model"]["experience"] if entry.get("bullets")]
    assert roles, "The verified canonical work history should contain role evidence."
    assert any(
        "In my documented role as " + str(item.get("role")) in letter
        for item in roles
    )
    assert "reduced mortality by 50%" not in letter.lower()


def test_ui_no_longer_offers_attachmentless_mailto_apply():
    from utils.paths import PROJECT_ROOT

    js = (PROJECT_ROOT / "dashboard" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'data-action="apply-email"' in js
    assert 'async function applyByEmail(id)' in js
    assert "Apply · Email with attachments" in js
    assert "href=\"mailto:" not in js
