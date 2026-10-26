"""Older saved recommendations must get accurate package state past page 500."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from dashboard import server
from utils import tracker


@pytest.fixture
def many_vacancies(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    source_url = "https://www.acbar.org/en/jobs"
    with tracker.get_db() as conn:
        for index in range(620):
            job_id = f"recent-{index:04d}"
            url = f"https://www.acbar.org/en/jobs/details/{300000+index}/medical-officer"
            conn.execute(
                """INSERT INTO vacancies(
                    id,title,company,source,url,metadata_json,discovered_at,updated_at,status)
                    VALUES(?, 'Medical Officer', 'Example NGO', 'ACBAR', ?, ?,
                           '2026-10-26T08:00:00', '2026-10-26T08:00:00', 'FOUND')""",
                (job_id, url, json.dumps({
                    "source_name": "ACBAR", "source_url": source_url,
                    "vacancy_url": url,
                })),
            )
        old_url = "https://www.acbar.org/en/jobs/details/200000/clinical-director"
        conn.execute(
            """INSERT INTO vacancies(
                id,title,company,source,url,metadata_json,discovered_at,updated_at,
                status,readiness,package_status,package_json,documents_json)
                VALUES(?, 'Clinical Director', 'Example NGO', 'ACBAR', ?, ?,
                       '2026-10-20T08:00:00', '2026-10-20T08:00:00',
                       'PACKAGE_READY', 'READY_TO_APPLY', 'READY_FOR_REVIEW', ?, ?)""",
            (
                "old-target", old_url,
                json.dumps({"source_name": "ACBAR", "source_url": source_url, "vacancy_url": old_url}),
                json.dumps({"package_status": "READY_FOR_REVIEW", "route_type": "email"}),
                json.dumps({"generated_paths": {"tailored_cv": {"pdf": "documents/old.pdf"}}}),
            ),
        )
        conn.commit()
    return old_url


def test_selected_old_job_is_not_lost_behind_500_newer_records(many_vacancies, monkeypatch):
    assert tracker.list_actionable_jobs(limit=500)[-1]["id"] != "old-target"
    assert "old-target" in tracker.get_actionable_jobs_by_ids(["old-target"])
    monkeypatch.setattr(server, "get_latest_scan", lambda: {
        "status": "SCAN_COMPLETE", "started_at": "2026-10-26T07:00:00",
        "finished_at": "2026-10-26T08:00:00",
        "recommendations": [{
            "id": "old-target", "title": "Clinical Director",
            "company": "Example NGO", "source": "ACBAR",
            "url": many_vacancies, "metadata": {"source_name": "ACBAR", "vacancy_url": many_vacancies},
            "status": "REVIEWED",
        }],
    })
    response = TestClient(server.app).get("/api/recommended")
    assert response.status_code == 200
    result = response.json()
    assert len(result["jobs"]) == 1
    job = result["jobs"][0]
    assert job["status"] == "PACKAGE_READY"
    assert job["package"]["package_status"] == "READY_FOR_REVIEW"
    assert job["documents"]["generated_paths"]["tailored_cv"]["pdf"] == "documents/old.pdf"
    assert result["data_origin"] == "latest_saved_scan"


def test_exact_lookup_is_parameterized_deduplicated_and_handles_empty_ids(many_vacancies):
    assert tracker.get_actionable_jobs_by_ids([]) == {}
    assert list(tracker.get_actionable_jobs_by_ids(["old-target", "old-target", "missing"])) == ["old-target"]
    # A forged identifier is treated literally, not executed as SQL.
    assert tracker.get_actionable_jobs_by_ids(["x') OR 1=1 --"]) == {}


def test_launcher_cannot_bind_unprotected_dashboard_to_network():
    from pathlib import Path

    launcher = Path("run_jobs_finder.bat").read_text(encoding="utf-8")
    assert 'set "HOST=127.0.0.1"' in launcher
    assert 'set "HOST=%JOBS_FINDER_HOST%"' not in launcher
    assert '"%MAIN_PY%" server --host "%HOST%"' in launcher
