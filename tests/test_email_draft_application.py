"""End-to-end tests for user-reviewed, never-autosent employer email drafts."""

from __future__ import annotations

import re
from email import policy
from email.parser import BytesParser

import pytest

from utils.email_drafts import EmailDraftError, build_email_draft


@pytest.fixture
def sample(tmp_path):
    folder = tmp_path / "documents" / "applications"
    folder.mkdir(parents=True)
    cv = folder / "tailored_cv.pdf"
    letter = folder / "cover_letter.pdf"
    cv.write_bytes(b"%PDF-1.4\n" + b"X" * 256)
    letter.write_bytes(b"%PDF-1.4\n" + b"Y" * 256)
    return tmp_path, cv, letter


def _job(cv, letter, checklist):
    return {
        "id": "acbar-tfu-42",
        "is_expired": False,
        "package": {
            "route_type": "email",
            "package_status": "READY_FOR_REVIEW",
            "missing_items": [],
            "required_documents_checklist": checklist,
            "email_draft": {
                "to": "recruitment@example.org",
                "subject": "Application for Head of TFU",
                "body": "Dear Hiring Committee,\n\nPlease review my application.\n\nKind regards.",
            },
        },
        "documents": {"generated_paths": {
            "tailored_cv": {"pdf": str(cv)},
            "cover_letter": {"pdf": str(letter)},
        }},
    }


def _parts(raw):
    email = BytesParser(policy=policy.default).parsebytes(raw)
    return email, [part for part in email.iter_attachments()]


def test_eml_for_cv_only_has_correct_recipient_body_subject_and_exact_attachment(sample):
    root, cv, letter = sample
    name, data = build_email_draft(_job(cv, letter, ["Tailored CV / resume"]), project_root=root)
    message, attachments = _parts(data)
    assert name.endswith("-UNSENT.eml")
    assert message["To"] == "recruitment@example.org"
    assert message["Subject"] == "Application for Head of TFU"
    assert message.get("From") is None
    assert message["X-Unsent"] == "1"
    assert "Please review my application." in message.get_body(preferencelist=("plain",)).get_content()
    assert [part.get_filename() for part in attachments] == [cv.name]
    assert attachments[0].get_payload(decode=True) == cv.read_bytes()


def test_eml_attaches_cover_only_when_requested(sample):
    root, cv, letter = sample
    _, both = build_email_draft(_job(cv, letter, ["Tailored CV", "Cover letter"]), project_root=root)
    msg, attachments = _parts(both)
    assert msg["To"] == "recruitment@example.org"
    assert {part.get_filename() for part in attachments} == {cv.name, letter.name}


@pytest.mark.parametrize("route,status,missing", [
    ("online_form", "READY_FOR_REVIEW", []),
    ("email", "NEEDS_USER_INPUT", ["missing form"]),
    ("email", "READY_FOR_REVIEW", ["unverified"]),
])
def test_invalid_application_readiness_blocks_email(sample, route, status, missing):
    root, cv, letter = sample
    job = _job(cv, letter, ["Tailored CV"])
    job["package"].update(route_type=route, package_status=status, missing_items=missing)
    with pytest.raises(EmailDraftError):
        build_email_draft(job, project_root=root)


def test_extra_required_document_blocks_incomplete_draft(sample):
    root, cv, letter = sample
    with pytest.raises(EmailDraftError, match="additional documents"):
        build_email_draft(_job(cv, letter, ["Tailored CV", "Completed organization application form"]), project_root=root)


def test_wrong_path_and_invalid_pdf_do_not_leave_email_draft(sample):
    root, cv, letter = sample
    job = _job(cv, letter, ["Tailored CV"])
    job["documents"]["generated_paths"]["tailored_cv"]["pdf"] = str(letter.parent.parent.parent / "profile.yaml")
    with pytest.raises(EmailDraftError):
        build_email_draft(job, project_root=root)
    cv.write_text("NOT A PDF", encoding="utf-8")
    job["documents"]["generated_paths"]["tailored_cv"]["pdf"] = str(cv)
    with pytest.raises(EmailDraftError):
        build_email_draft(job, project_root=root)


def test_email_header_injection_rejected(sample):
    root, cv, letter = sample
    job = _job(cv, letter, ["Tailored CV"])
    job["package"]["email_draft"]["subject"] = "Head of TFU\nBcc: attacker@example.org"
    with pytest.raises(EmailDraftError):
        build_email_draft(job, project_root=root)


def test_original_documents_and_application_status_are_unchanged(sample):
    root, cv, letter = sample
    job = _job(cv, letter, ["Tailored CV"])
    before = (cv.read_bytes(), letter.read_bytes(), repr(job))
    build_email_draft(job, project_root=root)
    assert (cv.read_bytes(), letter.read_bytes(), repr(job)) == before
    assert not any(root.rglob("*.eml"))


def test_frontend_apply_action_and_backend_never_claim_auto_send():
    from utils.paths import PROJECT_ROOT
    js = (PROJECT_ROOT / "dashboard/static/app.js").read_text(encoding="utf-8")
    server = (PROJECT_ROOT / "dashboard/server.py").read_text(encoding="utf-8")
    assert 'data-action="apply-email"' in js
    assert 'async function applyByEmail(id)' in js
    assert '@app.post("/api/jobs/{job_id}/open-email")' in server
    assert '"sent": False' in server
    assert not re.search(r"(smtp\.sendmail|gmail\.messages\.send)", server, re.IGNORECASE)
