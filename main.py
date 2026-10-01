#!/usr/bin/env python3
"""Jobs-Finder — Afghanistan job finder and application package assistant."""

from __future__ import annotations

import argparse
import asyncio
import sys
import webbrowser
from pathlib import Path
from typing import Any

import yaml

from utils.discovery import PARTIAL_SCAN, SOURCES_UNAVAILABLE, run_discovery_scan
from utils.documents import prepare_application_bundle
from utils.medical_matcher import NOT_ELIGIBLE_STATUS, match_job_against_profile
from utils.profile import save_profile
from utils.profile_builder import build_profile_from_cv_file
from utils.recommendations import evaluate_scan_jobs
from utils.resume_parser import extract_resume_text
from utils.source_registry import normalize_profile_source_budgets
from utils.tracker import (
    delete_all,
    get_job_by_id,
    get_recommended_jobs,
    list_actionable_jobs,
    log_medical_match,
    log_scan_result,
    mark_applied_manually,
    print_stats,
    update_tailored_resume,
)

PROFILE_PATH = Path("profile.yaml")


def load_profile(path: str = "profile.yaml", *, required: bool = True) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        if required:
            print(f"Profile not found: {path}")
            print("Copy profile.yaml.example to profile.yaml and enter verified facts first.")
            sys.exit(1)
        return {}
    profile = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    # Remove untouched builder-era discovery budgets (see
    # utils/source_registry.py). This is the load-time migration that stops a
    # CV-import-era profile.yaml from silently capping real scans at 6 listing
    # pages / 30 detail pages; anything the user actually edited is preserved.
    _profile, budget_notes = normalize_profile_source_budgets(profile)
    for note in budget_notes:
        print(note)
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    missing = [field for field in ["first_name", "last_name", "email"] if not personal.get(field)]
    if missing and required:
        print(f"Missing required profile fields: {', '.join(missing)}")
        sys.exit(1)
    return profile


def _resume_text(profile: dict[str, Any]) -> str:
    return extract_resume_text(profile.get("resume_path", ""))


def print_scan_accounting(scan: Any) -> None:
    """Render backend-authoritative counters without reconstructing them."""
    print("Source details:")
    for report in scan.source_reports:
        print(f"\nSource: {report.name}")
        print(f"Status: {report.status}")
        print(f"Pages: {report.pages_requested} requested / {report.pages_succeeded} succeeded / {report.pages_failed} failed")
        print(f"Pagination: {report.pagination_stop_reason}")
        if getattr(report, "source_listings_reported", None) is not None:
            print(f"Source listings reported: {report.source_listings_reported}")
        page_limit = getattr(report, "configured_page_limit", None)
        detail_limit = getattr(report, "configured_detail_limit", None)
        if page_limit is not None or detail_limit is not None:
            print(f"Configured limits: pages={page_limit if page_limit is not None else 'unbounded'}, details={detail_limit if detail_limit is not None else 'unbounded'}")
        print(f"Listings seen: {report.listings_seen}")
        print(f"Parse failures: {report.listing_parse_failures}")
        print(f"Vacancies parsed: {report.vacancies_parsed}")
        print(f"Not processed due to budget: {report.not_processed_due_to_budget}")
        print(f"Detail pages: {report.detail_pages_attempted} attempted / {report.detail_pages_succeeded} succeeded / {report.detail_pages_failed} failed")
        print(f"Listing fallback used: {report.listing_fallback_used}")
        print(f"Duplicates removed: {report.duplicates_removed}")
        print(f"Expired: {report.expired_excluded}")
        print(f"Irrelevant: {report.irrelevant_excluded}")
        print(f"Incompatible role classification: {report.incompatible_role_classification_excluded}")
        print(f"Source validation: {report.source_validation_excluded}")
        print(f"Relevant retained: {report.relevant_retained}")
        print(f"Application routes: {report.application_routes_found} found / {report.application_routes_unavailable} unavailable")
        print(f"Partial reasons: {', '.join(report.partial_reasons) if report.partial_reasons else 'None'}")
        if report.error:
            print(f"Errors: {report.error}")
    summary = scan.summary()
    print("\nOVERALL")
    print(f"Sources: {summary['sources_attempted']} attempted / {summary['sources_scanned']} scanned / {summary['sources_partial']} partial / {summary['sources_unavailable']} unavailable / {summary['sources_failed']} failed")
    print(f"Pages: {summary['pages_requested']} requested / {summary['pages_succeeded']} succeeded / {summary['pages_failed']} failed")
    for label, key in [
        ("Listings seen", "listings_seen"), ("Parse failures", "listing_parse_failures"),
        ("Vacancies parsed", "vacancies_parsed"), ("Not processed due to budget", "not_processed_due_to_budget"),
        ("Duplicates removed", "duplicates_removed"), ("Expired", "expired_excluded"),
        ("Irrelevant", "irrelevant_excluded"), ("Incompatible role classification", "incompatible_role_classification_excluded"),
        ("Source validation", "source_validation_excluded"), ("Relevant retained", "relevant_retained"),
    ]:
        print(f"{label}: {summary[key]}")
    print(f"Application routes: {summary['application_routes_found']} found / {summary['application_routes_unavailable']} unavailable")
    print(f"Recommended from this scan: {summary['recommended_from_scan']}")
    actionable = summary["ready_to_apply_from_scan"] + summary["needs_verification_from_scan"]
    gated = actionable - summary["recommended_from_scan"]
    if gated > 0:
        print(f"Note: {gated} retained vacancy(ies) stay in the jobs list for manual review but are not recommended: their professional role family is not positively MD/public-health compatible (e.g. generic programme/operations titles with health wording only).")
    print(f"Readiness: {summary['ready_to_apply_from_scan']} ready / {summary['needs_verification_from_scan']} needs verification / {summary['not_eligible_from_scan']} not eligible")


async def cmd_scan(profile: dict[str, Any]) -> dict[str, Any]:
    print("Finding Afghanistan health/medical vacancies...")
    scan = await run_discovery_scan(profile)
    resume_text = _resume_text(profile)
    # One shared orchestration (also used by the dashboard): store, match, and
    # record — the recommendation collection is derived once, authoritatively.
    evaluate_scan_jobs(scan, profile, resume_text)
    log_scan_result(scan.to_dict())
    print(scan.message)
    print_scan_accounting(scan)
    print_scan_recommendations(scan)
    return scan.to_dict()


def print_scan_recommendations(scan: Any) -> None:
    """Print exactly the scan's authoritative recommendation collection.

    The number printed here is structurally identical to the
    "Recommended from this scan" counter: both are derived from
    ``scan.recommendations`` — never from a separate tracker re-query.
    """
    if not scan.jobs:
        return
    print("\nRecommended vacancies:")
    if not scan.recommendations:
        print("None from this scan. Broad discovery results remain reviewable under: python main.py jobs")
        return
    _print_recommendation_entries(scan.recommendations)


def _print_recommendation_entries(jobs: list[dict[str, Any]]) -> None:
    for index, job in enumerate(jobs, start=1):
        match = job.get("match") or {}
        metadata = job.get("metadata") or {}
        route = metadata.get("apply_url") or metadata.get("vacancy_url") or job.get("apply_url") or job.get("url")
        print(f"{index}. {job['title']} — {job['company']} ({job.get('location') or 'Location not listed'})")
        print(f"   ID: {job['id']}")
        print(f"   Source: {metadata.get('source_name') or job.get('source') or 'Source not listed'}")
        print(f"   Readiness: {job.get('readiness') or match.get('readiness_status') or 'Needs review'}")
        if metadata.get("closing_date"):
            print(f"   Deadline: {metadata['closing_date']}")
        if route:
            print(f"   Official route: {route}")
        if match.get("explanation"):
            print(f"   {match['explanation']}")


def print_recommended(limit: int = 20) -> None:
    jobs = get_recommended_jobs(limit=limit)
    if not jobs:
        print("No recommended vacancies yet. Run: python main.py find")
        return
    _print_recommendation_entries(jobs)


def cmd_prepare(profile: dict[str, Any], job_id: str) -> dict[str, Any] | None:
    job = get_job_by_id(job_id)
    if not job:
        print(f"Vacancy not found: {job_id}")
        return None
    resume_text = _resume_text(profile)
    report = match_job_against_profile(job, profile, resume_text=resume_text).to_dict()
    log_medical_match(job_id, report)
    if report.get("readiness_status") == NOT_ELIGIBLE_STATUS:
        print("Not preparing a package: this vacancy is classified NOT_ELIGIBLE.")
        print(report.get("explanation", ""))
        return None
    docs = prepare_application_bundle(job, profile, report, resume_text=resume_text)
    update_tailored_resume(job_id, docs)
    package = docs.get("application_package", {})
    print(f"Prepared package: {job['title']} — {job['company']}")
    print(f"Package status: {package.get('package_status')}")
    print("Generated files:")
    for label, value in (docs.get("generated_paths") or {}).items():
        print(f"- {label}: {value}")
    if package.get("missing_items"):
        print("Review warnings / missing items:")
        for item in package["missing_items"]:
            print(f"- {item}")
    return docs


def cmd_open(job_id: str) -> None:
    job = get_job_by_id(job_id)
    if not job:
        print(f"Vacancy not found: {job_id}")
        return
    package = job.get("package") or {}
    metadata = job.get("metadata") or {}
    email = package.get("apply_email") or metadata.get("apply_email") or job.get("apply_email") or ""
    web_url = package.get("apply_url") or metadata.get("apply_url") or job.get("apply_url") or ""
    vacancy_url = package.get("official_vacancy_page") or metadata.get("vacancy_url") or job.get("url") or ""
    if email:
        print(f"Opening email application draft to: {email}")
        webbrowser.open(f"mailto:{email}")
        return
    url = web_url or vacancy_url
    if not url:
        print("No official application route is stored. Open the source vacancy URL manually.")
        return
    print(f"Opening official vacancy/application page: {url}")
    webbrowser.open(url)


def cmd_mark_applied(job_id: str) -> None:
    phrase = f"APPLIED {job_id}"
    typed = input(f"If you manually submitted this application, type '{phrase}' to record it: ").strip()
    if typed != phrase:
        print("Not recorded.")
        return
    ok, message = mark_applied_manually(job_id, confirmation=typed)
    print(message if ok else f"Could not record: {message}")


def cmd_import_cv(cv_path: str, profile_path: str) -> None:
    profile = build_profile_from_cv_file(cv_path, resume_path=cv_path)
    save_profile(profile, profile_path)
    print(f"Structured profile written to {profile_path}")
    print("Review it before scanning. Missing evidence remains Needs verification.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Jobs-Finder — Afghanistan job finder and application package assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("find", help="Find, normalize, match, and store Afghanistan vacancies")
    sub.add_parser("recommended", help="Show vacancies worth reviewing now")
    sub.add_parser("jobs", help="Show all stored vacancies")
    sub.add_parser("stats", help="Show simple stored-vacancy counts")
    sub.add_parser("reset", help="Delete stored vacancies and packages from the local database")

    prepare = sub.add_parser("prepare", help="Prepare a vacancy-specific CV, cover letter, and application package")
    prepare.add_argument("job_id")

    open_cmd = sub.add_parser("open", help="Open the official application route for a stored vacancy")
    open_cmd.add_argument("job_id")

    applied = sub.add_parser("mark-applied", help="Record a user-confirmed manual application")
    applied.add_argument("job_id")

    import_cv = sub.add_parser("import-cv", help="Build profile.yaml from a text/PDF CV for user review")
    import_cv.add_argument("cv_path")
    import_cv.add_argument("--profile", default="profile.yaml")



    server = sub.add_parser("server", help="Launch the web dashboard")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8080)

    args = parser.parse_args()

    if args.command == "server":
        from dashboard.server import run_server
        run_server(host=args.host, port=args.port)
        return
    if args.command == "import-cv":
        cmd_import_cv(args.cv_path, args.profile)
        return
    if args.command == "recommended":
        print_recommended()
        return
    if args.command == "jobs":
        for job in list_actionable_jobs():
            print(f"{job['id']} | {job['status']} | {job['title']} — {job['company']}")
        return
    if args.command == "stats":
        print_stats()
        return
    if args.command == "reset":
        print(f"Deleted {delete_all()} stored vacancies.")
        return

    profile = load_profile()
    if args.command == "find":
        asyncio.run(cmd_scan(profile))
    elif args.command == "prepare":
        cmd_prepare(profile, args.job_id)
    elif args.command == "open":
        cmd_open(args.job_id)
    elif args.command == "mark-applied":
        cmd_mark_applied(args.job_id)


if __name__ == "__main__":
    main()
