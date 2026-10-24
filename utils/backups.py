"""Explicit, local-only export of the user's actual Jobs-Finder work.

Backups use SQLite's online backup API so a WAL database is never copied
while its sidecar is inconsistent. Documents are read as bytes, never parsed
or sent to external services. No private reference file or secrets are
searched for outside the canonical project directories.
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import stat
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from utils import tracker
from utils.paths import PROJECT_ROOT

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_INPUT_BYTES = 128 * 1024 * 1024
MAX_DOCUMENT_FILES = 2500


class BackupError(RuntimeError):
    """A complete verified local export could not be safely created."""


def backup_archive() -> tuple[str, bytes]:
    """Produce a complete point-in-time data export; never modify the source.

    A zip contains the canonical profile, a coherent applications.db snapshot,
    generated application documents, and an integrity manifest. A digest is
    recorded for each member to detect accidental corruption of backups.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    members: list[tuple[str, bytes]] = []
    total_bytes = 0

    def append_file(name: str, data: bytes) -> None:
        nonlocal total_bytes
        if len(data) > MAX_FILE_BYTES:
            raise BackupError("A file is too large for a safe portable backup.")
        total_bytes += len(data)
        if total_bytes > MAX_ARCHIVE_INPUT_BYTES:
            raise BackupError(
                "The saved documents are too large for the in-app backup limit. "
                "Make a manual copy of the project documents folder instead."
            )
        members.append((name, data))

    profile = PROJECT_ROOT / "profile.yaml"
    if not profile.is_file():
        raise BackupError("Canonical profile.yaml is missing; a complete backup cannot be made.")
    append_file("profile.yaml", profile.read_bytes())

    # Always snapshot the live database via sqlite3_backup, never copy
    # applications.db, -wal, and -shm as unrelated filesystem files.
    try:
        with tempfile.TemporaryDirectory(prefix="jobs-finder-export-") as temporary:
            snapshot = Path(temporary) / "applications.db"
            original = tracker._read_connection()
            try:
                with closing(sqlite3.connect(str(snapshot), timeout=15)) as target:
                    original.backup(target, pages=128, sleep=0.05)
                    check = target.execute("PRAGMA integrity_check").fetchone()
                    if not check or check[0] != "ok":
                        raise BackupError("The local database did not pass its integrity check.")
                append_file("applications.db", snapshot.read_bytes())
            finally:
                tracker._close_read_connection(original)
    except (OSError, sqlite3.Error) as exc:
        raise BackupError("Could not create a consistent SQLite backup; existing data was not modified.") from exc

    doc_count = 0
    for folder in ("documents", "resumes", "generated"):
        base = PROJECT_ROOT / folder
        if not base.is_dir() or base.is_symlink():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            if not path.resolve().is_relative_to(base.resolve()):
                continue
            doc_count += 1
            if doc_count > MAX_DOCUMENT_FILES:
                raise BackupError("Too many document files for one in-app export.")
            if path.stat().st_size > MAX_FILE_BYTES:
                raise BackupError("A generated document exceeds the in-app backup size limit.")
            append_file(path.relative_to(PROJECT_ROOT).as_posix(), path.read_bytes())

    manifest = {
        "format": "jobs-finder-local-data-backup",
        "version": 1,
        "created_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "note": "Private applicant data. Keep this file confidential. No private-reference contacts outside the project are included.",
        "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in members
        },
    }
    buff = io.BytesIO()
    with ZipFile(buff, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in members:
            archive.writestr(name, data)
        archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True, indent=2))
    return f"jobs-finder-backup-{stamp}.zip", buff.getvalue()


MAX_ARCHIVE_BYTES = MAX_ARCHIVE_INPUT_BYTES + (8 * 1024 * 1024)
MAX_MANIFEST_BYTES = 128 * 1024


def _trusted_backup_member(name: str) -> bool:
    """Allow only the canonical profile, DB and known project document dirs."""
    if not name or "\\" in name or name.startswith("/") or ":" in name:
        return False
    parts = PurePosixPath(name).parts
    if not parts or any(part in {"", ".", ".."} for part in name.split("/")):
        return False
    if name in {"profile.yaml", "applications.db"}:
        return True
    return len(parts) >= 2 and parts[0] in {"documents", "resumes", "generated"}


def verify_backup_archive(data: bytes) -> dict[str, object]:
    """Validate the actual archived bytes without overwriting ANY user file.

    The verification is deliberately independent from the export code:
    it checks complete manifest membership, safe archive paths, file-size
    limits, SHA256 checksums, and SQLite integrity in a fresh temporary file.
    No path inside the archive is extracted to an arbitrary destination.
    """
    if not data or len(data) > MAX_ARCHIVE_BYTES:
        raise BackupError("Backup ZIP is empty or exceeds the safe archive limit.")
    try:
        with ZipFile(io.BytesIO(data), "r") as archive:
            names = archive.namelist()
            if not names or len(names) != len(set(names)):
                raise BackupError("Backup contains duplicate file names or is empty.")
            if "manifest.json" not in names or len(names) > MAX_DOCUMENT_FILES + 3:
                raise BackupError("Backup manifest is missing or archive contains too many files.")
            manifest_info = archive.getinfo("manifest.json")
            if manifest_info.file_size > MAX_MANIFEST_BYTES:
                raise BackupError("Backup manifest is too large.")
            manifest = json.loads(archive.read(manifest_info))
            if not isinstance(manifest, dict) or (
                manifest.get("format") != "jobs-finder-local-data-backup"
                or manifest.get("version") != 1
            ):
                raise BackupError("This is not a supported Jobs-Finder backup.")
            records = manifest.get("files")
            if not isinstance(records, dict) or not {"profile.yaml", "applications.db"}.issubset(records):
                raise BackupError("Backup is missing its profile or application database.")
            if set(names) != set(records) | {"manifest.json"}:
                raise BackupError("Backup contents do not match its integrity manifest.")
            total_size = 0
            for name, expected in records.items():
                if not isinstance(name, str) or not _trusted_backup_member(name):
                    raise BackupError("Backup contains an unsafe file path.")
                if not isinstance(expected, dict):
                    raise BackupError("Backup integrity manifest is malformed.")
                info = archive.getinfo(name)
                if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                    raise BackupError("Backup contains a directory or symbolic link.")
                if info.file_size > MAX_FILE_BYTES:
                    raise BackupError("Backup member exceeds the safe size limit.")
                total_size += info.file_size
                if total_size > MAX_ARCHIVE_INPUT_BYTES:
                    raise BackupError("Backup exceeds the total safe data limit.")
                if type(expected.get("bytes")) is not int or expected["bytes"] != info.file_size:
                    raise BackupError("Backup file length differs from its manifest.")
                digest = expected.get("sha256")
                if not isinstance(digest, str) or len(digest) != 64:
                    raise BackupError("Backup integrity manifest is malformed.")
                if hashlib.sha256(archive.read(info)).hexdigest() != digest:
                    raise BackupError("Backup has damaged or altered files.")
            with tempfile.TemporaryDirectory(prefix="jobs-finder-verify-") as temporary:
                snapshot = Path(temporary) / "snapshot.db"
                snapshot.write_bytes(archive.read("applications.db"))
                try:
                    with closing(sqlite3.connect(str(snapshot))) as conn:
                        result = conn.execute("PRAGMA integrity_check").fetchone()
                        if result is None or result[0] != "ok":
                            raise BackupError("Backup application database failed its integrity check.")
                        required = {"vacancies", "scan_runs", "job_alerts", "seen_recommendations"}
                        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                        if not required.issubset(tables):
                            raise BackupError("Backup application database is missing required tables.")
                        vacancies = int(conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0])
                        applied = int(conn.execute(
                            "SELECT COUNT(*) FROM vacancies WHERE status='APPLIED_MANUALLY'"
                        ).fetchone()[0])
                except sqlite3.Error as exc:
                    raise BackupError("Backup application database could not be opened or validated.") from exc
            return {
                "valid": True,
                "created_at_utc": manifest.get("created_at_utc") or "",
                "files_verified": len(records),
                "vacancies_saved": vacancies,
                "applications_submitted_saved": applied,
                "database_integrity": "ok",
                "safe_to_restore_automatically": False,
                "message": "Backup checked successfully. Keep it private. Verification does not restore or overwrite files.",
            }
    except (BadZipFile, OSError, EOFError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise BackupError("The supplied file is not a complete, readable Jobs-Finder backup ZIP.") from exc
