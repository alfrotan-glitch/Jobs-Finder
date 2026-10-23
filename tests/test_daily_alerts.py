"""Daily alert inbox end-to-end regression tests using the actual local SQLite store."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from dashboard import server
from utils import tracker
from utils.alerts import (
    list_alerts,
    record_deadline_alerts,
    record_scan_alerts,
)
from utils.discovery import SCAN_COMPLETE, SOURCES_UNAVAILABLE, Job
from utils.scan_guard import ScanAlreadyRunning, exclusive_scan
from utils.windows_schedule import schedule_status


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "applications.db")
    return TestClient(server.app)


def _job(job_id: str, *, deadline: date | None = None):
    return Job(
        job_id, "Medical Officer", "Example Humanitarian Organization", "Kabul",
        f"https://www.acbar.org/en/jobs/details/{job_id}/medical-officer",
        None, "acbar", "Physician with clinical experience, send CV to employer.",
        metadata={
            "source_name": "ACBAR",
            "source_url": "https://www.acbar.org/en/jobs",
            "vacancy_url": f"https://www.acbar.org/en/jobs/details/{job_id}/medical-officer",
            "closing_date": (deadline or date.today() + timedelta(days=20)).isoformat(),
            "apply_email": "recruitment@example.org",
            "application_method": "EMAIL",
        },
    )


def _report(status="READY_TO_APPLY"):
    return {
        "readiness_status": status,
        "facts": {"role_analysis": {"classification": "md_physician_role"}},
    }


def _scan(*jobs, status=SCAN_COMPLETE):
    return {
        "status": status,
        "recommendations": [
            {
                "id": job.id, "title": job.title, "company": job.company,
                "metadata": job.metadata, "readiness": "READY_TO_APPLY",
                "match": _report(),
            }
            for job in jobs
        ],
    }


def test_first_seen_matching_alert_is_persistent_and_never_duplicate(client):
    job = _job("first-match")
    tracker.log_discovered_and_medical_match(job, _report())
    record_scan_alerts(_scan(job))
    record_scan_alerts(_scan(job))
    body = client.get("/api/alerts").json()
    assert body["unread_count"] == 1
    assert len(body["alerts"]) == 1
    first = body["alerts"][0]
    assert first["kind"] == "NEW_MATCH"
    assert first["job_id"] == job.id
    assert "New match" in first["title"]

    acknowledged = client.post(f"/api/alerts/{first['id']}/read")
    assert acknowledged.status_code == 200
    assert client.get("/api/alerts").json()["unread_count"] == 0
    assert client.post(f"/api/alerts/{first['id']}/read").status_code == 200
    assert client.post("/api/alerts/123456789/read").status_code == 404


def test_deadline_thresholds_are_deduplicated_and_only_for_actionable_jobs(client):
    today = date.today()
    soon = _job("soon", deadline=today + timedelta(days=6))
    blocked = _job("ineligible", deadline=today + timedelta(days=1))
    past = _job("past", deadline=today - timedelta(days=1))
    for job, report in [(soon, _report()), (blocked, _report("NOT_ELIGIBLE")), (past, _report())]:
        tracker.log_discovered_and_medical_match(job, report)
    record_deadline_alerts(today=today)
    record_deadline_alerts(today=today)
    notices = list_alerts()["alerts"]
    assert len(notices) == 1
    assert "in 6 days" in notices[0]["title"]
    assert notices[0]["job_id"] == "soon"

    record_deadline_alerts(today=today + timedelta(days=3))
    record_deadline_alerts(today=today + timedelta(days=5))
    notices = list_alerts()["alerts"]
    assert len(notices) == 3
    assert all(x["job_id"] == "soon" for x in notices)
    assert {x["kind"] for x in notices} == {"DEADLINE"}


def test_no_false_match_created_from_source_outage(client):
    job = _job("not-yet-seen")
    tracker.log_discovered_and_medical_match(job, _report())
    today = date(2026, 10, 23)
    record_scan_alerts(_scan(job, status=SOURCES_UNAVAILABLE), today=today)
    record_scan_alerts(_scan(job, status=SOURCES_UNAVAILABLE), today=today)
    assert len(list_alerts()["alerts"]) == 1
    assert list_alerts()["alerts"][0]["kind"] == "SOURCE_ISSUE"
    record_scan_alerts(_scan(job), today=today)
    assert len(list_alerts()["alerts"]) == 2
    assert list_alerts()["alerts"][0]["kind"] == "NEW_MATCH"


def test_manual_application_is_not_realerted(client):
    job = _job("submitted")
    tracker.log_discovered_and_medical_match(job, _report())
    ok, _ = tracker.mark_applied_manually(job.id, confirmation=f"APPLIED {job.id}")
    assert ok
    record_scan_alerts(_scan(job))
    record_deadline_alerts(today=date.today())
    assert list_alerts()["alerts"] == []


def test_inbox_read_all_and_limits(client):
    for index in range(4):
        job = _job(f"match-{index}")
        tracker.log_discovered_and_medical_match(job, _report())
        record_scan_alerts(_scan(job))
    assert client.get("/api/alerts?limit=2").json()["unread_count"] == 4
    assert len(client.get("/api/alerts?limit=2").json()["alerts"]) == 2
    response = client.post("/api/alerts/read-all")
    assert response.status_code == 200
    assert response.json()["marked"] == 4
    assert client.get("/api/alerts").json()["unread_count"] == 0


def test_alerts_are_upgraded_in_existing_database_without_losing_application_history(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "applications.db"
    monkeypatch.setattr(tracker, "DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE vacancies(
                id TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT,
                source TEXT, url TEXT, apply_url TEXT, description TEXT, status TEXT,
                readiness TEXT, package_status TEXT, metadata_json TEXT, match_json TEXT,
                package_json TEXT, documents_json TEXT, discovered_at TEXT, updated_at TEXT);
            CREATE TABLE scan_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT,
                message TEXT, started_at TEXT, finished_at TEXT, result_json TEXT, created_at TEXT);
            INSERT INTO vacancies(id,title,company,status,metadata_json,match_json)
                VALUES('historic','Medical Officer','Employer','APPLIED_MANUALLY','{}','{}');
            """
        )
    assert list_alerts()["alerts"] == []
    assert tracker.get_job_by_id("historic")["status"] == "APPLIED_MANUALLY"


def test_monitor_schedule_is_explicit_opt_in_and_respects_api_validation(client, monkeypatch):
    monkeypatch.setattr(server, "schedule_status", lambda: {"supported": True, "enabled": False, "time": "09:00"})
    changes = []

    def fake_schedule(enabled):
        changes.append(enabled)
        return {"supported": True, "enabled": enabled, "time": "09:00"}

    monkeypatch.setattr(server, "set_schedule", fake_schedule)
    assert client.get("/api/monitor/schedule").json()["enabled"] is False
    assert changes == []
    for payload in ({}, {"enabled": 1}, {"enabled": "yes"}, []):
        assert client.post("/api/monitor/schedule", json=payload).status_code == 400
    response = client.post("/api/monitor/schedule", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert changes == [True]
    assert client.post("/api/monitor/schedule", json={"enabled": False}).json()["enabled"] is False
    assert changes == [True, False]


def test_daily_check_scheduler_is_not_claimed_on_other_operating_systems():
    import os
    if os.name != "nt":
        assert schedule_status()["supported"] is False


def test_cross_process_scan_guard_rejects_simultaneous_scans(client):
    with exclusive_scan(), pytest.raises(ScanAlreadyRunning), exclusive_scan():
        raise AssertionError("Should never enter a second scan")


def test_shipped_ui_offers_visible_alerts_and_daily_monitor_controls():
    from utils.paths import PROJECT_ROOT

    html = (PROJECT_ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "dashboard/static/app.js").read_text(encoding="utf-8")
    ps = (PROJECT_ROOT / "tools/windows_daily_check.ps1").read_text(encoding="utf-8")
    assert 'id="alertsList"' in html
    assert 'id="monitoringSchedule"' in html
    assert 'id="alertNavCount"' in html
    assert "toggle-daily-check" in js
    assert "mark-all-alerts-read" not in js  # only real, wired action names
    assert "read-all-alerts" in js
    assert "New-ScheduledTaskTrigger -Daily" in ps
    assert "New-ScheduledTaskPrincipal" in ps
    assert "monitor-once" in ps
    assert "Submit" not in ps
