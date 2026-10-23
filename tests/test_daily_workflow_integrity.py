"""End-to-end local tracker invariants for everyday use.

Rescanning is an information refresh, not a reset of the applicant's actions.
Expired saved listings remain historical records but must no longer be
advertised or prepared as current opportunities.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from dashboard import server
from utils import tracker
from utils.discovery import Job


def job(job_id: str, *, closing: str) -> Job:
    return Job(
        job_id,
        "Medical Doctor",
        "Example NGO",
        "Kabul",
        f"https://www.acbar.org/en/jobs/details/{job_id}/{job_id}",
        "recruitment@example.org",
        "acbar",
        "Medical Doctor (MD) role in primary healthcare. Send CV to recruitment@example.org.",
        metadata={
            "source_name": "ACBAR",
            "source_url": "https://www.acbar.org/en/jobs",
            "vacancy_url": f"https://www.acbar.org/en/jobs/details/{job_id}/{job_id}",
            "application_method": "EMAIL",
            "apply_email": "recruitment@example.org",
            "closing_date": closing,
        },
    )


def ready_report() -> dict:
    return {"readiness_status": "READY_TO_APPLY", "facts": {"role_analysis": {"classification": "md_physician_role"}}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(server, "_runtime_profile", lambda required=False: {})
    return TestClient(server.app)


def test_rescan_preserves_prepared_package_and_manual_application(client):
    item = job("repeat", closing=(date.today() + timedelta(days=14)).isoformat())
    tracker.log_discovered_and_medical_match(item, ready_report())
    documents = {
        "application_package": {"package_status": "READY_FOR_REVIEW", "email_draft": {"to": "recruitment@example.org"}},
        "generated_paths": {"tailored_cv": {"pdf": "documents/applications/repeat.pdf"}},
    }
    tracker.update_tailored_resume(item.id, documents)
    assert tracker.get_job_by_id(item.id)["status"] == tracker.PACKAGE_READY

    tracker.log_discovered_and_medical_match(item, ready_report())
    persisted = tracker.get_job_by_id(item.id)
    assert persisted["status"] == tracker.PACKAGE_READY
    assert persisted["documents"]["generated_paths"] == documents["generated_paths"]

    ok, _ = tracker.mark_applied_manually(item.id, confirmation=f"APPLIED {item.id}")
    assert ok
    tracker.log_discovered_and_medical_match(item, ready_report())
    assert tracker.get_job_by_id(item.id)["status"] == tracker.APPLIED_MANUALLY

    # Even a direct lower-level regenerate must not erase this fact.
    tracker.update_tailored_resume(item.id, documents)
    assert tracker.get_job_by_id(item.id)["status"] == tracker.APPLIED_MANUALLY
    assert all(x["id"] != item.id for x in tracker.get_recommended_jobs())


def test_recommendation_preserves_generated_download_paths_after_refresh(client):
    item = job("prepared", closing=(date.today() + timedelta(days=12)).isoformat())
    tracker.log_discovered_and_medical_match(item, ready_report())
    documents = {
        "application_package": {"package_status": "READY_FOR_REVIEW", "email_draft": {"to": "recruitment@example.org"}},
        "generated_paths": {"tailored_cv": {"pdf": "documents/applications/prepared.pdf", "docx": "documents/applications/prepared.docx"}},
    }
    tracker.update_tailored_resume(item.id, documents)
    tracker.log_scan_result({
        "status": "SCAN_COMPLETE",
        "started_at": "2026-10-01T08:00:00Z",
        "finished_at": "2026-10-01T08:00:02Z",
        "recommendations": [{
            "id": item.id, "title": item.title, "metadata": item.metadata,
            "readiness": "READY_TO_APPLY", "status": "REVIEWED",
        }],
    })

    response = client.get("/api/recommended")
    assert response.status_code == 200
    result = response.json()
    assert result["data_origin"] == "latest_saved_scan"
    assert len(result["jobs"]) == 1
    row = result["jobs"][0]
    assert row["status"] == "PACKAGE_READY"
    assert row["package_status"] == "READY_FOR_REVIEW"
    assert row["documents"]["generated_paths"]["tailored_cv"]["docx"].endswith("prepared.docx")
    assert row["package"]["email_draft"]["to"] == "recruitment@example.org"


def test_stale_deadline_is_removed_from_current_recommendations_but_remains_history(client):
    closed = job("closed", closing=(date.today() - timedelta(days=1)).isoformat())
    tracker.log_discovered_and_medical_match(closed, ready_report())
    tracker.log_scan_result({
        "status": "SCAN_COMPLETE",
        "recommendations": [{
            "id": closed.id, "title": closed.title, "metadata": closed.metadata,
            "readiness": "READY_TO_APPLY", "status": "REVIEWED",
        }],
    })
    assert tracker.get_job_by_id(closed.id)["is_expired"] is True
    assert tracker.get_recommended_jobs() == []
    assert client.get("/api/recommended").json()["jobs"] == []
    jobs = client.get("/api/jobs").json()["jobs"]
    assert any(x["id"] == closed.id and x["is_expired"] for x in jobs)
    response = client.post(f"/api/jobs/{closed.id}/prepare")
    assert response.status_code == 409
    assert "passed its stated deadline" in response.json()["detail"]
    assert tracker.get_job_by_id(closed.id)["documents"] == {}


def test_previously_applied_vacancy_cannot_be_prepared_again(client):
    item = job("submitted", closing=(date.today() + timedelta(days=15)).isoformat())
    tracker.log_discovered_and_medical_match(item, ready_report())
    ok, _ = tracker.mark_applied_manually(item.id, confirmation=f"APPLIED {item.id}")
    assert ok
    response = client.post(f"/api/jobs/{item.id}/prepare")
    assert response.status_code == 409
    assert "already marked as submitted" in response.json()["detail"]
    assert tracker.get_job_by_id(item.id)["status"] == tracker.APPLIED_MANUALLY


def test_dashboard_renders_closed_history_without_representing_it_as_open():
    from utils.paths import PROJECT_ROOT

    script = (PROJECT_ROOT / "dashboard" / "static" / "app.js").read_text(encoding="utf-8")
    assert "job.is_expired" in script
    assert "DEADLINE PASSED" in script
    assert "Past-deadline vacancies" in script
    assert "canPrepare = !isNotEligible && !job.is_expired" in script
