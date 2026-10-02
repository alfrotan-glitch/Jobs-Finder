from pathlib import Path

from utils import tracker
from utils.discovery import Job


def test_tracker_simple_status_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    job = Job("j1", "Medical Officer", "Org", "Kabul", "https://example.org", "hr@example.org", "test", metadata={})
    tracker.log_discovered(job)
    tracker.log_medical_match("j1", {"readiness_status": "READY_TO_APPLY", "counts": {}})
    tracker.update_tailored_resume("j1", {"application_package": {"application_route": "hr@example.org"}, "generated_paths": {}})

    stored = tracker.get_job_by_id("j1")
    assert stored["status"] == tracker.PACKAGE_READY
    assert stored["package"]["application_route"] == "hr@example.org"
    ok, message = tracker.mark_applied_manually("j1", confirmation="APPLIED j1")
    assert ok, message
    assert tracker.get_job_by_id("j1")["status"] == tracker.APPLIED_MANUALLY


def test_launcher_is_one_safe_canonical_runtime():
    text = Path("run_jobs_finder.bat").read_text(encoding="utf-8").lower()

    assert "%~dp0" in text
    assert ".venv" in text
    assert "requirements.txt" in text
    assert "%main_py%\" server --host" in text
    assert "http://localhost:%port%" in text
    assert "playwright" not in text
    assert "jobspy" not in text
    assert "main.py watch" not in text
    assert "main.py find" not in text
    assert "background scanning: disabled" in text
    assert "port %port% is already in use" in text


def test_requirements_are_lightweight():
    requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()
    assert "python-jobspy" not in requirements
    assert "numpy" not in requirements
    assert "playwright" not in requirements
    assert "apscheduler" not in requirements


def test_package_needs_input_status_is_distinct_from_package_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    job = Job("j2", "Medical Officer", "Org", "Kabul", "https://example.org", "", "test", metadata={})
    tracker.log_discovered(job)
    tracker.update_tailored_resume(
        "j2",
        {"application_package": {"application_route": "", "package_status": "NEEDS_USER_INPUT", "missing_items": ["Application contact details"]}, "generated_paths": {}},
    )

    stored = tracker.get_job_by_id("j2")
    assert stored["status"] == tracker.PACKAGE_NEEDS_INPUT
    assert stored["status"] != tracker.PACKAGE_READY
    assert stored["package_status"] == "NEEDS_USER_INPUT"


def test_package_ready_for_review_maps_to_package_ready_status(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    job = Job("j3", "Medical Officer", "Org", "Kabul", "https://example.org", "hr@example.org", "test", metadata={})
    tracker.log_discovered(job)
    tracker.update_tailored_resume(
        "j3",
        {"application_package": {"application_route": "hr@example.org", "package_status": "READY_FOR_REVIEW"}, "generated_paths": {}},
    )

    stored = tracker.get_job_by_id("j3")
    assert stored["status"] == tracker.PACKAGE_READY
    assert stored["package_status"] == "READY_FOR_REVIEW"


def test_new_vacancy_defaults_to_not_created_package_status(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    job = Job("j4", "Medical Officer", "Org", "Kabul", "https://example.org", "hr@example.org", "test", metadata={})
    tracker.log_discovered(job)
    stored = tracker.get_job_by_id("j4")
    assert stored["package_status"] == "NOT_CREATED"


def test_unknown_source_is_not_listed_as_actionable_job(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    unknown = Job("bad", "Medical Officer", "Org", "Kabul", "https://example.org/bad", "hr@example.org", "UNKNOWN", metadata={"source_name": "UNKNOWN"})
    valid = Job("good", "Medical Officer", "Org", "Kabul", "https://example.org/good", "hr@example.org", "ACBAR", metadata={"source_name": "ACBAR", "source_url": "https://example.org/jobs", "vacancy_url": "https://example.org/good", "application_method": "email"})
    tracker.log_discovered(unknown)
    tracker.log_discovered(valid)
    assert [job["id"] for job in tracker.list_actionable_jobs()] == ["good"]
