"""CLI and dashboard follow the same safe application lifecycle."""

from __future__ import annotations

from datetime import date, timedelta

import main


def _stored_job(*, closing: str, status: str = "REVIEWED") -> dict:
    return {
        "id": "job-123",
        "title": "Medical Doctor",
        "company": "Example NGO",
        "status": status,
        "metadata": {
            "closing_date": closing,
            "source_name": "ACBAR",
            "source_url": "https://www.acbar.org/en/jobs",
        },
    }


def test_cli_cannot_regenerate_an_expired_or_manually_applied_vacancy(monkeypatch, capsys):
    def should_not_run(*args, **kwargs):
        raise AssertionError("No profile matching or generation should occur for blocked jobs")

    monkeypatch.setattr(main, "match_job_against_profile", should_not_run)
    monkeypatch.setattr(main, "prepare_application_bundle", should_not_run)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    future = (date.today() + timedelta(days=10)).isoformat()
    for stored in (
        _stored_job(closing=yesterday),
        _stored_job(closing=future, status="APPLIED_MANUALLY"),
    ):
        monkeypatch.setattr(main, "get_job_by_id", lambda _id: stored)
        assert main.cmd_prepare({}, "job-123") is None
    feedback = capsys.readouterr().out
    assert "deadline has passed" in feedback
    assert "already recorded as submitted" in feedback


def test_cli_uses_official_form_when_both_web_and_contact_email_are_present(monkeypatch):
    target = "https://forms.gle/aRealApplicationForm"
    job = {
        **_stored_job(closing=(date.today() + timedelta(days=10)).isoformat()),
        "apply_email": "contact@example.org",
        "apply_url": target,
        "metadata": {"application_method": "WEB", "apply_email": "contact@example.org", "apply_url": target},
    }
    opened: list[str] = []
    monkeypatch.setattr(main, "get_job_by_id", lambda _id: job)
    monkeypatch.setattr(main.webbrowser, "open", opened.append)
    main.cmd_open("job-123")
    assert opened == [target]


def test_cli_preserves_email_only_legacy_routes(monkeypatch):
    job = {
        **_stored_job(closing=(date.today() + timedelta(days=10)).isoformat()),
        "apply_email": "recruitment@example.org",
        "apply_url": "",
        "metadata": {"application_method": "EMAIL", "apply_email": "recruitment@example.org"},
    }
    opened: list[str] = []
    monkeypatch.setattr(main, "get_job_by_id", lambda _id: job)
    monkeypatch.setattr(main.webbrowser, "open", opened.append)
    main.cmd_open("job-123")
    assert opened == ["mailto:recruitment@example.org"]
