"""Recommendation results must expose saved-scan provenance to the UI."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard import server
from utils import profile as profile_repository
from utils import tracker
from utils.discovery import Job


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_repository, "CANONICAL_PROFILE_PATH", tmp_path / "profile.yaml")
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    return TestClient(server.app)


def _job() -> Job:
    return Job(
        "saved-history-md",
        "Medical Officer",
        "Example Health Organization",
        "Kabul",
        "https://jobs.example.org/vacancies/saved-history-md",
        "recruitment@example.org",
        "ACBAR",
        "Medical Doctor required. Apply to recruitment@example.org.",
        metadata={
            "source_name": "ACBAR",
            "source_url": "https://jobs.example.org/source",
            "vacancy_url": "https://jobs.example.org/vacancies/saved-history-md",
            "application_method": "EMAIL",
            "apply_email": "recruitment@example.org",
        },
    )


def test_recommended_endpoint_labels_history_when_no_saved_scan_exists(client):
    job = _job()
    tracker.log_discovered(job)
    tracker.log_medical_match(job.id, {"readiness_status": "READY_TO_APPLY"})

    body = client.get("/api/recommended").json()
    assert body["data_origin"] == "stored_history"
    assert body["scan"] is None
    assert [row["id"] for row in body["jobs"]] == [job.id]


def test_dashboard_script_discloses_saved_recommendation_provenance():
    script = Path("dashboard/static/app.js").read_text(encoding="utf-8")
    assert "Recommendations from the last saved scan" in script
    assert "Showing saved recommendation history, not a live source result" in script
