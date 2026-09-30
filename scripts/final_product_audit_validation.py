#!/usr/bin/env python3
"""Reproducible final product audit validation for Jobs-Finder.

This script uses deterministic, local vacancy fixtures based on real Afghan job
search scenarios and official-source evidence captured during the 2026-09-30
final audit. It does not contact employer systems and never submits an
application. It exercises the production pipeline end-to-end with a temporary
SQLite database and writes a machine-readable report under docs/.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import sqlite3
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from dashboard.server import app
from utils import tracker
from utils.discovery import Job
from utils.documents import prepare_application_bundle
from utils.job_watcher import get_actionable_opportunities, get_watcher_jobs, run_job_watch_scan
from utils.medical_matcher import match_job_against_profile
from utils.source_registry import load_source_registry, validate_source_registry

AUDIT_DATE = date(2026, 9, 30)
OUT_PATH = Path("docs/final_product_audit_validation_2026-09-30.json")
DOC_OUT_DIR = Path("documents/final_product_audit_2026-09-30")


def audit_profile() -> dict[str, Any]:
    return {
        "personal": {
            "first_name": "Allah Yar",
            "last_name": "Frotan",
            "full_name": "Dr. Allah Yar Frotan",
            "email": "doctor@example.org",
            "phone": "",
            "location": "Kabul, Afghanistan",
            "nationality": "Afghan",
            "gender": "Male",
        },
        "medical_education": [{"degree": "MD", "institution": "Recognized medical university", "verified": True}],
        "license_registration": {
            "verified": True,
            "authority": "Afghan Medical Council / medical professional registration",
            "status": "Verified — holds valid medical professional registration/license",
            "number": "",
        },
        "medical_exit_exam": {"verified": True, "status": "Verified — completed required Medical Exit Exam"},
        "clinical_experience": {"years": 3},
        "work_history": [
            {
                "title": "Medical Doctor",
                "organization": "Action Against Hunger / Afghanistan health and nutrition programs",
                "location": "Afghanistan",
                "start": "2022-01",
                "end": "2025-07",
                "bullets": [
                    "Provided clinical consultation and patient care in Afghanistan health programs.",
                    "Worked with BPHS/EPHS, HMIS reporting, IMAM/nutrition, IPC, patient safety, and community health teams.",
                    "Supported supervision, training, and health-facility coordination using verified CV evidence only.",
                ],
            }
        ],
        "skills": {
            "clinical": ["OPD/IPD clinical care", "Infection prevention and control", "Patient safety", "SafeCare and clinical protocols"],
            "public_health": ["HMIS", "BPHS", "EPHS", "Nutrition/IMAM", "Health program coordination"],
            "tools": ["MS Office"],
        },
        "languages": [
            {"name": "Dari", "level": "Fluent"},
            {"name": "Pashto", "level": "Fluent"},
            {"name": "English", "level": "Professional"},
        ],
        "preferences": {"locations": ["Afghanistan", "Kabul"], "willing_to_relocate": True, "min_match_score": 65},
        "job_sources": {"fmic": {"enabled": True}, "akhs": {"enabled": True}, "acbar": {"enabled": True}},
        "watcher": {"enabled": True, "scan_interval_hours": 6, "deadline_alert_days": [7, 3, 1], "auto_prepare_ready_to_apply": False},
        "notifications": {"new_jobs": True, "deadline_alerts": True, "source_failures": True},
    }


def resume_text() -> str:
    return (
        "Dr. Allah Yar Frotan is an MD Medical Doctor with verified Afghan Medical Council / medical professional "
        "registration and verified completion of the required Medical Exit Exam. He has conservative dated Afghanistan "
        "clinical and public-health experience, including OPD/IPD care, BPHS/EPHS, HMIS, IMAM/nutrition, IPC, SafeCare, "
        "patient safety, supervision, training, MS Office, Dari, Pashto, and English. No license number, issue date, expiry "
        "date, certificate number, or references are provided."
    )


def _job(
    job_id: str,
    title: str,
    company: str,
    location: str,
    source_url: str,
    apply_url: str,
    source: str,
    description: str,
    closing: str,
    *,
    reliability: str = "high",
    reference: str = "",
    email: str = "",
) -> Job:
    metadata = {
        "source": source,
        "source_url": source_url,
        "original_vacancy_url": source_url,
        "source_urls": [source_url],
        "source_reliability": reliability,
        "source_provenance": [{"source": source, "url": source_url, "reliability": reliability}],
        "closing_date": closing,
        "reference_number": reference,
    }
    if email:
        metadata["application_email"] = email
    return Job(
        id=job_id,
        title=title,
        company=company,
        location=location,
        url=source_url,
        apply_url=apply_url,
        platform=source,
        description=description,
        metadata=metadata,
    )


def vacancy_fixtures(*, fmic_updated: bool = False) -> list[Job]:
    fmic_description = (
        "Medical Officer, FMIC/HR/571. Requirements: Medical Degree from recognized university, registered with Afghan "
        "Medical Council, 1-2 years clinical hospital experience, SafeCare/clinical protocols/infection control/patient "
        "safety, Dari/Pashto/English, MS Office. Closing date: October 05, 2026. Apply at "
        "https://docs.google.com/forms/d/1doS8XyeEEV_aQ7FUW5tnrBSPTJtgHgk1UHm4mjReYQM/edit."
    )
    if fmic_updated:
        fmic_description += " Updated employer note: emergency/OPD duty roster and patient safety coordination clarified."
    fmic = _job(
        "fmic-medical-officer-571",
        "Medical Officer",
        "French Medical Institute for Mothers and Children (FMIC)",
        "Kabul, Afghanistan",
        "https://www.fmic.org.af/WorkWithUs/vacancies/Pages/Medical-Officer-2026.aspx",
        "https://docs.google.com/forms/d/1doS8XyeEEV_aQ7FUW5tnrBSPTJtgHgk1UHm4mjReYQM/edit",
        "fmic",
        fmic_description,
        "2026-10-05",
        reference="FMIC/HR/571",
    )
    fmic_duplicate = _job(
        "fmic-medical-officer-571-signal",
        "Medical Officer",
        "French Medical Institute for Mothers and Children (FMIC)",
        "Kabul, Afghanistan",
        "https://www.fmic.org.af/WorkWithUs/vacancies/Pages/Medical-Officer-2026.aspx?ref=duplicate-signal",
        "https://docs.google.com/forms/d/1doS8XyeEEV_aQ7FUW5tnrBSPTJtgHgk1UHm4mjReYQM/edit",
        "verified_signal",
        fmic_description,
        "2026-10-05",
        reliability="medium",
        reference="FMIC/HR/571",
    )
    akhs = _job(
        "akhs-surgeon-125",
        "Surgeon",
        "AKHS-A",
        "Kabul PHT, Afghanistan",
        "https://akhs.odoo.com/jobs/detail/surgeon-125",
        "https://akhs.odoo.com/jobs/detail/surgeon-125",
        "akhs",
        "Surgeon. Kabul PHT. Requirements: Specialist Surgeon qualification and specialist certification in general "
        "surgery. One year relevant experience. Afghan nationality. Dari and Pashto required. Closing date: Oct 10, 2026. "
        "Apply online at https://akhs.odoo.com/jobs/detail/surgeon-125.",
        "2026-10-10",
    )
    iom = _job(
        "iom-supply-chain-assistant",
        "Supply Chain Assistant",
        "IOM",
        "Kabul, Afghanistan",
        "https://afghanistan.iom.int/careers",
        "mailto:jobs@iom.int",
        "iom_signal",
        "Supply Chain Assistant. Job Requirements: Bachelor degree in Business Administration, Logistics, Procurement or "
        "relevant field is required. Minimum two years of supply chain, procurement and asset management experience. English, "
        "Dari and Pashto required. Closing date: 2026-10-05. Apply by email to jobs@iom.int.",
        "2026-10-05",
        reliability="medium",
        email="jobs@iom.int",
    )
    female_md = _job(
        "ri-female-medical-doctor",
        "Female Medical Doctor",
        "Relief International (RI)",
        "Nimruz, Afghanistan",
        "https://wazifaha.org/jobs/female-medical-doctor-ri-nimruz-2026-signal",
        "mailto:afg.jobs@ri.org",
        "acbar_signal",
        "Female Medical Doctor. MD required. Valid medical registration required. At least 1 year work experience in health "
        "sector. Dari and Pashto required. Female applicants only. Closing date: 2026-10-03. Apply by email to afg.jobs@ri.org.",
        "2026-10-03",
        reliability="medium",
        reference="RI-NIM-HEALTH-2026",
        email="afg.jobs@ri.org",
    )
    expired = _job(
        "expired-medical-officer",
        "Medical Officer",
        "Expired Health NGO",
        "Kabul, Afghanistan",
        "https://example.org/expired-medical-officer",
        "mailto:expired@example.org",
        "expired_fixture",
        "Medical Officer. MD and clinical experience required. Dari and Pashto required. Closing date: 2026-09-20. Apply by email.",
        "2026-09-20",
        reliability="medium",
        email="expired@example.org",
    )
    return [fmic, fmic_duplicate, akhs, iom, female_md, expired]


def _watcher_by_title(title: str) -> dict[str, Any]:
    rows = get_watcher_jobs(active_only=False, limit=100)
    matches = [row for row in rows if row.get("title") == title]
    if not matches:
        raise AssertionError(f"missing watcher row for {title}")
    # Prefer active row when duplicates are possible.
    matches.sort(key=lambda r: (r.get("current_status") != "ACTIVE", r.get("organization") or ""))
    return matches[0]


def _application_by_id(job_id: str) -> dict[str, Any]:
    row = tracker.get_job_by_id(job_id)
    if not row:
        raise AssertionError(f"missing application row {job_id}")
    return row


def inspect_db_integrity(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        duplicate_groups = conn.execute(
            """
            SELECT lower(title) AS title, lower(company) AS company, lower(location) AS location, COUNT(*) AS count
            FROM applications
            GROUP BY lower(title), lower(company), lower(location)
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        orphan_watch_rows = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM job_watch_vacancies w
            LEFT JOIN applications a ON a.id = w.canonical_id
            WHERE a.id IS NULL
            """
        ).fetchone()["count"]
        invalid_status_rows = conn.execute(
            f"SELECT COUNT(*) AS count FROM applications WHERE status NOT IN ({','.join('?' for _ in tracker.VALID_STATUSES)})",
            tracker.VALID_STATUSES,
        ).fetchone()["count"]
        submitted_without_timestamp = conn.execute(
            "SELECT COUNT(*) AS count FROM applications WHERE status IN ('submitted','applied') AND submitted_at IS NULL"
        ).fetchone()["count"]
        submitted_rows = conn.execute("SELECT COUNT(*) AS count FROM applications WHERE status IN ('submitted','applied')").fetchone()["count"]
        missing_provenance = conn.execute(
            "SELECT COUNT(*) AS count FROM job_watch_vacancies WHERE source_provenance_json IS NULL OR source_provenance_json = '' OR source_provenance_json = '[]'"
        ).fetchone()["count"]
        notifications_to_deleted_jobs = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM job_watch_notifications n
            LEFT JOIN job_watch_vacancies w ON w.canonical_id = n.canonical_id
            WHERE n.canonical_id != '' AND w.canonical_id IS NULL
            """
        ).fetchone()["count"]
        expired_actionable = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM job_watch_vacancies
            WHERE current_status = 'ACTIVE' AND closing_date != '' AND date(closing_date) < date('2026-09-30')
            """
        ).fetchone()["count"]
        impossible_timestamps = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM job_watch_vacancies
            WHERE first_discovered_at != '' AND last_seen_at != '' AND datetime(last_seen_at) < datetime(first_discovered_at)
            """
        ).fetchone()["count"]
    finally:
        conn.close()
    return {
        "duplicate_application_groups": [dict(row) for row in duplicate_groups],
        "orphan_watch_rows": orphan_watch_rows,
        "invalid_status_rows": invalid_status_rows,
        "submitted_rows": submitted_rows,
        "submitted_without_timestamp": submitted_without_timestamp,
        "missing_watcher_provenance_rows": missing_provenance,
        "notifications_to_deleted_jobs": notifications_to_deleted_jobs,
        "expired_actionable_rows": expired_actionable,
        "impossible_timestamp_rows": impossible_timestamps,
    }


def document_checks(bundle: dict[str, Any], *, expected_title: str, expected_company: str, expected_keywords: list[str]) -> dict[str, Any]:
    paths = bundle.get("generated_paths", {})
    cv_path = Path(paths["tailored_cv"]["txt"])
    cover_path = Path(paths["cover_letter"]["txt"])
    package_path = Path(paths["application_package_txt"])
    cv = cv_path.read_text(encoding="utf-8")
    cover = cover_path.read_text(encoding="utf-8")
    package = package_path.read_text(encoding="utf-8")
    combined_review_docs = f"{cv}\n{cover}"
    combined_package = f"{combined_review_docs}\n{package}"
    forbidden = ["AMC-", "License No", "Registration No", "certificate number:", "issue date:", "expiry date:", "Reference 1", "Reference 2"]
    return {
        "expected_title_present": expected_title.lower() in combined_review_docs.lower(),
        "expected_company_present": expected_company.lower() in combined_review_docs.lower(),
        "expected_keywords_present": {kw: kw.lower() in combined_package.lower() for kw in expected_keywords},
        "forbidden_identifier_tokens_present": [token for token in forbidden if token.lower() in combined_review_docs.lower()],
        "package_has_no_submission_flag": "no_submission_performed" in json.dumps(bundle.get("application_package", {}), ensure_ascii=False).lower(),
        "package_mentions_manual_review_or_confirmation": ("explicit user confirmation" in package.lower() or "review" in package.lower()),
        "paths": {"cv_txt": str(cv_path), "cover_txt": str(cover_path), "package_txt": str(package_path)},
        "cv_chars": len(cv),
        "cover_chars": len(cover),
    }


def match_report_for(job: Job, profile: dict[str, Any]) -> dict[str, Any]:
    return match_job_against_profile(job.to_dict(), profile, resume_text=resume_text(), today=AUDIT_DATE).to_dict()


async def run_validation() -> dict[str, Any]:
    profile = audit_profile()
    original_db = tracker.DB_PATH
    with tempfile.TemporaryDirectory(prefix="jobs_finder_final_audit_") as tmp:
        tmp_path = Path(tmp)
        audit_db = tmp_path / "final_audit.db"
        tracker.DB_PATH = audit_db
        try:
            registry = load_source_registry()
            registry_issues = validate_source_registry(registry)
            active_sources = [source for source in registry if source.get("reliability_status") == "ACTIVE"]
            enabled_sources = [source for source in registry if source.get("enabled_in_autonomous_discovery")]

            initial_jobs = vacancy_fixtures()

            async def first_discovery(_profile: dict[str, Any]) -> dict[str, Any]:
                return {
                    "jobs": initial_jobs,
                    "sources_attempted": ["fmic", "akhs", "acbar_signal", "iom_signal", "expired_fixture"],
                    "sources_successful": ["fmic", "akhs", "acbar_signal", "iom_signal", "expired_fixture"],
                    "source_errors": [],
                }

            first_summary = await run_job_watch_scan(
                profile,
                discovery_func=first_discovery,
                now=datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc),
                today=AUDIT_DATE,
                resume_text=resume_text(),
                scan_id="final_audit_initial",
            )

            async def repeat_discovery(_profile: dict[str, Any]) -> dict[str, Any]:
                return {
                    "jobs": vacancy_fixtures(),
                    "sources_attempted": ["fmic", "akhs", "acbar_signal", "iom_signal", "expired_fixture"],
                    "sources_successful": ["fmic", "akhs", "acbar_signal", "iom_signal", "expired_fixture"],
                    "source_errors": [],
                }

            repeat_summary = await run_job_watch_scan(
                profile,
                discovery_func=repeat_discovery,
                now=datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc),
                today=AUDIT_DATE,
                resume_text=resume_text(),
                scan_id="final_audit_repeat_unchanged",
            )

            fmic_row = _watcher_by_title("Medical Officer")
            akhs_row = _watcher_by_title("Surgeon")
            iom_row = _watcher_by_title("Supply Chain Assistant")
            female_row = _watcher_by_title("Female Medical Doctor")
            expired_rows = [row for row in get_watcher_jobs(active_only=False, limit=100) if row.get("title") == "Medical Officer" and row.get("organization") == "Expired Health NGO"]
            expired_row = expired_rows[0] if expired_rows else {}

            actionable_before_package = get_actionable_opportunities(limit=25)
            recommended_before_package = tracker.get_recommended_jobs(limit=25)

            fmic_app = _application_by_id(fmic_row["canonical_id"])
            fmic_match = fmic_row["last_matching_result"]
            fmic_bundle = prepare_application_bundle(fmic_app, profile, fmic_match, resume_text=resume_text(), out_dir=DOC_OUT_DIR / "fmic")
            tracker.update_tailored_resume(fmic_row["canonical_id"], fmic_bundle)
            fmic_after_prepare = _application_by_id(fmic_row["canonical_id"])

            akhs_app = _application_by_id(akhs_row["canonical_id"])
            akhs_match = akhs_row["last_matching_result"]
            akhs_bundle = prepare_application_bundle(akhs_app, profile, akhs_match, resume_text=resume_text(), out_dir=DOC_OUT_DIR / "akhs")
            akhs_doc_checks = document_checks(
                akhs_bundle,
                expected_title="Surgeon",
                expected_company="AKHS-A",
                expected_keywords=["surgeon", "specialist"],
            )
            fmic_doc_checks = document_checks(
                fmic_bundle,
                expected_title="Medical Officer",
                expected_company="FMIC",
                expected_keywords=["medical officer", "infection", "patient safety"],
            )
            fmic_cv = Path(fmic_doc_checks["paths"]["cv_txt"]).read_text(encoding="utf-8")
            akhs_cv = Path(akhs_doc_checks["paths"]["cv_txt"]).read_text(encoding="utf-8")
            tailoring_similarity = difflib.SequenceMatcher(None, fmic_cv, akhs_cv).ratio()

            no_confirm_ok, no_confirm_msg = tracker.transition_application_state(
                fmic_row["canonical_id"], "submitted", explicit_confirmation=False
            )
            client = TestClient(app)
            patch_res = client.patch(f"/api/jobs/{fmic_row['canonical_id']}", json={"status": "submitted"})
            apply_wrong_res = client.post(
                f"/api/apply/{fmic_row['canonical_id']}",
                json={"dry_run": False, "confirmation": "WRONG CONFIRMATION"},
            )

            async def updated_discovery(_profile: dict[str, Any]) -> dict[str, Any]:
                return {
                    "jobs": vacancy_fixtures(fmic_updated=True),
                    "sources_attempted": ["fmic", "akhs", "acbar_signal", "iom_signal", "expired_fixture"],
                    "sources_successful": ["fmic", "akhs", "acbar_signal", "iom_signal", "expired_fixture"],
                    "source_errors": [],
                }

            update_summary = await run_job_watch_scan(
                profile,
                discovery_func=updated_discovery,
                now=datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc),
                today=AUDIT_DATE,
                resume_text=resume_text(),
                scan_id="final_audit_material_update",
            )
            fmic_after_update = _application_by_id(fmic_row["canonical_id"])
            fmic_watcher_after_update = _watcher_by_title("Medical Officer")

            async def source_failure_discovery(_profile: dict[str, Any]) -> dict[str, Any]:
                return {
                    "jobs": [],
                    "sources_attempted": ["fmic", "akhs", "blocked_source_fixture"],
                    "sources_successful": [],
                    "source_errors": [{"source": "blocked_source_fixture", "error": "simulated TLS/login/source failure"}],
                }

            failure_summary = await run_job_watch_scan(
                profile,
                discovery_func=source_failure_discovery,
                now=datetime(2026, 9, 30, 11, 0, tzinfo=timezone.utc),
                today=AUDIT_DATE,
                resume_text=resume_text(),
                scan_id="final_audit_source_failure",
            )
            fmic_after_failure = _watcher_by_title("Medical Officer")

            # Match-only edge cases requested by the final audit.
            match_cases = {
                "ready_to_apply_fmic": fmic_row["last_matching_result"].get("readiness_status"),
                "needs_verification_akhs": akhs_row["last_matching_result"].get("readiness_status"),
                "not_eligible_female_only": female_row["last_matching_result"].get("readiness_status"),
                "non_health_needs_verification_low_priority": {
                    "readiness_status": iom_row.get("readiness_status"),
                    "operational_priority": iom_row.get("operational_priority"),
                    "priority_reasons": iom_row.get("priority_reasons"),
                },
            }

            db_integrity = inspect_db_integrity(audit_db)
            final_fmic_app = _application_by_id(fmic_row["canonical_id"])
            final_recommended = tracker.get_recommended_jobs(limit=25)
            final_actionable = get_actionable_opportunities(limit=25)

            evidence = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "audit_date": AUDIT_DATE.isoformat(),
                "temporary_database_used": str(audit_db),
                "profile_used": "embedded audit profile with owner-confirmed MD, Medical Exit Exam, and verified medical registration; no license number provided",
                "source_registry": {
                    "source_count": len(registry),
                    "active_source_ids": [source.get("id") for source in active_sources],
                    "active_source_count": len(active_sources),
                    "enabled_autonomous_source_ids": [source.get("id") for source in enabled_sources],
                    "enabled_autonomous_source_count": len(enabled_sources),
                    "registry_validation_issue_count": len(registry_issues),
                    "registry_validation_issues": registry_issues[:20],
                },
                "scan_summaries": {
                    "initial": first_summary,
                    "repeat_unchanged": repeat_summary,
                    "material_update": update_summary,
                    "source_failure": failure_summary,
                },
                "scenario_results": {
                    "ready_to_apply": {
                        "title": fmic_row.get("title"),
                        "organization": fmic_row.get("organization"),
                        "readiness_status": fmic_row.get("readiness_status"),
                        "operational_priority": fmic_row.get("operational_priority"),
                        "closing_date": fmic_row.get("closing_date"),
                        "application_route": fmic_row.get("application_route"),
                        "canonical_id": fmic_row.get("canonical_id"),
                    },
                    "needs_verification": {
                        "title": akhs_row.get("title"),
                        "organization": akhs_row.get("organization"),
                        "readiness_status": akhs_row.get("readiness_status"),
                        "operational_priority": akhs_row.get("operational_priority"),
                        "priority_reasons": akhs_row.get("priority_reasons"),
                    },
                    "not_eligible": {
                        "title": female_row.get("title"),
                        "organization": female_row.get("organization"),
                        "readiness_status": female_row.get("readiness_status"),
                        "operational_priority": female_row.get("operational_priority"),
                        "not_met_count": female_row.get("last_matching_result", {}).get("counts", {}).get("Not met"),
                    },
                    "non_health_noise_excluded": match_cases["non_health_needs_verification_low_priority"],
                    "duplicate_merge": {
                        "discovered_count": first_summary.get("discovered_count"),
                        "deduplicated_count": first_summary.get("deduplicated_count"),
                        "duplicate_merged": first_summary.get("deduplicated_count") < first_summary.get("discovered_count"),
                        "fmic_source_urls": fmic_row.get("source_urls"),
                    },
                    "unchanged_repeat": {
                        "unchanged_count": repeat_summary.get("unchanged_count"),
                        "updated_count": repeat_summary.get("updated_count"),
                        "new_count": repeat_summary.get("new_count"),
                    },
                    "material_update": {
                        "updated_count": update_summary.get("updated_count"),
                        "fmic_last_change_type": fmic_watcher_after_update.get("last_change_type"),
                        "changed_fields": [c for c in update_summary.get("changes", []) if c.get("canonical_id") == fmic_row.get("canonical_id")][0].get("changed_fields", []),
                        "prepared_status_preserved": fmic_after_update.get("status") == "prepared",
                    },
                    "expired_closed": {
                        "title": expired_row.get("title"),
                        "organization": expired_row.get("organization"),
                        "current_status": expired_row.get("current_status"),
                        "operational_priority": expired_row.get("operational_priority"),
                        "closing_date": expired_row.get("closing_date"),
                    },
                    "source_failure_isolated": {
                        "status": failure_summary.get("status"),
                        "sources_failed": failure_summary.get("sources_failed"),
                        "discovered_count": failure_summary.get("discovered_count"),
                        "fmic_status_after_empty_failure_scan": fmic_after_failure.get("current_status"),
                    },
                    "safe_real_world_flow": {
                        "prepared_status_after_package": fmic_after_prepare.get("status"),
                        "final_status_after_update_and_failure_scans": final_fmic_app.get("status"),
                        "submitted_at": final_fmic_app.get("submitted_at"),
                        "no_submission_timestamp": final_fmic_app.get("submitted_at") in (None, ""),
                        "application_route_verified_not_submitted": fmic_row.get("application_route"),
                        "package_no_submission_performed": fmic_bundle.get("no_submission_performed") is True,
                    },
                    "safety_negative_cases": {
                        "transition_to_submitted_without_confirmation_ok": no_confirm_ok,
                        "transition_to_submitted_without_confirmation_message": no_confirm_msg,
                        "api_patch_submitted_status_code": patch_res.status_code,
                        "api_apply_wrong_confirmation_status_code": apply_wrong_res.status_code,
                        "api_apply_wrong_confirmation_body": apply_wrong_res.json(),
                    },
                    "recommended_focus": {
                        "recommended_titles_before_package": [row.get("title") for row in recommended_before_package],
                        "actionable_titles_before_package": [row.get("title") for row in actionable_before_package],
                        "final_recommended_titles": [row.get("title") for row in final_recommended],
                        "final_actionable_titles": [row.get("title") for row in final_actionable],
                    },
                    "documents": {
                        "fmic": fmic_doc_checks,
                        "akhs": akhs_doc_checks,
                        "tailoring_similarity_ratio_fmic_vs_akhs_cv": tailoring_similarity,
                        "genuinely_tailored": tailoring_similarity < 0.95
                        and all(fmic_doc_checks["expected_keywords_present"].values())
                        and all(akhs_doc_checks["expected_keywords_present"].values()),
                    },
                    "data_integrity": db_integrity,
                },
            }

            checks = {
                "initial_scan_completed": first_summary.get("status") == "COMPLETED",
                "ready_to_apply_fmic": fmic_row.get("readiness_status") == "READY_TO_APPLY" and fmic_row.get("operational_priority") in {"APPLY_TODAY", "APPLY_SOON", "READY"},
                "needs_verification_akhs": akhs_row.get("readiness_status") == "NEEDS_VERIFICATION",
                "not_eligible_female_only": female_row.get("readiness_status") == "NOT_ELIGIBLE",
                "non_health_needs_verification_excluded": iom_row.get("readiness_status") == "NEEDS_VERIFICATION"
                and iom_row.get("operational_priority") == "LOW"
                and "Supply Chain Assistant" not in [row.get("title") for row in final_recommended]
                and "Supply Chain Assistant" not in [row.get("title") for row in final_actionable],
                "duplicate_merged": first_summary.get("deduplicated_count") < first_summary.get("discovered_count"),
                "repeat_scan_unchanged": repeat_summary.get("unchanged_count", 0) >= 4 and repeat_summary.get("updated_count") == 0,
                "material_update_detected": update_summary.get("updated_count", 0) >= 1
                and fmic_watcher_after_update.get("last_change_type") == "UPDATED",
                "prepared_state_preserved_after_rescans": fmic_after_update.get("status") == "prepared" and final_fmic_app.get("status") == "prepared",
                "expired_closed_removed_from_actionable": expired_row.get("current_status") == "EXPIRED"
                and expired_row.get("operational_priority") == "CLOSED"
                and "Expired Health NGO" not in [row.get("organization") for row in final_actionable],
                "source_failure_did_not_close_existing_jobs": failure_summary.get("sources_failed")
                and fmic_after_failure.get("current_status") == "ACTIVE",
                "safe_package_prepared_no_submission": fmic_after_prepare.get("status") == "prepared"
                and final_fmic_app.get("submitted_at") in (None, "")
                and fmic_bundle.get("no_submission_performed") is True,
                "negative_submission_cases_blocked": (not no_confirm_ok)
                and patch_res.status_code == 400
                and apply_wrong_res.status_code == 400,
                "documents_are_tailored": evidence["scenario_results"]["documents"]["genuinely_tailored"] is True,
                "documents_have_expected_vacancy_facts": fmic_doc_checks["expected_title_present"]
                and fmic_doc_checks["expected_company_present"]
                and akhs_doc_checks["expected_title_present"]
                and akhs_doc_checks["expected_company_present"],
                "documents_do_not_invent_sensitive_identifiers": not fmic_doc_checks["forbidden_identifier_tokens_present"]
                and not akhs_doc_checks["forbidden_identifier_tokens_present"],
                "db_integrity_clean": not db_integrity["duplicate_application_groups"]
                and db_integrity["orphan_watch_rows"] == 0
                and db_integrity["invalid_status_rows"] == 0
                and db_integrity["submitted_rows"] == 0
                and db_integrity["missing_watcher_provenance_rows"] == 0
                and db_integrity["notifications_to_deleted_jobs"] == 0
                and db_integrity["expired_actionable_rows"] == 0
                and db_integrity["impossible_timestamp_rows"] == 0,
            }
            evidence["checks"] = checks
            evidence["smoke_test_passed"] = all(bool(value) for value in checks.values())
            return evidence
        finally:
            tracker.DB_PATH = original_db


def main() -> None:
    evidence = asyncio.run(run_validation())
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    failed = [key for key, ok in evidence["checks"].items() if not ok]
    print(f"Final product audit validation written to {OUT_PATH}")
    print(f"smoke_test_passed={evidence['smoke_test_passed']}")
    if failed:
        print("FAILED_CHECKS=" + ", ".join(failed))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
