"""The Windows project-runtime SQLite contract.

These tests deliberately run the backend from a different working directory:
the process location must not select a second database, and a genuine
read-only database must fail with enough context to repair the runtime
rather than with a bare SQLite error.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import stat
from pathlib import Path

import pytest

import main
from dashboard import server
from utils import tracker
from utils.discovery import Job, ScanResult


def _job(job_id: str = "windows-runtime-job") -> Job:
    return Job(
        job_id,
        "Medical Officer",
        "Example Health Organisation",
        "Kabul",
        "https://example.org/jobs/1",
        "hr@example.org",
        "ACBAR",
        "A medical officer vacancy.",
        metadata={
            "source_name": "ACBAR",
            "source_url": "https://example.org/jobs",
            "vacancy_url": "https://example.org/jobs/1",
            "application_method": "email",
        },
    )


def test_normal_windows_style_cli_scan_uses_one_canonical_db_and_persists_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project-root launch must INSERT and then UPDATE the same DB.

    ``tmp_path/project`` stands in for ``C:\\Users\\...\\Jobs-Finder`` and
    ``tmp_path/other-cwd`` stands in for an arbitrary shell working directory.
    """
    project_root = tmp_path / "project"
    project_root.mkdir()
    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir()
    canonical_db = project_root / "applications.db"
    monkeypatch.setattr(tracker, "DB_PATH", canonical_db)
    monkeypatch.chdir(other_cwd)

    scan = ScanResult("SCANNED", [_job()], [], "start", "finish", "Complete")

    async def fake_discovery(profile: dict[str, object]) -> ScanResult:
        return scan

    monkeypatch.setattr(main, "run_discovery_scan", fake_discovery)
    asyncio.run(main.cmd_scan({}))

    assert canonical_db.exists()
    assert not (other_cwd / "applications.db").exists()
    with sqlite3.connect(canonical_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0] == 1
        row = conn.execute("SELECT readiness, match_json FROM vacancies WHERE id = ?", (_job().id,)).fetchone()
        assert row is not None
        assert row[0]  # the matcher outcome was persisted by UPDATE
        assert "readiness_status" in row[1]


def test_cli_and_dashboard_expose_the_same_canonical_db_path() -> None:
    """Both entry points must point at the tracker authority, not CWD."""
    expected = Path(tracker.DB_PATH).resolve()
    assert expected.is_absolute()
    assert Path(main.DB_PATH).resolve() == expected
    assert Path(server.DB_PATH).resolve() == expected


def test_default_db_path_is_cwd_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = Path(tracker.DB_PATH).resolve()
    monkeypatch.chdir(tmp_path)
    assert tracker.canonical_db_path() == expected
    assert tracker.canonical_db_path().parent == expected.parent


def test_tracker_connection_is_read_write_and_points_at_canonical_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical_db = tmp_path / "project" / "applications.db"
    canonical_db.parent.mkdir()
    monkeypatch.setattr(tracker, "DB_PATH", canonical_db)

    conn = tracker.get_db()
    try:
        database_list = conn.execute("PRAGMA database_list").fetchone()
        assert Path(database_list[2]).resolve() == canonical_db.resolve()
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 0
    finally:
        conn.close()


def test_existing_db_survives_a_cwd_change_without_a_duplicate_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    first_cwd = tmp_path / "first-cwd"
    second_cwd = tmp_path / "second-cwd"
    first_cwd.mkdir()
    second_cwd.mkdir()
    canonical_db = project_root / "applications.db"
    monkeypatch.setattr(tracker, "DB_PATH", canonical_db)

    monkeypatch.chdir(first_cwd)
    tracker.log_discovered(_job("existing-db"))
    monkeypatch.chdir(second_cwd)
    tracker.log_medical_match("existing-db", {"readiness_status": "NEEDS_VERIFICATION"})

    assert not (first_cwd / "applications.db").exists()
    assert not (second_cwd / "applications.db").exists()
    stored = tracker.get_job_by_id("existing-db")
    assert stored is not None
    assert stored["readiness"] == "NEEDS_VERIFICATION"


def test_genuine_readonly_database_has_actionable_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not hide a real Windows read-only file/ACL behind raw SQLite text."""
    canonical_db = tmp_path / "project" / "applications.db"
    canonical_db.parent.mkdir()
    monkeypatch.setattr(tracker, "DB_PATH", canonical_db)
    tracker.log_discovered(_job("readonly-db"))

    original_mode = stat.S_IMODE(canonical_db.stat().st_mode)
    try:
        # On Windows this maps to the file's READONLY attribute; on POSIX it
        # gives the same SQLite failure mode without touching user permissions.
        os.chmod(canonical_db, original_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
        with pytest.raises(tracker.TrackerDatabaseError, match=r"applications\.db") as exc_info:
            tracker.log_medical_match("readonly-db", {"readiness_status": "READY_TO_APPLY"})
        assert "read-only" in str(exc_info.value).lower()
        assert "directory" in str(exc_info.value).lower() or "attribute" in str(exc_info.value).lower()
    finally:
        os.chmod(canonical_db, original_mode)


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits do not model Windows directory ACLs")
def test_genuine_unwritable_database_directory_has_actionable_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    canonical_db = project_root / "applications.db"
    monkeypatch.setattr(tracker, "DB_PATH", canonical_db)
    tracker.log_discovered(_job("readonly-directory"))

    original_mode = stat.S_IMODE(project_root.stat().st_mode)
    try:
        os.chmod(project_root, original_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
        with pytest.raises(tracker.TrackerDatabaseError, match=r"database directory"):
            tracker.log_medical_match("readonly-directory", {"readiness_status": "READY_TO_APPLY"})
    finally:
        os.chmod(project_root, original_mode)
