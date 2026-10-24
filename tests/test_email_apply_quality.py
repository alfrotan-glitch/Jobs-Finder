"""Real apply-email MIME and verified CV duty acceptance regressions."""

from __future__ import annotations

import copy
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard import server
from utils.email_application import EmailCompositionError, compose_application_email


@pytest.fixture
def email_job(tmp_path):
    root = tmp_path / "Jobs-Finder"
    docs = root / "documents" / "applications"
    docs.mkdir(parents=True)
    cv = docs / "tailored_cv.pdf"
    cover = docs / "cover_letter.pdf"
    cv.write_bytes(b"%PDF-1.4\n% example CV")
    cover.write_bytes(b"%PDF-1.4\n% example cover letter")
    job = {
        "id": "acbar-test-head-tfu",
        "title": "Head of TFU",
        "company": "Example NGO",
        "source": "ACBAR",
        "url": "https://www.acbar.org/en/jobs/details/123/head-tfu",
        "apply_url": "applications@example.org",
        "status": "PACKAGE_READY",
        "is_expired": False,
        "metadata": {
            "application_method": "EMAIL",
            "apply_email": "applications@example.org",
            "source_url": "https://www.acbar.org",
            "vacancy_url": "https://www.acbar.org/en/jobs/details/123/head-tfu",
        },
        "package": {
            "package_status": "READY_FOR_REVIEW",
            "required_documents_checklist": ["Tailored CV / resume"],
            "email_draft": {
                "to": "applications@example.org",
                "subject": "Application for Head of TFU",
                "body": "Dear recruitment team,\nI am applying to the role.\nRegards",
            },
        },
        "documents": {
            "generated_paths": {
                "tailored_cv": {"pdf": str(cv)},
                "cover_letter": {"pdf": str(cover)},
            },
        },
    }
    return root, job, cv, cover


def _actual_message(job, root):
    name, data, attachments = compose_application_email(job, root=root)
    message = BytesParser(policy=policy.default).parsebytes(data)
    return name, message, attachments


def test_cv_only_email_includes_actual_pdf_and_not_extra_cover(email_job):
    root, job, cv, cover = email_job
    original = copy.deepcopy(job)
    name, message, files = _actual_message(job, root)
    assert name.endswith(".eml")
    assert message["To"] == "applications@example.org"
    assert message["Subject"] == "Application for Head of TFU"
    assert not message["From"]
    assert "I am applying" in message.get_body(preferencelist=("plain",)).get_content()
    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == cv.name
    assert attachments[0].get_payload(decode=True) == cv.read_bytes()
    assert files == [cv.name]
    assert cover.name not in files
    assert job == original  # Preparing an email is never submission.


def test_cover_and_cv_both_attached_exactly_when_requested(email_job):
    root, job, cv, cover = email_job
    job["package"]["required_documents_checklist"] = [
        "Tailored CV / resume", "Tailored cover letter / application letter"
    ]
    _, message, files = _actual_message(job, root)
    assert files == [cv.name, cover.name]
    assert len(list(message.iter_attachments())) == 2


def test_cover_only_does_not_attach_unrequested_cv(email_job):
    root, job, cv, cover = email_job
    job["package"]["required_documents_checklist"] = ["Tailored cover letter / application letter"]
    _, _, files = _actual_message(job, root)
    assert files == [cover.name] and cv.name not in files


@pytest.mark.parametrize(
    "mutation",
    ["online", "stale_email", "needs_input", "submitted", "missing_pdf", "manual_form", "traversal"],
)
def test_unsafe_apply_attempts_are_rejected_without_writing_or_sending(email_job, mutation, tmp_path):
    root, job, cv, _ = email_job
    if mutation == "online":
        job["metadata"]["application_method"] = "WEB"
        job["metadata"]["apply_url"] = "https://example.org/online-form"
    elif mutation == "stale_email":
        job["package"]["email_draft"]["to"] = "wrong@example.org"
    elif mutation == "needs_input":
        job["package"]["package_status"] = "NEEDS_USER_INPUT"
    elif mutation == "submitted":
        job["status"] = "APPLIED_MANUALLY"
    elif mutation == "missing_pdf":
        cv.unlink()
    elif mutation == "manual_form":
        job["package"]["required_documents_checklist"].append("Completed employer application form")
    elif mutation == "traversal":
        outside = tmp_path / "private.pdf"
        outside.write_bytes(b"%PDF secret")
        job["documents"]["generated_paths"]["tailored_cv"]["pdf"] = str(outside)
    with pytest.raises(EmailCompositionError):
        compose_application_email(job, root=root)
    assert not list(root.rglob("*.eml"))


def test_email_draft_api_is_post_only_and_returns_real_mime(email_job, monkeypatch):
    root, job, cv, _ = email_job
    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "get_job_by_id", lambda _id: job)
    monkeypatch.setattr(server, "is_expired", lambda _job: False)
    client = TestClient(server.app)
    assert client.get("/api/jobs/acbar-test-head-tfu/email-draft").status_code == 405
    response = client.post("/api/jobs/acbar-test-head-tfu/email-draft")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("message/rfc822")
    assert response.headers["cache-control"].startswith("no-store")
    actual = BytesParser(policy=policy.default).parsebytes(response.content)
    assert [part.get_filename() for part in actual.iter_attachments()] == [cv.name]
    assert job["status"] == "PACKAGE_READY"


def test_confirming_own_verified_duty_is_explicit_and_preserves_profile(monkeypatch):
    base = {
        "work_history": [
            {
                "title": "Health & Nutrition Supervisor",
                "organization": "ACF International",
                "verified": True,
                "responsibilities": [
                    {"text": "Supervised teams delivering basic health and nutrition services.", "verified": True}
                ],
            }
        ],
        "profile_status": "VERIFIED",
    }
    saves = []
    monkeypatch.setattr(server, "_runtime_profile", lambda _required: copy.deepcopy(base))
    monkeypatch.setattr(server, "save_canonical_profile", lambda profile: saves.append(copy.deepcopy(profile)))
    client = TestClient(server.app)
    url = "/api/profile/experience/0/add-duty"
    payload = {
        "role_title": "Health & Nutrition Supervisor",
        "text": "I supervised and coached field health and nutrition teams in providing the verified service package.",
        "confirmation": "I CONFIRM THIS IS MY EXPERIENCE",
    }
    denied = client.post(url, json={**payload, "confirmation": "anything"})
    assert denied.status_code == 400 and not saves
    assert client.post(url, json={**payload, "role_title": "Different role"}).status_code == 409
    assert not saves
    success = client.post(url, json=payload)
    assert success.status_code == 200
    assert len(saves) == 1
    assert len(saves[0]["work_history"][0]["responsibilities"]) == 2
    assert saves[0]["work_history"][0]["responsibilities"][-1] == {
        "text": payload["text"], "verified": True
    }
    assert len(base["work_history"][0]["responsibilities"]) == 1


def test_frontend_apply_and_verified_role_controls_are_real():
    from utils.paths import PROJECT_ROOT

    js = (PROJECT_ROOT / "dashboard" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'data-action="apply-job"' in js
    assert "async function applyJob" in js
    assert "email-draft" in js
    assert 'data-action="add-verified-duty"' in js
    assert "I CONFIRM THIS IS MY EXPERIENCE" in js
