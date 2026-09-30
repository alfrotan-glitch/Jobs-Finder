"""Continuous Afghan job watcher.

This module turns the existing discovery orchestrator into a persistent,
restart-safe job watch loop.  It deliberately does not discover jobs itself:
`run_job_watch_scan()` calls `utils.discovery.discover_all_jobs()` unless tests
or tools inject a compatible discovery function.

The watcher stores canonical vacancies, material changes, notification events,
and scan audits in the same SQLite database used by the review-first
application tracker.  Existing matching, document generation, and application
state transitions are reused; no application is submitted here.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, Iterable

from utils.discovery import Job, deduplicate_jobs, is_job_fresh, vacancy_keys
from utils.medical_matcher import match_job_against_profile
from utils.medical_requirements import looks_medical
from utils.resume_parser import extract_resume_text
from utils.tracker import get_db, get_job_by_id, log_discovered, log_medical_match, update_tailored_resume

READY_TO_APPLY = "READY_TO_APPLY"
NEEDS_VERIFICATION = "NEEDS_VERIFICATION"
NOT_ELIGIBLE = "NOT_ELIGIBLE"

ACTIVE_STATUS = "ACTIVE"
CLOSED_STATUS = "CLOSED"
EXPIRED_STATUS = "EXPIRED"

DEFAULT_DEADLINE_THRESHOLDS = [7, 3, 1]


@dataclass
class WatcherConfig:
    enabled: bool = True
    scan_interval_hours: float = 6
    deadline_alert_days: list[int] = field(default_factory=lambda: list(DEFAULT_DEADLINE_THRESHOLDS))
    auto_prepare_ready_to_apply: bool = False
    application_out_dir: str = "documents/applications"
    notification_preferences: dict[str, bool] = field(default_factory=dict)


@dataclass
class JobChange:
    canonical_id: str
    change_type: str
    readiness_status: str = ""
    operational_priority: str = ""
    changed_fields: list[str] = field(default_factory=list)
    notification_ids: list[str] = field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def json_loads(value: str | None, default: Any = None) -> Any:
    if value in (None, ""):
        return {} if default is None else default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {} if default is None else default


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_for_hash(value: Any) -> str:
    return normalize_space(value).lower()


def stable_hash(value: Any) -> str:
    if not isinstance(value, str):
        value = json_dumps(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def watcher_config_from_profile(profile: dict[str, Any] | None) -> WatcherConfig:
    profile = profile or {}
    watcher = profile.get("watcher", {}) if isinstance(profile.get("watcher"), dict) else {}
    schedule = profile.get("schedule", {}) if isinstance(profile.get("schedule"), dict) else {}
    thresholds = watcher.get("deadline_alert_days", schedule.get("deadline_alert_days", DEFAULT_DEADLINE_THRESHOLDS))
    if isinstance(thresholds, str):
        thresholds = [int(item) for item in re.findall(r"\d+", thresholds)] or DEFAULT_DEADLINE_THRESHOLDS
    thresholds = sorted({int(item) for item in thresholds if int(item) >= 0}, reverse=True)
    interval = watcher.get("scan_interval_hours", schedule.get("job_watch_interval_hours", schedule.get("discover_interval_hours", 6)))
    notifications = profile.get("notifications", {}) if isinstance(profile.get("notifications"), dict) else {}
    watcher_notifications = watcher.get("notifications", {}) if isinstance(watcher.get("notifications"), dict) else {}
    prefs = {
        "new_jobs": bool(notifications.get("new_jobs", watcher_notifications.get("new_jobs", True))),
        "needs_verification": bool(notifications.get("needs_verification", watcher_notifications.get("needs_verification", True))),
        "deadline_alerts": bool(notifications.get("deadline_alerts", watcher_notifications.get("deadline_alerts", True))),
        "updates": bool(notifications.get("updates", watcher_notifications.get("updates", True))),
        "closed": bool(notifications.get("closed", watcher_notifications.get("closed", True))),
        "source_failures": bool(notifications.get("source_failures", watcher_notifications.get("source_failures", True))),
    }
    return WatcherConfig(
        enabled=bool(watcher.get("enabled", schedule.get("enabled", True))),
        scan_interval_hours=float(interval or 6),
        deadline_alert_days=thresholds or list(DEFAULT_DEADLINE_THRESHOLDS),
        auto_prepare_ready_to_apply=bool(watcher.get("auto_prepare_ready_to_apply", False)),
        application_out_dir=str(watcher.get("application_out_dir", "documents/applications")),
        notification_preferences=prefs,
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def init_watcher_db() -> None:
    conn = get_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_watch_vacancies (
                canonical_id TEXT PRIMARY KEY,
                discovery_job_id TEXT,
                title TEXT,
                organization TEXT,
                location TEXT,
                source_urls_json TEXT DEFAULT '[]',
                source_provenance_json TEXT DEFAULT '[]',
                first_discovered_at TEXT,
                last_seen_at TEXT,
                last_changed_at TEXT,
                posting_date TEXT,
                closing_date TEXT,
                current_status TEXT,
                previous_status TEXT,
                content_fingerprint TEXT,
                requirements_fingerprint TEXT,
                application_route TEXT,
                last_matching_result_json TEXT DEFAULT '{}',
                last_notification_at TEXT,
                notification_state_json TEXT DEFAULT '{}',
                operational_priority TEXT DEFAULT '',
                readiness_status TEXT DEFAULT '',
                last_change_type TEXT DEFAULT '',
                priority_reasons_json TEXT DEFAULT '[]',
                description TEXT DEFAULT '',
                metadata_json TEXT DEFAULT '{}'
            )
            """
        )
        _migrate_watcher_schema(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_watch_status ON job_watch_vacancies(current_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_watch_readiness ON job_watch_vacancies(readiness_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_watch_closing ON job_watch_vacancies(closing_date)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_watch_notifications (
                id TEXT PRIMARY KEY,
                dedupe_key TEXT UNIQUE,
                event_type TEXT,
                canonical_id TEXT,
                title TEXT,
                message TEXT,
                readiness_status TEXT,
                threshold_days INTEGER,
                state TEXT DEFAULT 'unread',
                created_at TEXT,
                payload_json TEXT DEFAULT '{}'
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_watch_notifications_state ON job_watch_notifications(state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_watch_notifications_job ON job_watch_notifications(canonical_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_watch_scans (
                scan_id TEXT PRIMARY KEY,
                started_at TEXT,
                finished_at TEXT,
                status TEXT,
                sources_attempted_json TEXT DEFAULT '[]',
                sources_successful_json TEXT DEFAULT '[]',
                sources_failed_json TEXT DEFAULT '[]',
                discovered_count INTEGER DEFAULT 0,
                normalized_count INTEGER DEFAULT 0,
                deduplicated_count INTEGER DEFAULT 0,
                new_count INTEGER DEFAULT 0,
                updated_count INTEGER DEFAULT 0,
                unchanged_count INTEGER DEFAULT 0,
                closed_count INTEGER DEFAULT 0,
                ready_to_apply_count INTEGER DEFAULT 0,
                needs_verification_count INTEGER DEFAULT 0,
                not_eligible_count INTEGER DEFAULT 0,
                errors_json TEXT DEFAULT '[]'
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _migrate_watcher_schema(conn) -> None:
    cursor = conn.execute("PRAGMA table_info(job_watch_vacancies)")
    existing = {row[1] for row in cursor.fetchall()}
    migrations = {
        "last_change_type": "TEXT DEFAULT ''",
    }
    for column, definition in migrations.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE job_watch_vacancies ADD COLUMN {column} {definition}")


# ---------------------------------------------------------------------------
# Canonical identity and fingerprints
# ---------------------------------------------------------------------------


def canonical_job_id(job: Job | dict[str, Any]) -> str:
    """Return a stable ID using the existing deduplication candidate keys."""
    keys = vacancy_keys(job)
    strongest = keys[0] if keys else str(_get(job, "id", ""))
    return "watch_" + stable_hash(strongest)[:18]


def _get(job: Job | dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(job, dict):
        return job.get(key, default)
    return getattr(job, key, default)


def _metadata(job: Job | dict[str, Any]) -> dict[str, Any]:
    metadata = _get(job, "metadata", {}) or {}
    if isinstance(metadata, str):
        return json_loads(metadata, {})
    return metadata if isinstance(metadata, dict) else {}


def source_urls(job: Job | dict[str, Any]) -> list[str]:
    metadata = _metadata(job)
    values: list[str] = []
    for value in list(metadata.get("source_urls") or []) + [metadata.get("source_url"), metadata.get("original_vacancy_url"), _get(job, "url"), _get(job, "apply_url")]:
        if value and value not in values:
            values.append(str(value))
    return values


def source_provenance(job: Job | dict[str, Any]) -> list[dict[str, Any]]:
    metadata = _metadata(job)
    provenance = metadata.get("source_provenance") or []
    return provenance if isinstance(provenance, list) else []


def posting_date(job: Job | dict[str, Any]) -> str:
    metadata = _metadata(job)
    return str(metadata.get("posting_date") or metadata.get("date_posted") or "")[:10]


def closing_date(job: Job | dict[str, Any]) -> str:
    metadata = _metadata(job)
    return str(metadata.get("closing_date") or metadata.get("deadline") or "")[:10]


def application_route(job: Job | dict[str, Any]) -> str:
    metadata = _metadata(job)
    return normalize_space(
        metadata.get("application_email")
        or metadata.get("application_url")
        or _get(job, "apply_url")
        or _get(job, "url")
        or ""
    )


def material_payload(job: Job | dict[str, Any]) -> dict[str, Any]:
    """Fields whose changes should be considered material."""
    return {
        "title": normalize_for_hash(_get(job, "title", "")),
        "organization": normalize_for_hash(_get(job, "company", "")),
        "location": normalize_for_hash(_get(job, "location", "")),
        "posting_date": posting_date(job),
        "closing_date": closing_date(job),
        "application_route": normalize_for_hash(application_route(job)),
        "description": normalize_for_hash(_get(job, "description", ""))[:20000],
    }


def content_fingerprint(job: Job | dict[str, Any]) -> str:
    return stable_hash(material_payload(job))


def requirements_payload(job: Job | dict[str, Any], match_report: dict[str, Any] | None = None) -> dict[str, Any]:
    if match_report and isinstance(match_report.get("extracted_requirements"), dict):
        extracted = match_report["extracted_requirements"]
    else:
        extracted = _metadata(job).get("requirements") or {}
    reqs = extracted.get("requirements", []) if isinstance(extracted, dict) else []
    facts = extracted.get("facts", {}) if isinstance(extracted, dict) else {}
    compact = {
        "requirements": [
            {
                "key": item.get("key"),
                "required": item.get("required"),
                "value": item.get("value"),
                "criticality": item.get("criticality"),
            }
            for item in reqs
            if isinstance(item, dict)
        ],
        "facts": {
            key: facts.get(key)
            for key in [
                "reference_number",
                "application_email",
                "application_url",
                "application_subject",
                "closing_date",
                "locations",
                "gender_requirement",
                "nationality_requirement",
            ]
            if isinstance(facts, dict) and facts.get(key) not in (None, "", [])
        },
    }
    return compact


def requirements_fingerprint(job: Job | dict[str, Any], match_report: dict[str, Any] | None = None) -> str:
    return stable_hash(requirements_payload(job, match_report))


def is_expired(job_or_row: Job | dict[str, Any], *, today: date | None = None) -> bool:
    today = today or date.today()
    if isinstance(job_or_row, dict) and "closing_date" in job_or_row and "metadata" not in job_or_row:
        closing = str(job_or_row.get("closing_date") or "")
    else:
        closing = closing_date(job_or_row)
    parsed = parse_date(closing)
    return bool(parsed and parsed < today)


def source_marks_closed(job: Job | dict[str, Any]) -> bool:
    metadata = _metadata(job)
    value = " ".join(
        str(metadata.get(key, ""))
        for key in ["status", "current_status", "vacancy_status", "state"]
    ).lower()
    title = str(_get(job, "title", "")).lower()
    return "closed" in value or "expired" in value or title.startswith("[closed]")


def lifecycle_status(job: Job | dict[str, Any], *, today: date | None = None) -> str:
    if source_marks_closed(job):
        return CLOSED_STATUS
    if is_expired(job, today=today):
        return EXPIRED_STATUS
    return ACTIVE_STATUS


def changed_fields(existing: dict[str, Any], job: Job | dict[str, Any], content_fp: str, req_fp: str) -> list[str]:
    fields: list[str] = []
    comparisons = {
        "title": normalize_space(_get(job, "title", "")),
        "organization": normalize_space(_get(job, "company", "")),
        "location": normalize_space(_get(job, "location", "")),
        "posting_date": posting_date(job),
        "closing_date": closing_date(job),
        "application_route": application_route(job),
    }
    for field, new_value in comparisons.items():
        if normalize_space(existing.get(field, "")) != normalize_space(new_value):
            fields.append(field)
    if existing.get("content_fingerprint") != content_fp and "description" not in fields:
        fields.append("description")
    if existing.get("requirements_fingerprint") != req_fp:
        fields.append("requirements")
    return fields


# ---------------------------------------------------------------------------
# Matching and priority
# ---------------------------------------------------------------------------


def readiness_from_match(match_report: dict[str, Any]) -> str:
    value = str(match_report.get("readiness_status") or "").upper()
    if value in {READY_TO_APPLY, NEEDS_VERIFICATION, NOT_ELIGIBLE}:
        return value
    priority = str(match_report.get("priority") or "").lower()
    if "verification" in priority:
        return NEEDS_VERIFICATION
    if "low" in priority or "closed" in priority or "not" in priority:
        return NOT_ELIGIBLE
    return READY_TO_APPLY if match_report else NEEDS_VERIFICATION


def deadline_days_left(job: Job | dict[str, Any], *, today: date | None = None) -> int | None:
    today = today or date.today()
    parsed = parse_date(closing_date(job))
    if not parsed:
        return None
    return (parsed - today).days


def calculate_operational_priority(job: Job | dict[str, Any], match_report: dict[str, Any], *, today: date | None = None) -> tuple[str, list[str]]:
    """Explainable operational priority from deterministic facts only."""
    today = today or date.today()
    status = lifecycle_status(job, today=today)
    readiness = readiness_from_match(match_report)
    metadata = _metadata(job)
    reliability = str(metadata.get("source_reliability") or metadata.get("reliability") or "unknown").lower()
    route = application_route(job)
    days_left = deadline_days_left(job, today=today)
    medical = bool(match_report.get("facts", {}).get("is_medical")) or looks_medical(f"{_get(job, 'title', '')}\n{_get(job, 'description', '')}")
    reasons: list[str] = []

    if status in {CLOSED_STATUS, EXPIRED_STATUS}:
        return "CLOSED", ["Vacancy is closed or its closing date has passed"]
    if readiness == READY_TO_APPLY:
        reasons.append("Deterministic matcher classified this vacancy as READY_TO_APPLY")
    elif readiness == NEEDS_VERIFICATION:
        reasons.append("Specific requirement(s) need user verification before applying")
    else:
        reasons.append("Deterministic matcher classified this vacancy as NOT_ELIGIBLE or low fit")
    if medical:
        reasons.append("Medical/health relevance detected from the title or vacancy text")
    else:
        reasons.append("No clear medical/health relevance was detected")
    if not medical:
        # A vacancy can be mechanically complete (route + no unmet extracted
        # requirements) while still being unrelated to Dr. Frotan's medical /
        # public-health profile. Keep it visible in the audit trail, but do not
        # promote it as actionable or auto-package it.
        return "LOW", reasons
    if route:
        reasons.append("Application route is available")
    else:
        reasons.append("Application route must be verified")
    if reliability == "high":
        reasons.append("High-provenance source")
    elif reliability == "medium":
        reasons.append("Medium-provenance source; employer route should be checked")
    if days_left is not None:
        reasons.append(f"Deadline is in {days_left} day(s)")

    if readiness == READY_TO_APPLY and days_left is not None and days_left <= 1:
        return "APPLY_TODAY", reasons
    if readiness == READY_TO_APPLY and days_left is not None and days_left <= 3:
        return "APPLY_SOON", reasons
    if readiness == READY_TO_APPLY:
        return "READY", reasons
    if readiness == NEEDS_VERIFICATION:
        return "VERIFY", reasons
    return "LOW", reasons


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


def create_notification(
    *,
    event_type: str,
    canonical_id: str = "",
    title: str = "",
    message: str = "",
    readiness_status: str = "",
    threshold_days: int | None = None,
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    created_at: str | None = None,
) -> str | None:
    init_watcher_db()
    created_at = created_at or utc_now_iso()
    payload = payload or {}
    dedupe_key = dedupe_key or f"{event_type}:{canonical_id}:{threshold_days or ''}:{stable_hash(payload)[:12]}"
    notification_id = "evt_" + stable_hash(dedupe_key)[:20]
    conn = get_db()
    inserted = False
    try:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO job_watch_notifications
            (id, dedupe_key, event_type, canonical_id, title, message, readiness_status,
             threshold_days, state, created_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unread', ?, ?)
            """,
            (
                notification_id,
                dedupe_key,
                event_type,
                canonical_id,
                title,
                message,
                readiness_status,
                threshold_days,
                created_at,
                json_dumps(payload),
            ),
        )
        inserted = cur.rowcount > 0
        if inserted and canonical_id:
            row = conn.execute("SELECT notification_state_json FROM job_watch_vacancies WHERE canonical_id = ?", (canonical_id,)).fetchone()
            state = json_loads(row["notification_state_json"], {}) if row else {}
            state.setdefault("issued", [])
            if dedupe_key not in state["issued"]:
                state["issued"].append(dedupe_key)
            conn.execute(
                "UPDATE job_watch_vacancies SET last_notification_at = ?, notification_state_json = ? WHERE canonical_id = ?",
                (created_at, json_dumps(state), canonical_id),
            )
        conn.commit()
    finally:
        conn.close()
    if inserted:
        try:
            from utils.events import EventBus

            EventBus.emit("job_watch_notification", {"id": notification_id, "type": event_type, "canonical_id": canonical_id})
        except Exception:
            pass
        return notification_id
    return None


def notifications_for_deadline(job: Job | dict[str, Any], canonical_id: str, readiness: str, thresholds: Iterable[int], *, today: date | None = None) -> list[str]:
    today = today or date.today()
    days = deadline_days_left(job, today=today)
    if days is None or days < 0:
        return []
    ids: list[str] = []
    title = f"{_get(job, 'title', '')} — {_get(job, 'company', '')}".strip(" —")
    applicable = [threshold for threshold in sorted({int(t) for t in thresholds}) if days <= threshold]
    if not applicable:
        return []
    threshold = applicable[0]
    nid = create_notification(
        event_type="deadline_approaching",
        canonical_id=canonical_id,
        title=title,
        message=f"Deadline approaching: {title} closes in {days} day(s).",
        readiness_status=readiness,
        threshold_days=threshold,
        payload={"days_left": days, "closing_date": closing_date(job), "threshold_days": threshold},
        dedupe_key=f"deadline_approaching:{canonical_id}:{threshold}:{closing_date(job)}",
    )
    if nid:
        ids.append(nid)
    return ids


# ---------------------------------------------------------------------------
# Persistence operations
# ---------------------------------------------------------------------------


def _job_row(canonical_id: str) -> dict[str, Any] | None:
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM job_watch_vacancies WHERE canonical_id = ?", (canonical_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _merge_unique(existing_json: str | None, values: list[Any]) -> str:
    existing = json_loads(existing_json, [])
    if not isinstance(existing, list):
        existing = []
    for value in values:
        if value and value not in existing:
            existing.append(value)
    return json_dumps(existing)


def canonicalize_job(job: Job | dict[str, Any], canonical_id: str) -> Job:
    if isinstance(job, Job):
        cloned = copy.deepcopy(job)
    else:
        cloned = Job(
            id=str(job.get("id") or canonical_id),
            title=str(job.get("title") or ""),
            company=str(job.get("company") or job.get("organization") or ""),
            location=str(job.get("location") or ""),
            url=str(job.get("url") or job.get("original_vacancy_url") or ""),
            apply_url=str(job.get("apply_url") or job.get("application_route") or job.get("application_url") or ""),
            platform=str(job.get("platform") or job.get("source") or "watcher"),
            description=str(job.get("description") or ""),
            department=str(job.get("department") or ""),
            metadata=copy.deepcopy(job.get("metadata") or {}),
        )
    original_id = cloned.id
    cloned.id = canonical_id
    cloned.metadata = cloned.metadata or {}
    cloned.metadata.setdefault("original_discovery_id", original_id)
    cloned.metadata["canonical_job_id"] = canonical_id
    cloned.metadata["source_urls"] = source_urls(cloned)
    cloned.metadata["source_provenance"] = source_provenance(cloned)
    return cloned


def _mark_application_closed(job_id: str, *, lifecycle_status: str = EXPIRED_STATUS) -> None:
    """Reflect source closure without erasing user application progress.

    Unstarted vacancies become not_eligible so they disappear from Recommended.
    Prepared/opened applications become closed/expired so the Applications view
    can show why they are no longer actionable. Submitted/applied/follow-up
    rows are never reset by a watcher scan.
    """
    app = get_job_by_id(job_id)
    if not app:
        return
    current = app.get("status") or "discovered"
    terminal_or_user_decided = {"submitted", "applied", "interviewing", "offer", "rejected", "withdrawn", "archived"}
    if current in terminal_or_user_decided:
        new_status = current
    elif current in {"prepared", "review", "opened"}:
        new_status = "closed" if lifecycle_status == CLOSED_STATUS else "expired"
    else:
        new_status = "not_eligible"
    now_iso = utc_now_iso()
    conn = get_db()
    try:
        conn.execute(
            "UPDATE applications SET status = ?, priority = 'Closed', last_activity = COALESCE(last_activity, ?) WHERE id = ?",
            (new_status, now_iso, job_id),
        )
        conn.commit()
    finally:
        conn.close()



def _upsert_application_snapshot(job: Job, match_report: dict[str, Any], *, new_record: bool) -> None:
    """Keep the existing review-first tracker aligned with the canonical job."""
    if new_record or not get_job_by_id(job.id):
        log_discovered(job)
    metadata = dict(job.metadata or {})
    metadata["readiness_status"] = readiness_from_match(match_report)
    metadata["operational_priority"] = calculate_operational_priority(job, match_report)[0]
    job.metadata = metadata
    conn = get_db()
    try:
        conn.execute(
            """
            UPDATE applications
            SET title = ?, company = ?, platform = ?, url = ?, apply_url = ?, location = ?,
                description = ?, source = ?, metadata = ?, source_url = ?, closing_date = ?,
                date_posted = ?, application_email = COALESCE(NULLIF(?, ''), application_email),
                application_subject = COALESCE(NULLIF(?, ''), application_subject),
                reference_number = COALESCE(NULLIF(?, ''), reference_number),
                provenance_json = ?
            WHERE id = ?
            """,
            (
                job.title,
                job.company,
                job.platform,
                job.url,
                job.apply_url,
                job.location,
                job.description,
                metadata.get("source", job.platform),
                json_dumps(metadata),
                metadata.get("source_url", job.url),
                metadata.get("closing_date", ""),
                metadata.get("posting_date", metadata.get("date_posted", "")),
                metadata.get("application_email", ""),
                metadata.get("application_subject", ""),
                metadata.get("reference_number", ""),
                json_dumps(metadata.get("source_provenance", [])),
                job.id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    log_medical_match(job.id, match_report)


def persist_job(
    job: Job,
    match_report: dict[str, Any],
    *,
    now_iso: str,
    today: date,
    notification_preferences: dict[str, bool] | None = None,
) -> JobChange:
    init_watcher_db()
    canonical_id = job.id
    readiness = readiness_from_match(match_report)
    op_priority, reasons = calculate_operational_priority(job, match_report, today=today)
    status = lifecycle_status(job, today=today)
    content_fp = content_fingerprint(job)
    req_fp = requirements_fingerprint(job, match_report)
    existing = _job_row(canonical_id)
    notify = notification_preferences or {"new_jobs": True, "needs_verification": True, "updates": True, "closed": True}
    fields = changed_fields(existing, job, content_fp, req_fp) if existing else []
    change_type = "NEW" if not existing else "UPDATED" if fields or existing.get("current_status") != status else "UNCHANGED"
    notification_ids: list[str] = []

    conn = get_db()
    try:
        if not existing:
            conn.execute(
                """
                INSERT INTO job_watch_vacancies
                (canonical_id, discovery_job_id, title, organization, location, source_urls_json,
                 source_provenance_json, first_discovered_at, last_seen_at, last_changed_at,
                 posting_date, closing_date, current_status, previous_status, content_fingerprint,
                 requirements_fingerprint, application_route, last_matching_result_json,
                 notification_state_json, operational_priority, readiness_status,
                 last_change_type, priority_reasons_json, description, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?, ?)
                """,
                (
                    canonical_id,
                    job.metadata.get("original_discovery_id", canonical_id),
                    job.title,
                    job.company,
                    job.location,
                    json_dumps(source_urls(job)),
                    json_dumps(source_provenance(job)),
                    now_iso,
                    now_iso,
                    now_iso,
                    posting_date(job),
                    closing_date(job),
                    status,
                    content_fp,
                    req_fp,
                    application_route(job),
                    json_dumps(match_report),
                    op_priority,
                    readiness,
                    change_type,
                    json_dumps(reasons),
                    job.description,
                    json_dumps(job.metadata),
                ),
            )
        else:
            previous_status = existing.get("current_status") or ""
            last_changed = now_iso if change_type == "UPDATED" else existing.get("last_changed_at") or now_iso
            conn.execute(
                """
                UPDATE job_watch_vacancies
                SET discovery_job_id = ?, title = ?, organization = ?, location = ?,
                    source_urls_json = ?, source_provenance_json = ?, last_seen_at = ?,
                    last_changed_at = ?, posting_date = ?, closing_date = ?, current_status = ?,
                    previous_status = ?, content_fingerprint = ?, requirements_fingerprint = ?,
                    application_route = ?, last_matching_result_json = ?, operational_priority = ?,
                    readiness_status = ?, last_change_type = ?, priority_reasons_json = ?, description = ?, metadata_json = ?
                WHERE canonical_id = ?
                """,
                (
                    job.metadata.get("original_discovery_id", canonical_id),
                    job.title,
                    job.company,
                    job.location,
                    _merge_unique(existing.get("source_urls_json"), source_urls(job)),
                    _merge_unique(existing.get("source_provenance_json"), source_provenance(job)),
                    now_iso,
                    last_changed,
                    posting_date(job),
                    closing_date(job),
                    status,
                    previous_status if previous_status != status else existing.get("previous_status", ""),
                    content_fp,
                    req_fp,
                    application_route(job),
                    json_dumps(match_report),
                    op_priority,
                    readiness,
                    change_type,
                    json_dumps(reasons),
                    job.description,
                    json_dumps(job.metadata),
                    canonical_id,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    _upsert_application_snapshot(job, match_report, new_record=not existing)
    if status in {CLOSED_STATUS, EXPIRED_STATUS}:
        _mark_application_closed(canonical_id, lifecycle_status=status)

    title = f"{job.title} — {job.company}"
    if notify.get("new_jobs", True) and change_type == "NEW" and status == ACTIVE_STATUS and readiness == READY_TO_APPLY:
        nid = create_notification(
            event_type="new_ready_to_apply_job",
            canonical_id=canonical_id,
            title=title,
            message=f"New ready-to-apply opportunity: {title}",
            readiness_status=readiness,
            payload={"operational_priority": op_priority, "reasons": reasons},
            dedupe_key=f"new_ready_to_apply_job:{canonical_id}",
            created_at=now_iso,
        )
        if nid:
            notification_ids.append(nid)
    elif notify.get("needs_verification", True) and change_type == "NEW" and status == ACTIVE_STATUS and readiness == NEEDS_VERIFICATION:
        nid = create_notification(
            event_type="new_needs_verification_job",
            canonical_id=canonical_id,
            title=title,
            message=f"New opportunity needs verification: {title}",
            readiness_status=readiness,
            payload={"operational_priority": op_priority, "reasons": reasons},
            dedupe_key=f"new_needs_verification_job:{canonical_id}",
            created_at=now_iso,
        )
        if nid:
            notification_ids.append(nid)
    elif notify.get("updates", True) and change_type == "UPDATED" and status == ACTIVE_STATUS:
        nid = create_notification(
            event_type="vacancy_updated_materially",
            canonical_id=canonical_id,
            title=title,
            message=f"Vacancy updated materially: {title}",
            readiness_status=readiness,
            payload={"changed_fields": fields, "operational_priority": op_priority},
            dedupe_key=f"vacancy_updated_materially:{canonical_id}:{content_fp}:{req_fp}",
            created_at=now_iso,
        )
        if nid:
            notification_ids.append(nid)
    if notify.get("closed", True) and status in {CLOSED_STATUS, EXPIRED_STATUS}:
        nid = create_notification(
            event_type="vacancy_closed",
            canonical_id=canonical_id,
            title=title,
            message=f"Vacancy closed/expired: {title}",
            readiness_status=readiness,
            payload={"status": status, "closing_date": closing_date(job)},
            dedupe_key=f"vacancy_closed:{canonical_id}:{status}:{closing_date(job)}",
            created_at=now_iso,
        )
        if nid:
            notification_ids.append(nid)

    return JobChange(canonical_id, change_type, readiness, op_priority, fields, notification_ids)


def expire_closed_jobs(*, now_iso: str, today: date, notify: bool = True) -> int:
    init_watcher_db()
    conn = get_db()
    closed = 0
    notifications: list[dict[str, Any]] = []
    try:
        rows = conn.execute(
            """
            SELECT canonical_id, title, organization, closing_date, current_status, readiness_status
            FROM job_watch_vacancies
            WHERE current_status NOT IN (?, ?) AND closing_date IS NOT NULL AND closing_date != ''
            """,
            (CLOSED_STATUS, EXPIRED_STATUS),
        ).fetchall()
        for row in rows:
            parsed = parse_date(row["closing_date"])
            if parsed and parsed < today:
                conn.execute(
                    """
                    UPDATE job_watch_vacancies
                    SET previous_status = current_status, current_status = ?, last_changed_at = ?, last_change_type = ?
                    WHERE canonical_id = ?
                    """,
                    (EXPIRED_STATUS, now_iso, "EXPIRED", row["canonical_id"]),
                )
                closed += 1
                notifications.append(dict(row))
        conn.commit()
    finally:
        conn.close()
    for row in notifications:
        _mark_application_closed(row["canonical_id"], lifecycle_status=EXPIRED_STATUS)
        if not notify:
            continue
        create_notification(
            event_type="vacancy_closed",
            canonical_id=row["canonical_id"],
            title=f"{row['title']} — {row['organization']}",
            message=f"Vacancy expired: {row['title']} — {row['organization']}",
            readiness_status=row["readiness_status"] or "",
            payload={"status": EXPIRED_STATUS, "closing_date": row["closing_date"]},
            dedupe_key=f"vacancy_closed:{row['canonical_id']}:{EXPIRED_STATUS}:{row['closing_date']}",
            created_at=now_iso,
        )
    return closed


def issue_deadline_notifications_for_active_jobs(*, today: date, thresholds: Iterable[int]) -> int:
    init_watcher_db()
    conn = get_db()
    issued = 0
    try:
        rows = conn.execute("SELECT * FROM job_watch_vacancies WHERE current_status = ?", (ACTIVE_STATUS,)).fetchall()
    finally:
        conn.close()
    for row in rows:
        job = {
            "id": row["canonical_id"],
            "title": row["title"],
            "company": row["organization"],
            "location": row["location"],
            "url": "",
            "apply_url": row["application_route"],
            "description": row["description"],
            "metadata": {"closing_date": row["closing_date"]},
        }
        issued += len(notifications_for_deadline(job, row["canonical_id"], row["readiness_status"] or "", thresholds, today=today))
    return issued


# ---------------------------------------------------------------------------
# Scan orchestration
# ---------------------------------------------------------------------------


def active_source_ids(profile: dict[str, Any]) -> list[str]:
    try:
        from utils.source_registry import active_sources_for_discovery, registry_enabled

        if registry_enabled(profile):
            return [record["id"] for record in active_sources_for_discovery(profile)]
    except Exception:
        pass
    sources = profile.get("job_sources", {}) if isinstance(profile.get("job_sources"), dict) else {}
    ids = []
    for key, value in sources.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and value.get("enabled", True):
            ids.append(key)
        elif isinstance(value, list) and value:
            ids.append(key)
    return ids or ["existing_discovery_orchestrator"]


def begin_scan(scan_id: str, started_at: str, attempted: list[str]) -> None:
    init_watcher_db()
    conn = get_db()
    try:
        conn.execute(
            """
            UPDATE job_watch_scans
            SET status = 'INTERRUPTED', finished_at = COALESCE(finished_at, ?),
                errors_json = CASE WHEN errors_json IS NULL OR errors_json = '[]'
                    THEN '[{"phase":"scan","error":"Previous scan did not finish before the next scan started"}]'
                    ELSE errors_json END
            WHERE status = 'RUNNING' AND scan_id != ?
            """,
            (started_at, scan_id),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO job_watch_scans
            (scan_id, started_at, status, sources_attempted_json, sources_successful_json, sources_failed_json, errors_json)
            VALUES (?, ?, 'RUNNING', ?, '[]', '[]', '[]')
            """,
            (scan_id, started_at, json_dumps(attempted)),
        )
        conn.commit()
    finally:
        conn.close()


def finish_scan(scan_id: str, summary: dict[str, Any]) -> None:
    init_watcher_db()
    conn = get_db()
    try:
        conn.execute(
            """
            UPDATE job_watch_scans
            SET finished_at = ?, status = ?, sources_attempted_json = ?, sources_successful_json = ?,
                sources_failed_json = ?, discovered_count = ?, normalized_count = ?, deduplicated_count = ?,
                new_count = ?, updated_count = ?, unchanged_count = ?, closed_count = ?,
                ready_to_apply_count = ?, needs_verification_count = ?, not_eligible_count = ?, errors_json = ?
            WHERE scan_id = ?
            """,
            (
                summary.get("finished_at"),
                summary.get("status", "COMPLETED"),
                json_dumps(summary.get("sources_attempted", [])),
                json_dumps(summary.get("sources_successful", [])),
                json_dumps(summary.get("sources_failed", [])),
                int(summary.get("discovered_count", 0)),
                int(summary.get("normalized_count", 0)),
                int(summary.get("deduplicated_count", 0)),
                int(summary.get("new_count", 0)),
                int(summary.get("updated_count", 0)),
                int(summary.get("unchanged_count", 0)),
                int(summary.get("closed_count", 0)),
                int(summary.get("ready_to_apply_count", 0)),
                int(summary.get("needs_verification_count", 0)),
                int(summary.get("not_eligible_count", 0)),
                json_dumps(summary.get("errors", [])),
                scan_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _coerce_jobs_result(result: Any) -> tuple[list[Job], list[dict[str, Any]], list[str], list[str]]:
    """Accept list[Job] or a dict result from tests/tools."""
    source_errors: list[dict[str, Any]] = []
    attempted: list[str] = []
    successful: list[str] = []
    if isinstance(result, dict):
        jobs = result.get("jobs", []) or []
        source_errors = result.get("source_errors", result.get("sources_failed", [])) or []
        attempted = result.get("sources_attempted", []) or []
        successful = result.get("sources_successful", []) or []
    else:
        jobs = result or []
    coerced: list[Job] = []
    for item in jobs:
        if isinstance(item, Job):
            coerced.append(item)
        elif isinstance(item, dict):
            coerced.append(
                Job(
                    id=str(item.get("id") or stable_hash(item)[:12]),
                    title=str(item.get("title") or ""),
                    company=str(item.get("company") or item.get("organization") or ""),
                    location=str(item.get("location") or ""),
                    url=str(item.get("url") or item.get("original_vacancy_url") or ""),
                    apply_url=str(item.get("apply_url") or item.get("application_route") or item.get("application_url") or ""),
                    platform=str(item.get("platform") or item.get("source") or "watcher"),
                    description=str(item.get("description") or ""),
                    department=str(item.get("department") or ""),
                    metadata=copy.deepcopy(item.get("metadata") or {}),
                )
            )
    return coerced, source_errors, attempted, successful


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _source_id_from_job(job: Job) -> str:
    metadata = job.metadata or {}
    return str(metadata.get("source") or job.platform or metadata.get("source_name") or "unknown")


def _profile_discovery_audit(profile: dict[str, Any]) -> dict[str, Any]:
    audit = profile.get("_watcher_source_audit") if isinstance(profile, dict) else None
    return audit if isinstance(audit, dict) else {}


def _source_error_notifications(source_errors: list[dict[str, Any]], *, now_iso: str) -> list[str]:
    ids: list[str] = []
    day = now_iso[:10]
    for error in source_errors:
        source = str(error.get("source") or error.get("id") or "source")
        message = str(error.get("error") or error.get("message") or "Source failed during scan")
        nid = create_notification(
            event_type="source_failure",
            canonical_id="",
            title=source,
            message=f"Source failure: {source} — {message}",
            payload=error,
            dedupe_key=f"source_failure:{source}:{day}:{stable_hash(message)[:10]}",
            created_at=now_iso,
        )
        if nid:
            ids.append(nid)
    return ids


async def run_job_watch_scan(
    profile: dict[str, Any],
    *,
    discovery_func: Callable[[dict[str, Any]], Any] | None = None,
    now: datetime | None = None,
    today: date | None = None,
    resume_text: str | None = None,
    scan_id: str | None = None,
) -> dict[str, Any]:
    """Run one watcher scan using the existing discovery orchestrator.

    Source/discovery failures are recorded in the scan audit and notifications,
    but they never delete or close previously seen jobs.  Jobs are only closed by
    an explicit source closed marker or by a parsed closing date passing.
    """
    init_watcher_db()
    config = watcher_config_from_profile(profile)
    supplied_now = now is not None
    now_dt = (now or utc_now()).replace(microsecond=0)
    today = today or now_dt.date()
    now_iso = now_dt.isoformat()
    scan_id = scan_id or f"scan_{now_dt.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    attempted = active_source_ids(profile)
    begin_scan(scan_id, now_iso, attempted)

    summary: dict[str, Any] = {
        "scan_id": scan_id,
        "started_at": now_iso,
        "finished_at": "",
        "status": "COMPLETED",
        "sources_attempted": list(attempted),
        "sources_successful": [],
        "sources_failed": [],
        "discovered_count": 0,
        "normalized_count": 0,
        "deduplicated_count": 0,
        "new_count": 0,
        "updated_count": 0,
        "unchanged_count": 0,
        "closed_count": 0,
        "ready_to_apply_count": 0,
        "needs_verification_count": 0,
        "not_eligible_count": 0,
        "notifications_created": 0,
        "errors": [],
        "changes": [],
    }

    jobs: list[Job] = []
    source_errors: list[dict[str, Any]] = []
    injected_attempted: list[str] = []
    injected_successful: list[str] = []
    try:
        if discovery_func is None:
            from utils.discovery import discover_all_jobs

            discovery_func = discover_all_jobs
        result = await _maybe_await(discovery_func(profile))
        jobs, source_errors, injected_attempted, injected_successful = _coerce_jobs_result(result)
    except Exception as exc:
        source_errors = [{"source": "discovery_orchestrator", "error": str(exc)}]
        summary["errors"].append({"phase": "discovery", "error": str(exc)})
        jobs = []

    audit = _profile_discovery_audit(profile)
    for value in injected_attempted or audit.get("attempted", []) or []:
        if value not in summary["sources_attempted"]:
            summary["sources_attempted"].append(value)
    source_errors.extend(audit.get("failed", []) or [])
    source_errors = [err if isinstance(err, dict) else {"source": "source", "error": str(err)} for err in source_errors]

    summary["discovered_count"] = len(jobs)
    summary["normalized_count"] = len(jobs)
    unique_jobs = deduplicate_jobs(jobs)
    summary["deduplicated_count"] = len(unique_jobs)

    resume_text = resume_text if resume_text is not None else extract_resume_text(profile.get("resume_path", ""))
    for raw_job in unique_jobs:
        try:
            canonical_id = canonical_job_id(raw_job)
            job = canonicalize_job(raw_job, canonical_id)
            report = match_job_against_profile(job.to_dict(), profile, resume_text=resume_text, today=today).to_dict()
            change = persist_job(job, report, now_iso=now_iso, today=today, notification_preferences=config.notification_preferences)
            summary["changes"].append(change.__dict__)
            summary[f"{change.change_type.lower()}_count"] = summary.get(f"{change.change_type.lower()}_count", 0) + 1
            if lifecycle_status(job, today=today) in {CLOSED_STATUS, EXPIRED_STATUS}:
                summary["closed_count"] += 1
            if change.readiness_status == READY_TO_APPLY:
                summary["ready_to_apply_count"] += 1
                if config.auto_prepare_ready_to_apply and change.change_type in {"NEW", "UPDATED"}:
                    prepared = prepare_application_for_watcher_job(
                        canonical_id,
                        profile,
                        resume_text=resume_text,
                        out_dir=config.application_out_dir,
                    )
                    if prepared.get("ok"):
                        change.notification_ids.append(
                            create_notification(
                                event_type="application_package_prepared",
                                canonical_id=canonical_id,
                                title=f"{job.title} — {job.company}",
                                message=f"Application package prepared for review: {job.title} — {job.company}",
                                readiness_status=READY_TO_APPLY,
                                payload={"generated_paths": prepared.get("generated_paths", {})},
                                dedupe_key=f"application_package_prepared:{canonical_id}:{content_fingerprint(job)}",
                                created_at=now_iso,
                            )
                            or ""
                        )
            elif change.readiness_status == NEEDS_VERIFICATION:
                summary["needs_verification_count"] += 1
            else:
                summary["not_eligible_count"] += 1
            summary["notifications_created"] += len([nid for nid in change.notification_ids if nid])
        except Exception as exc:  # isolate bad vacancy records
            summary["errors"].append({"phase": "process_job", "job": _get(raw_job, "id", ""), "error": str(exc)})

    expired_count = expire_closed_jobs(now_iso=now_iso, today=today, notify=config.notification_preferences.get("closed", True))
    summary["closed_count"] += expired_count
    if config.notification_preferences.get("deadline_alerts", True):
        summary["notifications_created"] += issue_deadline_notifications_for_active_jobs(today=today, thresholds=config.deadline_alert_days)

    source_failed_ids = []
    for err in source_errors:
        source_failed_ids.append(str(err.get("source") or err.get("id") or "source"))
        summary["errors"].append({"phase": "source", **err})
    source_failed_ids = list(dict.fromkeys(source_failed_ids))
    summary["sources_failed"] = source_errors
    successful = set(injected_successful or audit.get("successful", []) or [_source_id_from_job(job) for job in unique_jobs])
    for failed in source_failed_ids:
        successful.discard(failed)
    if not successful and not source_errors and summary["sources_attempted"]:
        successful.update(summary["sources_attempted"])
    summary["sources_successful"] = sorted(successful)
    source_notification_ids = _source_error_notifications(source_errors, now_iso=now_iso) if config.notification_preferences.get("source_failures", True) else []
    summary["notifications_created"] += len(source_notification_ids)

    summary["finished_at"] = now_iso if supplied_now else utc_now_iso()
    finish_scan(scan_id, summary)
    try:
        from utils.events import EventBus

        EventBus.emit("job_watch_scan_complete", summary)
    except Exception:
        pass
    return summary


# ---------------------------------------------------------------------------
# Read APIs
# ---------------------------------------------------------------------------


def _row_to_watch_job(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["source_urls"] = json_loads(item.pop("source_urls_json", "[]"), [])
    item["source_provenance"] = json_loads(item.pop("source_provenance_json", "[]"), [])
    item["last_matching_result"] = json_loads(item.pop("last_matching_result_json", "{}"), {})
    item["notification_state"] = json_loads(item.pop("notification_state_json", "{}"), {})
    item["priority_reasons"] = json_loads(item.pop("priority_reasons_json", "[]"), [])
    item["metadata"] = json_loads(item.pop("metadata_json", "{}"), {})
    return item


def get_watcher_jobs(*, active_only: bool = True, limit: int = 100) -> list[dict[str, Any]]:
    init_watcher_db()
    conn = get_db()
    try:
        if active_only:
            rows = conn.execute(
                """
                SELECT * FROM job_watch_vacancies
                WHERE current_status = ?
                ORDER BY CASE operational_priority
                    WHEN 'APPLY_TODAY' THEN 0 WHEN 'APPLY_SOON' THEN 1 WHEN 'READY' THEN 2
                    WHEN 'VERIFY' THEN 3 WHEN 'LOW' THEN 4 ELSE 5 END,
                    closing_date IS NULL, closing_date, first_discovered_at DESC
                LIMIT ?
                """,
                (ACTIVE_STATUS, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM job_watch_vacancies ORDER BY last_seen_at DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return [_row_to_watch_job(row) for row in rows]


def _recommendation_rank(item: dict[str, Any]) -> tuple[int, str, str]:
    readiness = item.get("readiness_status")
    change_type = item.get("last_change_type")
    closing = item.get("closing_date") or "9999-99-99"
    days = None
    parsed = parse_date(item.get("closing_date"))
    if parsed:
        days = (parsed - date.today()).days
    if change_type == "NEW" and readiness == READY_TO_APPLY:
        bucket = 0
    elif readiness == READY_TO_APPLY and days is not None and days <= 7:
        bucket = 1
    elif change_type == "NEW" and readiness == NEEDS_VERIFICATION:
        bucket = 2
    elif change_type == "UPDATED" and readiness in {READY_TO_APPLY, NEEDS_VERIFICATION}:
        bucket = 3
    elif readiness == READY_TO_APPLY:
        bucket = 4
    else:
        bucket = 5
    return (bucket, closing, item.get("last_changed_at") or item.get("first_discovered_at") or "")


def get_actionable_opportunities(limit: int = 25) -> list[dict[str, Any]]:
    jobs = [
        item
        for item in get_watcher_jobs(active_only=True, limit=500)
        if item.get("readiness_status") in {READY_TO_APPLY, NEEDS_VERIFICATION}
        and item.get("operational_priority") not in {"LOW", "CLOSED"}
    ]
    jobs.sort(key=_recommendation_rank)
    return jobs[:limit]


def get_notifications(*, state: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    init_watcher_db()
    conn = get_db()
    try:
        if state:
            rows = conn.execute(
                "SELECT * FROM job_watch_notifications WHERE state = ? ORDER BY created_at DESC LIMIT ?",
                (state, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM job_watch_notifications ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    items = []
    for row in rows:
        item = dict(row)
        item["payload"] = json_loads(item.pop("payload_json", "{}"), {})
        items.append(item)
    return items


def mark_notification_seen(notification_id: str) -> bool:
    init_watcher_db()
    conn = get_db()
    try:
        cur = conn.execute("UPDATE job_watch_notifications SET state = 'seen' WHERE id = ?", (notification_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_scan_audits(limit: int = 20) -> list[dict[str, Any]]:
    init_watcher_db()
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM job_watch_scans ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    items = []
    for row in rows:
        item = dict(row)
        item["sources_attempted"] = json_loads(item.pop("sources_attempted_json", "[]"), [])
        item["sources_successful"] = json_loads(item.pop("sources_successful_json", "[]"), [])
        item["sources_failed"] = json_loads(item.pop("sources_failed_json", "[]"), [])
        item["errors"] = json_loads(item.pop("errors_json", "[]"), [])
        items.append(item)
    return items


def get_watcher_summary() -> dict[str, Any]:
    init_watcher_db()
    conn = get_db()
    try:
        counts = {}
        for status in [ACTIVE_STATUS, CLOSED_STATUS, EXPIRED_STATUS]:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM job_watch_vacancies WHERE current_status = ?", (status,)).fetchone()
            counts[status.lower()] = row["cnt"]
        for readiness in [READY_TO_APPLY, NEEDS_VERIFICATION, NOT_ELIGIBLE]:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM job_watch_vacancies WHERE current_status = ? AND readiness_status = ?",
                (ACTIVE_STATUS, readiness),
            ).fetchone()
            counts[readiness.lower()] = row["cnt"]
        unread = conn.execute("SELECT COUNT(*) AS cnt FROM job_watch_notifications WHERE state = 'unread'").fetchone()["cnt"]
        last_scan = conn.execute("SELECT * FROM job_watch_scans ORDER BY started_at DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    summary = {"counts": counts, "unread_notifications": unread, "last_scan": None}
    if last_scan:
        summary["last_scan"] = get_scan_audits(limit=1)[0]
    return summary


# ---------------------------------------------------------------------------
# Application-package integration
# ---------------------------------------------------------------------------


def prepare_application_for_watcher_job(
    canonical_id: str,
    profile: dict[str, Any],
    *,
    resume_text: str = "",
    out_dir: str = "documents/applications",
) -> dict[str, Any]:
    """Prepare a review-first package for a watcher vacancy.

    This reuses the existing document/package workflow and updates the existing
    application tracker.  It never submits an application.
    """
    init_watcher_db()
    app_job = get_job_by_id(canonical_id)
    if not app_job:
        return {"ok": False, "error": "Job not found in application tracker"}
    row = _job_row(canonical_id)
    match_report = json_loads(row.get("last_matching_result_json") if row else "{}", {})
    if not match_report:
        match_report = match_job_against_profile(app_job, profile, resume_text=resume_text).to_dict()
        log_medical_match(canonical_id, match_report)
    readiness = readiness_from_match(match_report)
    if readiness == NOT_ELIGIBLE:
        return {
            "ok": False,
            "job_id": canonical_id,
            "readiness_status": readiness,
            "error": "Application package not prepared because deterministic matching classified this vacancy as NOT_ELIGIBLE.",
            "generated_paths": {},
            "application_package": {},
            "no_submission_performed": True,
        }
    from utils.documents import prepare_application_bundle

    docs = prepare_application_bundle(app_job, profile, match_report, resume_text=resume_text, out_dir=out_dir)
    update_tailored_resume(canonical_id, docs)
    return {
        "ok": True,
        "job_id": canonical_id,
        "readiness_status": readiness,
        "generated_paths": docs.get("generated_paths", {}),
        "application_package": docs.get("application_package", {}),
        "no_submission_performed": True,
    }


# ---------------------------------------------------------------------------
# Convenience sync wrapper for CLI/tests
# ---------------------------------------------------------------------------


def run_job_watch_scan_sync(profile: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return asyncio.run(run_job_watch_scan(profile, **kwargs))
