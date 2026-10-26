"""Offline handover must never claim that automated checks prove production."""
from __future__ import annotations

from pathlib import Path

from tools.release_readiness import _check_database, _smoke_documents, collect_readiness


def test_release_readiness_report_stays_conservative_and_pii_free():
    result = collect_readiness()
    assert result["decision"] in {"HOLD", "READY_FOR_WINDOWS_UAT_NOT_PRODUCTION"}
    assert result["checks"]["documents"]["status"] == "PASS"
    assert result["checks"]["github_visibility"]["status"] == "WARN"
    assert result["checks"]["windows_browser_uat"]["status"] == "WARN"
    assert result["checks"]["private_references"]["status"] == "WARN"
    for banned in ("referee@example.org", "0794357509", "password="):
        assert banned not in str(result)


def test_read_only_db_check_never_creates_a_missing_database(tmp_path):
    db = tmp_path / "applications.db"
    report = _check_database(db)
    assert report["status"] == "WARN"
    assert not db.exists()


def test_renderer_smoke_is_safe_and_uses_only_fictional_data():
    result = _smoke_documents()
    assert result["status"] == "PASS", result


def test_windows_readiness_launcher_is_explicit_and_safe():
    launcher = Path("Check_Jobs_Finder_Readiness.bat").read_text(encoding="utf-8")
    assert "tools\\release_readiness.py" in launcher
    assert "run_jobs_finder.bat" in launcher
    assert "git pull" not in launcher.lower()
    assert "apply" not in launcher.lower()
