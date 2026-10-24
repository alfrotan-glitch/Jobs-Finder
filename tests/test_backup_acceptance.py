"""Backup assurance, restore safety, and scheduler ownership regressions."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient

from dashboard import server
from utils import backups, tracker, windows_schedule


@pytest.fixture
def private_export(tmp_path, monkeypatch):
    monkeypatch.setattr(backups, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "applications.db")
    (tmp_path / "profile.yaml").write_text("personal:\n  first_name: Verified\n", encoding="utf-8")
    files = tmp_path / "documents" / "applications"
    files.mkdir(parents=True)
    (files / "CV.txt").write_text("PRIVATE resume", encoding="utf-8")
    conn = tracker.get_db()
    conn.execute(
        "INSERT INTO vacancies(id,title,company,status) VALUES(?,?,?,?)",
        ("submitted", "Medical Officer", "Verified NGO", tracker.APPLIED_MANUALLY),
    )
    conn.commit()
    conn.close()
    name, raw = backups.backup_archive()
    return tmp_path, name, raw


def _repack(archive_bytes, *, mutate):
    with ZipFile(io.BytesIO(archive_bytes)) as archive:
        content = {name: archive.read(name) for name in archive.namelist()}
    mutate(content)
    bio = io.BytesIO()
    with ZipFile(bio, "w", ZIP_DEFLATED) as archive:
        for name, data in content.items():
            archive.writestr(name, data)
    return bio.getvalue()


def test_independent_backup_verifier_reads_actual_profile_documents_and_submissions(private_export):
    root, name, raw = private_export
    report = backups.verify_backup_archive(raw)
    assert report["valid"] is True
    assert report["files_verified"] == 3
    assert report["vacancies_saved"] == 1
    assert report["applications_submitted_saved"] == 1
    assert report["database_integrity"] == "ok"
    assert report["safe_to_restore_automatically"] is False
    assert (root / "profile.yaml").read_text(encoding="utf-8").startswith("personal:")
    assert (root / "documents" / "applications" / "CV.txt").read_text(encoding="utf-8") == "PRIVATE resume"


def test_tampered_profile_fails_integrity_without_touching_original(private_export):
    root, _, raw = private_export
    tampered = _repack(raw, mutate=lambda parts: parts.__setitem__("profile.yaml", b"ATTACKED"))
    with pytest.raises(backups.BackupError, match="damaged or altered"):
        backups.verify_backup_archive(tampered)
    assert "Verified" in (root / "profile.yaml").read_text(encoding="utf-8")


def test_corrupt_sqlite_is_rejected_even_when_hashes_match(private_export):
    _, _, raw = private_export

    def corrupt(parts):
        parts["applications.db"] = b"not a SQLite database"
        manifest = json.loads(parts["manifest.json"])
        manifest["files"]["applications.db"] = {
            "bytes": len(parts["applications.db"]),
            "sha256": hashlib.sha256(parts["applications.db"]).hexdigest(),
        }
        parts["manifest.json"] = json.dumps(manifest).encode()

    damaged = _repack(raw, mutate=corrupt)
    with pytest.raises(backups.BackupError, match="database"):
        backups.verify_backup_archive(damaged)


@pytest.mark.parametrize(
    "badname",
    ["../outside.txt", "/etc/secrets.txt", "documents/../../secrets", "documents\\escape.txt", "C:/temp/secrets"],
)
def test_traversal_and_unexpected_archive_members_rejected(private_export, badname):
    _, _, raw = private_export

    def inject(parts):
        parts[badname] = b"not a trustworthy generated file"
        manifest = json.loads(parts["manifest.json"])
        manifest["files"][badname] = {
            "bytes": len(parts[badname]),
            "sha256": hashlib.sha256(parts[badname]).hexdigest(),
        }
        parts["manifest.json"] = json.dumps(manifest).encode()

    evil = _repack(raw, mutate=inject)
    with pytest.raises(backups.BackupError, match="unsafe file path"):
        backups.verify_backup_archive(evil)


def test_missing_member_and_broken_archives_are_rejected(private_export):
    _, _, raw = private_export
    with pytest.raises(backups.BackupError, match="readable"):
        backups.verify_backup_archive(b"not a zip file")

    def drop_file(parts):
        parts.pop("profile.yaml")

    with pytest.raises(backups.BackupError, match="contents do not match"):
        backups.verify_backup_archive(_repack(raw, mutate=drop_file))


def test_user_initiated_zip_validation_is_safe_and_has_no_restore_route(private_export):
    root, _, raw = private_export
    client = TestClient(server.app)
    before = (root / "applications.db").read_bytes()
    assert client.get("/api/backup/verify").status_code == 405
    response = client.post("/api/backup/verify", files={"file": ("jobs-finder-backup.zip", raw, "application/zip")})
    assert response.status_code == 200
    assert response.json()["files_verified"] == 3
    assert response.json()["safe_to_restore_automatically"] is False
    assert client.post("/api/backup/verify", files={"file": ("wrong.txt", raw, "text/plain")}).status_code == 400
    assert client.post("/api/backup/verify", files={"file": ("bad.zip", b"broken", "application/zip")}).status_code == 422
    assert (root / "applications.db").read_bytes() == before
    assert (root / "documents" / "applications" / "CV.txt").is_file()


def test_scheduler_collision_detection_and_user_explanation(monkeypatch):
    monkeypatch.setattr(windows_schedule.os, "name", "nt")
    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "The existing daily check belongs to another Jobs-Finder checkout."
    monkeypatch.setattr(windows_schedule.subprocess, "run", lambda *args, **kwargs: FakeResult())
    with pytest.raises(windows_schedule.ScheduleError, match="different Jobs-Finder installation"):
        windows_schedule.set_schedule(True)


def test_windows_schedule_script_rejects_cross_checkout_task_mutation():
    from utils.paths import PROJECT_ROOT

    script = (PROJECT_ROOT / "tools" / "windows_daily_check.ps1").read_text(encoding="utf-8")
    assert "function Assert-OwnScheduledTask" in script
    assert script.count("Assert-OwnScheduledTask $existing") == 3
    assert "Register-ScheduledTask" in script
    assert "Unregister-ScheduledTask" in script

    if os.name != "nt":
        return
    # No real task is registered. Mock the Windows cmdlet in a child PowerShell
    # session and verify a foreign task blocks the status action.
    ps = (
        'function Get-ScheduledTask { '
        '[pscustomobject]@{ Settings=[pscustomobject]@{Enabled=$true}; '
        'Actions=@([pscustomobject]@{Execute="C:\\Another\\python.exe"; '
        'WorkingDirectory="C:\\Another"; Arguments="wrong"}) } }; '
        f'& "{PROJECT_ROOT / "tools" / "windows_daily_check.ps1"}" -Action status'
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True,
        check=False, timeout=20,
    )
    assert result.returncode != 0
    assert "another Jobs-Finder checkout" in (result.stderr + result.stdout)


def test_backup_verify_controls_exist_and_are_wired_to_real_api():
    from utils.paths import PROJECT_ROOT

    html = (PROJECT_ROOT / "dashboard" / "templates" / "index.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "dashboard" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="backupVerifyFile"' in html
    assert 'id="verifyBackupBtn"' in html
    assert "/api/backup/verify" in js
    assert "verify-backup" in js
