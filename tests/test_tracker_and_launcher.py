from pathlib import Path

from utils.discovery import Job
from utils import tracker


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
