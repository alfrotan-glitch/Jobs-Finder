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
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

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
