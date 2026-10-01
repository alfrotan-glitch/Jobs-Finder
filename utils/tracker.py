"""Small SQLite store for the final Jobs-Finder workflow.

The product tracks only what it needs: discovered vacancies, deterministic match
results, generated package metadata, and whether the user says they applied
manually. It is not an ATS and does not model interviews, offers, follow-ups, or
submission automation.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "applications.db"

FOUND = "FOUND"
REVIEWED = "REVIEWED"
PACKAGE_READY = "PACKAGE_READY"
APPLIED_MANUALLY = "APPLIED_MANUALLY"
NEEDS_VERIFICATION = "NEEDS_VERIFICATION"
NOT_ELIGIBLE = "NOT_ELIGIBLE"

VALID_STATUSES = {FOUND, REVIEWED, PACKAGE_READY, APPLIED_MANUALLY, NEEDS_VERIFICATION, NOT_ELIGIBLE}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
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
            metadata_json TEXT DEFAULT '{}',
            match_json TEXT DEFAULT '',
            package_json TEXT DEFAULT '',
            documents_json TEXT DEFAULT '',
            discovered_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT ''
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_status ON vacancies(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_readiness ON vacancies(readiness)")
    conn.commit()
    return conn


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
    timestamp = now_iso()
    conn = get_db()
    try:
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
                data.get("platform") or metadata.get("source") or "",
                data.get("url") or "",
                data.get("apply_url") or data.get("url") or "",
                data.get("description") or "",
                FOUND,
                json.dumps(metadata, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def log_medical_match(job_id: str, report: dict[str, Any]) -> None:
    readiness = str(report.get("readiness_status") or "")
    status = readiness_to_status(readiness)
    conn = get_db()
    try:
        conn.execute(
            "UPDATE vacancies SET match_json=?, readiness=?, status=?, updated_at=? WHERE id=?",
            (json.dumps(report, ensure_ascii=False), readiness, status, now_iso(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_tailored_resume(job_id: str, documents: dict[str, Any]) -> None:
    package = documents.get("application_package") or {}
    conn = get_db()
    try:
        conn.execute(
            "UPDATE vacancies SET documents_json=?, package_json=?, status=?, updated_at=? WHERE id=?",
            (
                json.dumps(documents, ensure_ascii=False),
                json.dumps(package, ensure_ascii=False),
                PACKAGE_READY,
                now_iso(),
                job_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_tailored_resume(job_id: str) -> dict[str, Any]:
    job = get_job_by_id(job_id)
    return (job or {}).get("documents") or {}


def mark_applied_manually(job_id: str) -> tuple[bool, str]:
    job = get_job_by_id(job_id)
    if not job:
        return False, "Vacancy not found."
    if job.get("readiness") == "NOT_ELIGIBLE":
        return False, "Cannot mark a NOT_ELIGIBLE vacancy as applied."
    conn = get_db()
    try:
        conn.execute("UPDATE vacancies SET status=?, updated_at=? WHERE id=?", (APPLIED_MANUALLY, now_iso(), job_id))
        conn.commit()
    finally:
        conn.close()
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


def get_recommended_jobs(limit: int = 20) -> list[dict[str, Any]]:
    jobs = list_jobs(limit=500)
    def rank(job: dict[str, Any]) -> tuple[int, str]:
        readiness = job.get("readiness") or ""
        metadata = job.get("metadata") or {}
        closing = metadata.get("closing_date") or "9999-12-31"
        if readiness == "READY_TO_APPLY":
            bucket = 0
        elif readiness == "NEEDS_VERIFICATION":
            bucket = 1
        else:
            bucket = 3
        if job.get("status") == NOT_ELIGIBLE or readiness == "NOT_ELIGIBLE":
            bucket = 9
        return (bucket, str(closing))
    return [job for job in sorted(jobs, key=rank) if rank(job)[0] < 9][:limit]


def delete_all() -> int:
    conn = get_db()
    try:
        count = conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
        conn.execute("DELETE FROM vacancies")
        conn.commit()
        return int(count)
    finally:
        conn.close()


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
    for key in [FOUND, REVIEWED, NEEDS_VERIFICATION, PACKAGE_READY, APPLIED_MANUALLY, NOT_ELIGIBLE, "TOTAL"]:
        if key in data:
            print(f"{key}: {data[key]}")
