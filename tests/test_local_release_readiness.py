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


def test_local_readiness_detects_stale_owner_profile_without_destroying_data(monkeypatch):
    from tools import release_readiness
    from utils import profile as repository

    current = repository.load_canonical_profile(required=True)
    stale = dict(current)
    stale.pop("official_cv_approval", None)
    monkeypatch.setattr(release_readiness, "_smoke_documents", lambda: {"status":"PASS","detail":"Synthetic."})
    monkeypatch.setattr(repository, "load_canonical_profile", lambda *, required: stale)
    result = release_readiness.collect_readiness()
    assert result["checks"]["profile"]["status"] == "BLOCK"
    assert "OLD LOCAL PROFILE DETECTED" in result["checks"]["profile"]["detail"]


def test_owner_official_cv_status_is_visible_in_dashboard():
    from dashboard.server import _profile_details
    from utils.profile import load_canonical_profile

    profile = load_canonical_profile(required=True)
    result = _profile_details(profile)["official_cv_status"]
    assert result["owner_approved"] is True
    assert result["verified_duty_count"] == 24
    assert result["expected_duty_count"] == 24
    assert result["complete"] is True
