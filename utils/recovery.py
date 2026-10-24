"""Recover a verified backup into a *new*, runnable Jobs-Finder folder.

Never overwrite the current installation, active SQLite database, user
profile, or documents. Recovered data is staged and checked before an atomic
directory rename. This works while the original dashboard is open.
"""

from __future__ import annotations

import io
import json
import secrets
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

from utils.backups import BackupError, verify_backup_archive
from utils.paths import PROJECT_ROOT

# Copy executable app sources, not old caches, database, generated documents,
# .git or another project's local state. Profile and documents come from ZIP.
RUNTIME_FILES = (
    "main.py", "requirements.txt", "run_jobs_finder.bat",
    "Restore_Jobs_Finder_Backup.bat", "README.md", "profile.yaml.example",
    "pyproject.toml",
)
RUNTIME_DIRS = ("dashboard", "utils", "tools")
DOCUMENT_DIRS = ("documents", "resumes", "generated")


def _reject_runtime_entry(path: Path) -> bool:
    """Do not follow symlinks, caches or files held outside code roots."""
    return (
        path.is_symlink()
        or path.name in {"__pycache__", ".pytest_cache", ".venv", ".git"}
        or path.suffix in {".pyc", ".pyo"}
    )


def _copy_runtime_sources(source_root: Path, destination: Path) -> None:
    for name in RUNTIME_FILES:
        source = source_root / name
        if not source.is_file() or source.is_symlink():
            if name in {"main.py", "requirements.txt", "run_jobs_finder.bat"}:
                raise BackupError(f"Required program file is unavailable: {name}")
            continue
        shutil.copy2(source, destination / name)
    for folder in RUNTIME_DIRS:
        source = source_root / folder
        if not source.is_dir() or source.is_symlink():
            raise BackupError(f"Required program component is unavailable: {folder}")
        # Each subtree is examined before being copied, so no symlink is
        # dereferenced and no generated/cache data is collected.
        for item in sorted(source.rglob("*")):
            if _reject_runtime_entry(item) or any(_reject_runtime_entry(p) for p in item.relative_to(source).parents if p != Path(".")):
                continue
            relative = item.relative_to(source)
            target = destination / folder / relative
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif item.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)


def _relink_document_value(value: object, destination: Path, members: tuple[str, ...]) -> tuple[object, int]:
    """Move only paths to archived document members; never rewrite URLs/text."""
    if isinstance(value, dict):
        transformed: dict[str, object] = {}
        updates = 0
        for key, entry in value.items():
            transformed[key], count = _relink_document_value(entry, destination, members)
            updates += count
        return transformed, updates
    if isinstance(value, list):
        result: list[object] = []
        updates = 0
        for entry in value:
            edited, count = _relink_document_value(entry, destination, members)
            result.append(edited)
            updates += count
        return result, updates
    if not isinstance(value, str) or "://" in value:
        return value, 0
    normalized = value.replace("\\", "/").strip()
    if not normalized:
        return value, 0
    for member in members:
        # Only a real backed-up file path, not an arbitrary suffix match.
        # Require either exact relative name or the '/documents/...' boundary.
        if normalized.casefold() == member.casefold() or normalized.casefold().endswith("/" + member.casefold()):
            new_path = str(destination.joinpath(*member.split("/")))
            return (new_path, 1) if new_path != value else (value, 0)
    return value, 0


def _relink_sqlite_documents(path: Path, destination: Path, member_names: tuple[str, ...]) -> tuple[int, int]:
    """Rebase saved absolute document paths after recovery into another folder."""
    documents = tuple(sorted(
        (name for name in member_names if name.startswith(DOCUMENT_DIRS)),
        key=len, reverse=True,
    ))
    updated_records = 0
    updated_paths = 0
    with closing(sqlite3.connect(str(path), timeout=10)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute("SELECT id, documents_json, package_json FROM vacancies").fetchall()
        for job_id, docs_raw, package_raw in rows:
            new_values: list[str] = []
            changes = 0
            for raw in (docs_raw, package_raw):
                if not raw:
                    new_values.append(raw)
                    continue
                try:
                    parsed = json.loads(raw)
                except (ValueError, TypeError):
                    new_values.append(raw)
                    continue
                rewritten, count = _relink_document_value(parsed, destination, documents)
                new_values.append(json.dumps(rewritten, ensure_ascii=False) if count else raw)
                changes += count
            if changes:
                conn.execute(
                    "UPDATE vacancies SET documents_json=?, package_json=? WHERE id=?",
                    (new_values[0], new_values[1], job_id),
                )
                updated_records += 1
                updated_paths += changes
        check = conn.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != "ok":
            raise BackupError("The recovered database failed integrity checks after relinking.")
        conn.commit()
    # Force SQLite journal into the DB to avoid mismatching a separate WAL.
    with closing(sqlite3.connect(str(path))) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
    return updated_records, updated_paths


def recover_backup_to_new_installation(
    archive_path: str | Path, *,
    source_root: Path = PROJECT_ROOT,
    destination_parent: Path | None = None,
) -> dict[str, object]:
    """Create an independent runnable installation, leaving old files intact.

    No arbitrary destination path from the ZIP is trusted. No archive is
    extracted with extractall. A temporary sibling directory is atomically
    renamed only when all files + the resulting database check out.
    """
    archive_file = Path(archive_path).expanduser().resolve(strict=True)
    source_root = Path(source_root).resolve(strict=True)
    parent = Path(destination_parent).resolve(strict=True) if destination_parent else source_root.parent
    if not parent.is_dir() or parent.is_symlink():
        raise BackupError("The selected recovery parent is not a safe directory.")
    try:
        data = archive_file.read_bytes()
        report = verify_backup_archive(data)
    except OSError as exc:
        raise BackupError("The selected ZIP could not be read.") from exc

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    destination = parent / f"{source_root.name}-Recovered-{stamp}-{secrets.token_hex(3)}"
    staging = Path(tempfile.mkdtemp(prefix=".jobs-finder-recovery-", dir=parent))
    finalized = False
    try:
        _copy_runtime_sources(source_root, staging)
        with ZipFile(io.BytesIO(data), "r") as archive:
            member_names = tuple(name for name in archive.namelist() if name != "manifest.json")
            # verify_backup_archive independently checked all names, hashes,
            # directory/symlink flags, lengths and the DB before we got here.
            for name in member_names:
                target = staging.joinpath(*name.split("/"))
                if not target.resolve().is_relative_to(staging.resolve()):
                    raise BackupError("Unsafe path in backup archive.")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
        database = staging / "applications.db"
        if not database.is_file() or not (staging / "profile.yaml").is_file():
            raise BackupError("Required profile/database is missing from the recovered folder.")
        records, links = _relink_sqlite_documents(database, destination, member_names)
        if destination.exists():
            raise BackupError("The recovery destination already exists. Nothing was overwritten.")
        staging.rename(destination)
        finalized = True
        return {
            "success": True,
            "recovered_folder": str(destination),
            "vacancies": report["vacancies_saved"],
            "submitted_applications": report["applications_submitted_saved"],
            "files_verified": report["files_verified"],
            "records_relinked": records,
            "paths_relinked": links,
            "original_untouched": True,
            "message": "An independent copy is ready. Open run_jobs_finder.bat inside the recovered folder; your original installation was not changed.",
        }
    except (OSError, sqlite3.Error) as exc:
        raise BackupError("Recovery failed; your original Jobs-Finder folder was not changed.") from exc
    finally:
        if not finalized:
            shutil.rmtree(staging, ignore_errors=True)
