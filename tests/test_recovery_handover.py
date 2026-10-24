"""Customer acceptance tests: backup -> recovery -> runnable independent copy.

The recovered installation never overwrites the current checkout, current
canonical profile or the current SQLite WAL database.
"""

from __future__ import annotations

import io
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from zipfile import ZipFile

import pytest

from utils import backups, recovery, tracker


@pytest.fixture
def working_copy(tmp_path, monkeypatch):
    source = tmp_path / "Original Jobs-Finder"
    source.mkdir()
    for name, content in [
        ("main.py", "print('started')\n"),
        ("requirements.txt", "fastapi\n"),
        ("run_jobs_finder.bat", "@echo off\necho launched\n"),
        ("Restore_Jobs_Finder_Backup.bat", "@echo off\necho recovery\n"),
    ]:
        (source / name).write_text(content, encoding="utf-8")
    for name in ("dashboard", "utils", "tools"):
        (source / name).mkdir()
        (source / name / "example.py").write_text("VERSION = 1\n", encoding="utf-8")
    (source / "utils" / "__pycache__").mkdir()
    (source / "utils" / "__pycache__" / "bad.pyc").write_bytes(b"cache")
    (source / ".git").mkdir()
    (source / "profile.yaml").write_text("name: Original owner\n", encoding="utf-8")

    monkeypatch.setattr(backups, "PROJECT_ROOT", source)
    monkeypatch.setattr(tracker, "DB_PATH", source / "applications.db")
    doc = source / "documents" / "applications" / "medical_cv.pdf"
    doc.parent.mkdir(parents=True)
    doc.write_bytes(b"%PDF-1.4 from source")
    with tracker.get_db() as conn:
        original_absolute = r"C:\Users\OldUser\Desktop\Jobs-Finder\documents\applications\medical_cv.pdf"
        conn.execute(
            """INSERT INTO vacancies
               (id,title,company,status,documents_json,package_json)
               VALUES(?, ?, ?, ?, ?, ?)""",
            (
                "job-42", "Medical Officer", "Local Health Center", "APPLIED_MANUALLY",
                json.dumps({"generated_paths": {"tailored_cv": {"pdf": original_absolute}}}),
                json.dumps({"generated_paths": {"tailored_cv": original_absolute},
                            "online_application": {"url": "https://apply.example.org/form"}}),
            ),
        )
        conn.execute(
            """INSERT INTO job_alerts
               (dedupe_key,kind,job_id,title,message,created_at)
               VALUES('first-job','NEW_MATCH','job-42','New job','Apply carefully','2026-10-24')"""
        )
    archive_name, raw = backups.backup_archive()
    archive = tmp_path / archive_name
    archive.write_bytes(raw)
    # Simulate divergence since archive: original user's data MUST stay intact
    # and the recovered copy must use backed-up profile instead.
    (source / "profile.yaml").write_text("name: New local unsaved edit\n", encoding="utf-8")
    return source, archive, raw, doc


def test_complete_recovery_creates_new_runnable_copy_and_preserves_original(working_copy):
    source, archive, raw, document = working_copy
    original_db = source / "applications.db"
    before = original_db.read_bytes()
    report = recovery.recover_backup_to_new_installation(archive, source_root=source)
    dest = Path(report["recovered_folder"])
    assert report["success"] is True
    assert report["original_untouched"] is True
    assert dest != source and dest.parent == source.parent
    assert dest.name.startswith(source.name + "-Recovered-")
    assert (dest / "main.py").is_file()
    assert (dest / "run_jobs_finder.bat").is_file()
    assert (dest / "Restore_Jobs_Finder_Backup.bat").is_file()
    assert (dest / "utils" / "example.py").is_file()
    assert not (dest / "utils" / "__pycache__").exists()
    assert not (dest / ".git").exists()
    assert (dest / "profile.yaml").read_text(encoding="utf-8") == "name: Original owner\n"
    assert (source / "profile.yaml").read_text(encoding="utf-8") == "name: New local unsaved edit\n"
    assert document.read_bytes() == b"%PDF-1.4 from source"
    assert (dest / "documents" / "applications" / "medical_cv.pdf").read_bytes() == document.read_bytes()
    assert original_db.read_bytes() == before
    with closing(sqlite3.connect(dest / "applications.db")) as conn:
        row = conn.execute("SELECT status,documents_json,package_json FROM vacancies WHERE id='job-42'").fetchone()
        assert row[0] == "APPLIED_MANUALLY"
        expected_pdf = str(dest / "documents" / "applications" / "medical_cv.pdf")
        assert json.loads(row[1])["generated_paths"]["tailored_cv"]["pdf"] == expected_pdf
        assert json.loads(row[2])["generated_paths"]["tailored_cv"] == expected_pdf
        assert json.loads(row[2])["online_application"]["url"] == "https://apply.example.org/form"
        assert conn.execute("SELECT COUNT(*) FROM job_alerts").fetchone()[0] == 1
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert report["submitted_applications"] == 1
    assert report["records_relinked"] == 1
    assert report["paths_relinked"] == 2


def test_bad_zip_never_creates_a_recovery_folder_or_changes_original(working_copy):
    source, archive, _, _ = working_copy
    original_db = (source / "applications.db").read_bytes()
    archive.write_bytes(b"damaged data")
    with pytest.raises(backups.BackupError):
        recovery.recover_backup_to_new_installation(archive, source_root=source)
    assert not list(source.parent.glob(source.name + "-Recovered-*"))
    assert (source / "applications.db").read_bytes() == original_db


def test_missing_runtime_file_aborts_with_no_final_or_partial_install(working_copy):
    source, archive, _, _ = working_copy
    (source / "main.py").unlink()
    with pytest.raises(backups.BackupError, match="Required program file"):
        recovery.recover_backup_to_new_installation(archive, source_root=source)
    assert not list(source.parent.glob(source.name + "-Recovered-*"))
    assert not list(source.parent.glob(".jobs-finder-recovery-*"))


def test_restore_wizard_ships_and_does_not_change_existing_installation(working_copy):
    source, _, _, _ = working_copy
    # Repository's actual runnable Windows recovery scripts, not the fixture.
    from utils.paths import PROJECT_ROOT

    launcher = (PROJECT_ROOT / "Restore_Jobs_Finder_Backup.bat").read_text(encoding="utf-8")
    gui = (PROJECT_ROOT / "tools" / "restore_backup_gui.py").read_text(encoding="utf-8")
    assert "restore_backup_gui.py" in launcher
    assert "askopenfilename" in gui
    assert "askyesno" in gui
    assert "recover_backup_to_new_installation" in gui
    assert "Your original Jobs-Finder" in gui or "existing program" in gui
    assert (source / "profile.yaml").is_file()


def test_recovered_backup_is_still_readable_without_original_files(working_copy, monkeypatch):
    source, archive, _, _ = working_copy
    report = recovery.recover_backup_to_new_installation(archive, source_root=source)
    dest = Path(report["recovered_folder"])
    (source / "documents" / "applications" / "medical_cv.pdf").unlink()
    (source / "profile.yaml").unlink()
    monkeypatch.setattr(tracker, "DB_PATH", dest / "applications.db")
    assert tracker.get_job_by_id("job-42")["status"] == "APPLIED_MANUALLY"
    assert (dest / "profile.yaml").is_file()
    assert (dest / "documents" / "applications" / "medical_cv.pdf").is_file()
