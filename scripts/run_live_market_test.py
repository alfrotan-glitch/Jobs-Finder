#!/usr/bin/env python3
"""Run live Jobs-Finder market test using the existing discovery/watch workflow.

This is an operational runner, not a new discovery architecture. It uses the
current source registry, existing discovery functions, deterministic matcher, and
review-first package generator.
"""
from __future__ import annotations

import asyncio
import json
import runpy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from utils.profile_builder import build_profile_from_cv_text
from utils.source_registry import active_sources_for_discovery, load_source_registry, validate_source_registry
from utils.job_watcher import (
    READY_TO_APPLY,
    NEEDS_VERIFICATION,
    NOT_ELIGIBLE,
    get_actionable_opportunities,
    get_watcher_jobs,
    prepare_application_for_watcher_job,
    run_job_watch_scan,
)
from utils import tracker

RUN_DATE = date(2026, 9, 30)
RUN_STAMP = "2026-09-30_live_market"
OUT_DIR = Path("documents/live_market_test_2026-09-30")
REPORT_JSON = Path("docs/live_market_test_2026-09-30.json")
REPORT_MD = Path("docs/live_market_test_2026-09-30.md")


def build_profile() -> tuple[dict[str, Any], str]:
    # Existing repository fixture contains the current Dr. Frotan CV/profile facts
    # used by the product tests. The builder normalizes owner-confirmed Medical
    # Exit Exam and professional registration without inventing numbers.
    cv_text = runpy.run_path("tests/test_dr_frotan_profile.py")["SOURCE_CV_EXCERPT"]
    profile = build_profile_from_cv_text(cv_text, resume_path="live_profile_cv_excerpt.txt")
    profile.setdefault("source_registry", {})
    profile["source_registry"].update({"enabled": True, "path": "docs/source_registry.json", "disabled_source_ids": [], "enabled_source_ids": []})
    profile.setdefault("watcher", {})
    profile["watcher"].update({"enabled": True, "scan_interval_hours": 6, "deadline_alert_days": [7, 3, 1], "auto_prepare_ready_to_apply": False, "application_out_dir": str(OUT_DIR)})
    profile.setdefault("notifications", {})
    profile["notifications"].update({"new_jobs": True, "needs_verification": True, "deadline_alerts": True, "updates": True, "closed": True, "source_failures": True})
    profile.setdefault("preferences", {})
    profile["preferences"].update({
        "roles": [
            "Medical Officer", "Medical Doctor", "Physician", "Health Officer", "Nutrition Officer",
            "Public Health", "Health and Nutrition", "Clinical", "HMIS", "BPHS", "EPHS", "IMAM", "IMNCI",
        ],
        "locations": ["Afghanistan", "Kabul", "Daikundi"],
        "preferred_locations": ["Kabul", "Daikundi"],
        "willing_to_relocate": True,
        "field_deployment": True,
    })
    profile.setdefault("search", {})
    profile["search"]["generic_job_boards_enabled"] = False
    return profile, cv_text


def safe_job_summary(row: dict[str, Any]) -> dict[str, Any]:
    result = row.get("last_matching_result") or {}
    counts = result.get("counts") if isinstance(result, dict) else {}
    return {
        "id": row.get("canonical_id") or row.get("id"),
        "title": row.get("title"),
        "company": row.get("organization") or row.get("company"),
        "location": row.get("location"),
        "closing_date": row.get("closing_date"),
        "readiness_status": row.get("readiness_status"),
        "operational_priority": row.get("operational_priority"),
        "application_route": row.get("application_route") or row.get("apply_url"),
        "source_urls": row.get("source_urls") or [],
        "match_counts": counts or {},
        "priority_reasons": row.get("priority_reasons") or [],
    }


def package_summary(prepared: dict[str, Any]) -> dict[str, Any]:
    package = prepared.get("application_package") or {}
    return {
        "job_id": prepared.get("job_id"),
        "ok": prepared.get("ok"),
        "readiness_status": prepared.get("readiness_status"),
        "route_type": package.get("route_type"),
        "package_status": package.get("package_status"),
        "application_route": package.get("application_route"),
        "deadline": package.get("deadline"),
        "no_submission_performed": prepared.get("no_submission_performed"),
        "paths": prepared.get("generated_paths") or {},
        "missing_items": package.get("missing_items") or [],
        "review_warnings": package.get("review_warnings") or [],
    }


async def main() -> None:
    profile, cv_text = build_profile()
    records = load_source_registry(profile=profile)
    registry_errors = validate_source_registry(records)
    active_sources = active_sources_for_discovery(profile, records)

    summary = await run_job_watch_scan(
        profile,
        now=datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc),
        today=RUN_DATE,
        resume_text=cv_text,
        scan_id=RUN_STAMP,
    )

    all_watch_jobs = get_watcher_jobs(active_only=False, limit=1000)
    active_open_jobs = [row for row in all_watch_jobs if row.get("current_status") == "ACTIVE"]
    ready = [row for row in active_open_jobs if row.get("readiness_status") == READY_TO_APPLY]
    needs = [row for row in active_open_jobs if row.get("readiness_status") == NEEDS_VERIFICATION]
    not_eligible = [row for row in active_open_jobs if row.get("readiness_status") == NOT_ELIGIBLE]
    actionable = get_actionable_opportunities(limit=50)

    prepared_packages = []
    for row in sorted(ready, key=lambda r: (r.get("closing_date") or "9999-99-99", r.get("title") or "")):
        prepared = prepare_application_for_watcher_job(
            row["canonical_id"],
            profile,
            resume_text=cv_text,
            out_dir=str(OUT_DIR),
        )
        prepared_packages.append(package_summary(prepared))

    # Re-read tracker statuses after package generation to confirm no submission.
    submission_violations = []
    for pkg in prepared_packages:
        job = tracker.get_job_by_id(pkg["job_id"])
        if job and (job.get("submitted_at") or job.get("status") in {"submitted", "applied"}):
            submission_violations.append({"job_id": pkg["job_id"], "status": job.get("status"), "submitted_at": job.get("submitted_at")})

    evidence = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "market_date_used": RUN_DATE.isoformat(),
        "profile_source": "Existing Dr. Frotan CV/profile fixture normalized by utils.profile_builder; no private identifiers or license number invented.",
        "source_registry": {
            "records": len(records),
            "validation_errors": registry_errors,
            "active_sources_count": len(active_sources),
            "active_sources": [
                {
                    "id": source.get("id"),
                    "status": source.get("reliability_status"),
                    "method": source.get("discovery_method"),
                    "url": source.get("official_jobs_url"),
                }
                for source in active_sources
            ],
        },
        "scan_summary": summary,
        "counts": {
            "jobs_discovered_raw": summary.get("discovered_count"),
            "jobs_after_deduplication": summary.get("deduplicated_count"),
            "open_relevant_jobs": len(active_open_jobs),
            "ready_to_apply": len(ready),
            "needs_verification": len(needs),
            "not_eligible": len(not_eligible),
            "packages_prepared": len([pkg for pkg in prepared_packages if pkg.get("ok")]),
        },
        "ready_to_apply": [safe_job_summary(row) for row in ready],
        "needs_verification": [safe_job_summary(row) for row in needs],
        "not_eligible": [safe_job_summary(row) for row in not_eligible],
        "all_open_relevant_jobs": [safe_job_summary(row) for row in active_open_jobs],
        "best_actionable_by_deadline": [safe_job_summary(row) for row in actionable[:20]],
        "packages_prepared": prepared_packages,
        "submission_violations": submission_violations,
    }

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Live Afghan Job Market Test — 2026-09-30",
        "",
        f"Run at: {evidence['run_at']}",
        f"Active registry sources used: {len(active_sources)}",
        f"Registry validation errors: {len(registry_errors)}",
        "",
        "## Counts",
        "",
    ]
    for key, value in evidence["counts"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## READY_TO_APPLY", ""])
    if ready:
        for row in evidence["ready_to_apply"]:
            lines.append(f"- {row['title']} — {row['company']} — deadline {row['closing_date'] or 'N/A'} — route: {row['application_route'] or 'N/A'}")
    else:
        lines.append("- None found in this live run.")
    lines.extend(["", "## NEEDS_VERIFICATION", ""])
    for row in evidence["needs_verification"]:
        lines.append(f"- {row['title']} — {row['company']} — deadline {row['closing_date'] or 'N/A'} — priority {row['operational_priority']}")
    if not needs:
        lines.append("- None.")
    lines.extend(["", "## NOT_ELIGIBLE", ""])
    for row in evidence["not_eligible"]:
        lines.append(f"- {row['title']} — {row['company']} — deadline {row['closing_date'] or 'N/A'} — priority {row['operational_priority']}")
    if not not_eligible:
        lines.append("- None.")
    lines.extend(["", "## Packages prepared", ""])
    if prepared_packages:
        for pkg in prepared_packages:
            lines.append(f"- {pkg['job_id']} — {pkg['package_status']} — route: {pkg['application_route'] or 'N/A'}")
            paths = pkg.get("paths") or {}
            for label, value in paths.items():
                lines.append(f"  - {label}: {value}")
    else:
        lines.append("- None because no READY_TO_APPLY vacancy was found.")
    lines.extend(["", "## Best actionable opportunities by deadline", ""])
    if actionable:
        for row in evidence["best_actionable_by_deadline"]:
            lines.append(f"- {row['closing_date'] or 'N/A'} — {row['title']} — {row['company']} — {row['readiness_status']} — {row['application_route'] or 'N/A'}")
    else:
        lines.append("- None.")
    lines.extend(["", "## Source failures / blockers", ""])
    failures = summary.get("sources_failed") or []
    if failures:
        for failure in failures:
            lines.append(f"- {failure}")
    else:
        lines.append("- None reported by the scan.")
    if submission_violations:
        lines.extend(["", "## SAFETY ISSUE", ""])
        lines.append(json.dumps(submission_violations, ensure_ascii=False, indent=2))
    else:
        lines.extend(["", "Safety: no submission performed and no submitted/applied status was recorded."])
    REPORT_MD.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    print(f"Live market report JSON: {REPORT_JSON}")
    print(f"Live market report MD: {REPORT_MD}")
    print(json.dumps(evidence["counts"], ensure_ascii=False, indent=2))
    if submission_violations:
        raise SystemExit("Submission safety violation detected")


if __name__ == "__main__":
    asyncio.run(main())
