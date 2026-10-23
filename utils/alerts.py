"""Local, evidence-backed job alerts; no employer contact or hosted service.

This inbox is derived from the existing authoritative recommendation gate.
It is append-only apart from marking notices read, survives program restarts,
and never turns a source failure into a claim that the market has no jobs.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from utils import tracker
from utils.discovery import SCAN_FAILED, SOURCES_UNAVAILABLE, is_expired
from utils.recommendations import is_recommendable

MAX_INBOX_RESULTS = 100


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _add_alert(
    conn: Any, *, key: str, kind: str, title: str, message: str,
    job_id: str = "", deadline: str = "",
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO job_alerts
          (dedupe_key, kind, job_id, title, message, deadline, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (key, kind, job_id, title[:240], message[:1000], deadline, _now()),
    )


def record_scan_alerts(scan: Any, *, today: date | None = None) -> None:
    """Announce first-ever positively matched vacancies and source outages.

    First-seen memory belongs to the alert system, not to the current scan
    snapshot. Re-running a scan must not generate duplicates. Failures don't
    mark unseen roles as seen and don't claim that zero results means no jobs.
    """
    today = today or date.today()
    data = scan.to_dict() if hasattr(scan, "to_dict") else dict(scan)
    status = str(data.get("status") or "")
    with tracker._write_connection() as conn:
        if status in {SCAN_FAILED, SOURCES_UNAVAILABLE}:
            _add_alert(
                conn, key=f"source_failure:{today.isoformat()}",
                kind="SOURCE_ISSUE", title="Job sources could not be checked",
                message="Today's scan could not reach the configured sources. Your saved applications are unchanged; try again later.",
            )
            conn.commit()
            return
        seen = {
            row[0] for row in conn.execute("SELECT job_id FROM seen_recommendations")
        }
        for entry in data.get("recommendations") or []:
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            job_id = str(entry["id"])
            if is_expired(entry, today=today):
                continue
            if not is_recommendable(entry, entry.get("match") or {}):
                continue
            stored = conn.execute("SELECT status FROM vacancies WHERE id=?", (job_id,)).fetchone()
            if stored and stored[0] == tracker.APPLIED_MANUALLY:
                continue
            conn.execute(
                """
                INSERT INTO seen_recommendations(job_id, first_seen_at, last_seen_at)
                VALUES (?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET last_seen_at=excluded.last_seen_at
                """,
                (job_id, _now(), _now()),
            )
            if job_id in seen:
                continue
            seen.add(job_id)
            readiness = str((entry.get("match") or {}).get("readiness_status") or entry.get("readiness") or "")
            title = str(entry.get("title") or "New matching vacancy")
            company = str(entry.get("company") or "Employer not listed")
            description = (
                "Your verified profile meets the currently assessed requirements."
                if readiness == "READY_TO_APPLY"
                else "A potentially suitable role was found, but some requirements need verification."
            )
            _add_alert(
                conn, key=f"first_match:{job_id}", kind="NEW_MATCH",
                title=f"New match: {title}",
                message=f"{company} — {description} Review the official vacancy and deadline.",
                job_id=job_id,
                deadline=str((entry.get("metadata") or {}).get("closing_date") or ""),
            )
        conn.commit()


def record_deadline_alerts(*, today: date | None = None) -> None:
    """Issue one reminder for each relevant threshold as deadlines approach."""
    today = today or date.today()
    with tracker._write_connection() as conn:
        for job in tracker.get_recommended_jobs(limit=500):
            if job.get("status") == tracker.APPLIED_MANUALLY:
                continue
            raw = str((job.get("metadata") or {}).get("closing_date") or "")
            try:
                closing = date.fromisoformat(raw[:10])
            except ValueError:
                continue
            remaining = (closing - today).days
            if not 0 <= remaining <= 7:
                continue
            threshold = 1 if remaining <= 1 else 3 if remaining <= 3 else 7
            job_id = str(job.get("id") or "")
            if not job_id:
                continue
            wording = ("today" if remaining == 0 else "tomorrow" if remaining == 1 else f"in {remaining} days")
            title = str(job.get("title") or "Vacancy")
            _add_alert(
                conn, key=f"deadline:{job_id}:{threshold}",
                kind="DEADLINE",
                title=f"Deadline {wording}: {title}",
                message=f"Application deadline {closing.isoformat()}. Review the vacancy instructions and submit manually before it closes.",
                job_id=job_id, deadline=closing.isoformat(),
            )
        conn.commit()


def list_alerts(*, limit: int = 50) -> dict[str, Any]:
    limit = max(1, min(MAX_INBOX_RESULTS, int(limit)))
    conn = tracker._read_connection()
    try:
        unread = int(conn.execute("SELECT COUNT(*) FROM job_alerts WHERE read_at IS NULL").fetchone()[0])
        rows = conn.execute(
            "SELECT id, kind, job_id, title, message, deadline, created_at, read_at "
            "FROM job_alerts ORDER BY id DESC LIMIT ?", (limit,),
        ).fetchall()
        return {"alerts": [dict(row) for row in rows], "unread_count": unread}
    finally:
        tracker._close_read_connection(conn)


def mark_alert_read(alert_id: int) -> bool:
    with tracker._write_connection() as conn:
        changed = conn.execute(
            "UPDATE job_alerts SET read_at=COALESCE(read_at, ?) WHERE id=?",
            (_now(), alert_id),
        ).rowcount
        conn.commit()
        return bool(changed)


def mark_all_alerts_read() -> int:
    with tracker._write_connection() as conn:
        changed = conn.execute(
            "UPDATE job_alerts SET read_at=? WHERE read_at IS NULL",
            (_now(),),
        ).rowcount
        conn.commit()
        return int(changed)
