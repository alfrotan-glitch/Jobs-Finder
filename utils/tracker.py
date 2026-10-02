"""Small SQLite store for the final Jobs-Finder workflow.

The product tracks only what it needs: discovered vacancies, deterministic match
results, generated package metadata, and whether the user says they applied
manually. It is not an ATS and does not model interviews, offers, follow-ups, or
submission automation.

Three distinct concepts are tracked and must never be confused:

* Eligibility (``readiness`` column): READY_TO_APPLY / NEEDS_VERIFICATION /
  NOT_ELIGIBLE -- produced by the deterministic matcher from verified
  evidence. This never changes just because a document package was created.
* Package state (``package_status`` column): NOT_CREATED / READY_FOR_REVIEW /
  NEEDS_USER_INPUT -- the literal ``package_status`` produced by
  ``utils.documents.generate_application_package``. This reflects whether the
  generated package still has unresolved blockers (missing contact info,
  unresolved license/experience evidence, etc.), independent of eligibility.
* Application progress (``status`` column): FOUND / REVIEWED / PACKAGE_READY /
  PACKAGE_NEEDS_INPUT / APPLIED_MANUALLY / NEEDS_VERIFICATION / NOT_ELIGIBLE --
  a simple progress indicator for the Jobs/Applications views. It is
  intentionally coarse (not a full state machine) but PACKAGE_READY is never
  used when the generated package itself reports NEEDS_USER_INPUT -- that
  case uses PACKAGE_NEEDS_INPUT instead, so the UI/API never claims a package
  is ready when it still needs user input.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from utils.medical_requirements import canonical_source_fields, has_actionable_source
from utils.paths import CANONICAL_DB_PATH, PROJECT_ROOT
from utils.recommendations import is_recommendable, recommendation_rank

# Public compatibility name retained for tests and local integrations.  It is
# the one canonical database location used by both entry points.
DB_PATH = CANONICAL_DB_PATH


class TrackerDatabaseError(sqlite3.OperationalError):
    """A local database cannot be used for the requested tracker operation."""


def canonical_db_path() -> Path:
    """Return the effective absolute path, never a path relative to CWD.

    ``DB_PATH`` remains patchable for isolated tests and local embedding, but a
    relative override is still interpreted relative to the project root.  The
    production default comes from ``utils.paths.CANONICAL_DB_PATH``.
    """
    configured = Path(DB_PATH).expanduser()
    if not configured.is_absolute():
        configured = PROJECT_ROOT / configured
    return configured.resolve()


def _windows_readonly_attribute(path: Path) -> bool:
    """Detect the Windows FILE_ATTRIBUTE_READONLY bit when available."""
    try:
        attributes = int(getattr(path.stat(), "st_file_attributes", 0))
    except OSError:
        return False
    # Python exposes the value on some Windows versions, but the Windows API
    # value is stable and using the fallback keeps this import portable.
    readonly_flag = int(getattr(stat, "FILE_ATTRIBUTE_READONLY", 0x01))
    return bool(attributes & readonly_flag)


def _has_write_permission(path: Path) -> bool:
    """Best-effort ACL/mode check before SQLite produces an opaque error."""
    if not os.access(path, os.W_OK):
        return False
    if os.name != "nt":
        try:
            return bool(path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        except OSError:
            return False
    return True


def _write_problem(path: Path) -> str | None:
    """Describe a known non-writable path before opening SQLite."""
    parent = path.parent
    if not parent.exists():
        return f"the database directory does not exist: {parent}"
    if not parent.is_dir():
        return f"the database parent is not a directory: {parent}"
    if not _has_write_permission(parent):
        return f"the database directory is not writable: {parent}"
    if path.exists():
        if _windows_readonly_attribute(path):
            return f"the database file has the Windows read-only attribute: {path}"
        if not _has_write_permission(path):
            return f"the database file is not writable: {path}"
    # A WAL connection also writes these sibling files.  An old read-only
    # sidecar can therefore produce the same SQLite error even when the main
    # database file itself looks writable.
    for sidecar in (Path(f"{path}-wal"), Path(f"{path}-shm")):
        if sidecar.exists():
            if _windows_readonly_attribute(sidecar) or not _has_write_permission(sidecar):
                return f"the SQLite sidecar is not writable: {sidecar}"
    return None


def _is_readonly_sqlite_error(error: sqlite3.OperationalError) -> bool:
    message = str(error).lower()
    return any(
        phrase in message
        for phrase in (
            "readonly database",
            "read-only database",
            "unable to open database file",
            "attempt to write a readonly database",
        )
    )


def _database_error(path: Path, reason: str | BaseException) -> TrackerDatabaseError:
    detail = str(reason)
    return TrackerDatabaseError(
        "Jobs-Finder cannot write its SQLite database. "
        f"Canonical path: {path}. "
        f"Reason: {detail}. "
        "The normal runtime never uses a read-only database or a CWD-relative "
        "fallback; make this project location and its database writable for "
        "the current Windows user, or choose a writable project directory."
    )


@contextmanager
def _write_connection() -> Iterator[sqlite3.Connection]:
    """Yield a tracker connection and translate write failures with context."""
    conn = get_db()
    path = canonical_db_path()
    try:
        yield conn
    except sqlite3.OperationalError as error:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        if _is_readonly_sqlite_error(error):
            raise _database_error(path, error) from error
        raise
    finally:
        conn.close()

FOUND = "FOUND"
REVIEWED = "REVIEWED"
PACKAGE_READY = "PACKAGE_READY"
PACKAGE_NEEDS_INPUT = "PACKAGE_NEEDS_INPUT"
APPLIED_MANUALLY = "APPLIED_MANUALLY"
NEEDS_VERIFICATION = "NEEDS_VERIFICATION"
NOT_ELIGIBLE = "NOT_ELIGIBLE"

# Package-state vocabulary (kept separate from the two above).
PACKAGE_NOT_CREATED = "NOT_CREATED"
PACKAGE_READY_FOR_REVIEW = "READY_FOR_REVIEW"
PACKAGE_STATUS_NEEDS_USER_INPUT = "NEEDS_USER_INPUT"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_db() -> sqlite3.Connection:
    """Open the one project database and ensure its schema exists.

    SQLite is deliberately opened with a filesystem path, not a URI.  There is
    no ``mode=ro``, ``immutable=1``, or CWD fallback in this runtime.
    """
    path = canonical_db_path()
    problem = _write_problem(path)
    if problem:
        raise _database_error(path, problem)

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        # WAL needs the containing directory for its -wal/-shm files.  The
        # preflight above therefore checks both an existing DB and its parent.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vacancies (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT DEFAULT '',
                source TEXT DEFAULT '',
                url TEXT DEFAULT '',
                apply_url TEXT DEFAULT '',
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'FOUND',
                readiness TEXT DEFAULT '',
                package_status TEXT DEFAULT 'NOT_CREATED',
                metadata_json TEXT DEFAULT '{}',
                match_json TEXT DEFAULT '',
                package_json TEXT DEFAULT '',
                documents_json TEXT DEFAULT '',
                discovered_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT ''
            )
            """
        )
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(vacancies)").fetchall()}
        if "package_status" not in existing_columns:
            conn.execute("ALTER TABLE vacancies ADD COLUMN package_status TEXT DEFAULT 'NOT_CREATED'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_status ON vacancies(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_readiness ON vacancies(readiness)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                message TEXT DEFAULT '',
                started_at TEXT DEFAULT '',
                finished_at TEXT DEFAULT '',
                result_json TEXT NOT NULL,
                created_at TEXT DEFAULT ''
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scan_runs_created ON scan_runs(created_at)")
        conn.commit()
        return conn
    except sqlite3.Error as error:
        if conn is not None:
            conn.close()
        if isinstance(error, sqlite3.OperationalError) and _is_readonly_sqlite_error(error):
            raise _database_error(path, error) from error
        raise


def _to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for column in ["metadata_json", "match_json", "package_json", "documents_json"]:
        key = column.replace("_json", "")
        raw = data.pop(column, "")
        data[key] = _json(raw)
    data["metadata_json"] = json.dumps(data.get("metadata") or {}, ensure_ascii=False)
    data["match_json"] = json.dumps(data.get("match") or {}, ensure_ascii=False)
    data["package_json"] = json.dumps(data.get("package") or {}, ensure_ascii=False)
    data["documents_json"] = json.dumps(data.get("documents") or {}, ensure_ascii=False)
    # Backward-compatible aliases used by document generation and older views.
    data["platform"] = data.get("source", "")
    data["company"] = data.get("company", "")
    metadata = data.get("metadata") or {}
    data["apply_email"] = metadata.get("apply_email") or metadata.get("application_email") or ""
    data["application_method"] = metadata.get("application_method") or "UNAVAILABLE"
    return data


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _job_dict(job: Any) -> dict[str, Any]:
    return job.to_dict() if hasattr(job, "to_dict") else dict(job)


def log_scan_result(result: Any) -> int:
    """Persist one backend-authoritative discovery scan summary."""
    data = result.to_dict() if hasattr(result, "to_dict") else dict(result or {})
    timestamp = now_iso()
    with _write_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO scan_runs (status, message, started_at, finished_at, result_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(data.get("status") or ""),
                str(data.get("message") or ""),
                str(data.get("started_at") or ""),
                str(data.get("finished_at") or ""),
                json.dumps(data, ensure_ascii=False),
                timestamp,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def _scan_row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    result = _json(data.pop("result_json", ""))
    if result:
        result.setdefault("scan_id", data.get("id"))
        result.setdefault("created_at", data.get("created_at"))
        return result
    return {
        "scan_id": data.get("id"),
        "status": data.get("status", ""),
        "message": data.get("message", ""),
        "started_at": data.get("started_at", ""),
        "finished_at": data.get("finished_at", ""),
        "created_at": data.get("created_at", ""),
        "source_reports": [],
        "jobs": [],
        "job_count": 0,
    }


def get_latest_scan() -> dict[str, Any] | None:
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()
        return _scan_row_to_dict(row)
    finally:
        conn.close()


def list_recent_scans(limit: int = 10) -> list[dict[str, Any]]:
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [scan for row in rows if (scan := _scan_row_to_dict(row)) is not None]
    finally:
        conn.close()


def readiness_to_status(readiness: str) -> str:
    value = str(readiness or "").upper()
    if value == "NOT_ELIGIBLE":
        return NOT_ELIGIBLE
    if value == "NEEDS_VERIFICATION":
        return NEEDS_VERIFICATION
    return REVIEWED


def log_discovered(job: Any) -> None:
    data = _job_dict(job)
    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = _json(metadata)
    source = canonical_source_fields(data)
    metadata.update(
        {
            "source_name": source.get("source_name") or metadata.get("source_name") or metadata.get("source") or data.get("platform") or "",
            "source_url": source.get("source_url") or metadata.get("source_url") or "",
            "vacancy_url": source.get("vacancy_url") or data.get("url") or "",
            "apply_url": source.get("apply_url") or None,
            "apply_email": source.get("apply_email") or metadata.get("apply_email") or metadata.get("application_email") or "",
            "application_method": source.get("application_method") or metadata.get("application_method") or "UNAVAILABLE",
            "source_valid": source.get("source_valid"),
            "source_problems": source.get("problems") or [],
        }
    )
    timestamp = now_iso()
    with _write_connection() as conn:
        conn.execute(
            """
            INSERT INTO vacancies
            (id, title, company, location, source, url, apply_url, description, status,
             metadata_json, discovered_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title=excluded.title,
              company=excluded.company,
              location=excluded.location,
              source=excluded.source,
              url=excluded.url,
              apply_url=excluded.apply_url,
              description=excluded.description,
              metadata_json=excluded.metadata_json,
              updated_at=excluded.updated_at
            """,
            (
                data.get("id"),
                data.get("title") or "Untitled vacancy",
                data.get("company") or "Unknown employer",
                data.get("location") or "",
                source.get("source_name") or data.get("platform") or metadata.get("source") or "",
                source.get("vacancy_url") or data.get("url") or "",
                source.get("apply_url") or "",
                data.get("description") or "",
                FOUND,
                json.dumps(metadata, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        conn.commit()


def log_medical_match(job_id: str, report: dict[str, Any]) -> None:
    readiness = str(report.get("readiness_status") or "")
    status = readiness_to_status(readiness)
    with _write_connection() as conn:
        conn.execute(
            "UPDATE vacancies SET match_json=?, readiness=?, status=?, updated_at=? WHERE id=?",
            (json.dumps(report, ensure_ascii=False), readiness, status, now_iso(), job_id),
        )
        conn.commit()


def update_tailored_resume(job_id: str, documents: dict[str, Any]) -> None:
    """Store a generated application package and reflect its real state.

    The ``status`` column must never claim PACKAGE_READY when the generated
    package itself reports ``NEEDS_USER_INPUT`` -- that case is recorded as
    PACKAGE_NEEDS_INPUT instead, and the literal package_status is also
    stored in its own column so callers never have to guess.
    """
    package = documents.get("application_package") or {}
    package_status = str(package.get("package_status") or PACKAGE_READY_FOR_REVIEW)
    status = PACKAGE_NEEDS_INPUT if package_status == PACKAGE_STATUS_NEEDS_USER_INPUT else PACKAGE_READY
    with _write_connection() as conn:
        conn.execute(
            "UPDATE vacancies SET documents_json=?, package_json=?, package_status=?, status=?, updated_at=? WHERE id=?",
            (
                json.dumps(documents, ensure_ascii=False),
                json.dumps(package, ensure_ascii=False),
                package_status,
                status,
                now_iso(),
                job_id,
            ),
        )
        conn.commit()


def mark_applied_manually(job_id: str, *, confirmation: str = "") -> tuple[bool, str]:
    job = get_job_by_id(job_id)
    if not job:
        return False, "Vacancy not found."
    if confirmation != f"APPLIED {job_id}":
        return False, f"Explicit confirmation required: type APPLIED {job_id}."
    if job.get("readiness") == "NOT_ELIGIBLE":
        return False, "Cannot mark a NOT_ELIGIBLE vacancy as applied."
    with _write_connection() as conn:
        conn.execute("UPDATE vacancies SET status=?, updated_at=? WHERE id=?", (APPLIED_MANUALLY, now_iso(), job_id))
        conn.commit()
    return True, "Recorded as applied manually."


def get_job_by_id(job_id: str) -> dict[str, Any] | None:
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM vacancies WHERE id=?", (job_id,)).fetchone()
        return _to_dict(row)
    finally:
        conn.close()


def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM vacancies ORDER BY discovered_at DESC, updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_to_dict(row) for row in rows if row is not None]
    finally:
        conn.close()


def _is_actionable_market_job(job: dict[str, Any]) -> bool:
    return has_actionable_source(job)


def list_actionable_jobs(limit: int = 100) -> list[dict[str, Any]]:
    return [job for job in list_jobs(limit=limit * 3) if _is_actionable_market_job(job)][:limit]


def get_recommended_jobs(limit: int = 20) -> list[dict[str, Any]]:
    """Stored-history view of recommendations.

    The gate and the ordering come from the single recommendation authority
    (utils/recommendations.py), exactly as for scan-time recommendations:
    readiness in {READY_TO_APPLY, NEEDS_VERIFICATION} AND a positively
    compatible professional-role classification. Generic roles kept in broad
    discovery (ambiguous health wording, non-medical families) never pass.
    """
    jobs = [job for job in list_actionable_jobs(limit=500) if is_recommendable(job, job.get("match") or {})]
    jobs.sort(key=recommendation_rank)
    return jobs[:limit]


def delete_all() -> int:
    with _write_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
        conn.execute("DELETE FROM vacancies")
        conn.execute("DELETE FROM scan_runs")
        conn.commit()
        return int(count)


def stats() -> dict[str, int]:
    conn = get_db()
    try:
        rows = conn.execute("SELECT status, COUNT(*) FROM vacancies GROUP BY status").fetchall()
        out = {str(row[0]): int(row[1]) for row in rows}
        out["TOTAL"] = sum(out.values())
        return out
    finally:
        conn.close()


def print_stats() -> None:
    data = stats()
    if not data.get("TOTAL"):
        print("No vacancies stored yet.")
        return
    for key in [FOUND, REVIEWED, NEEDS_VERIFICATION, PACKAGE_READY, PACKAGE_NEEDS_INPUT, APPLIED_MANUALLY, NOT_ELIGIBLE, "TOTAL"]:
        if key in data:
            print(f"{key}: {data[key]}")
