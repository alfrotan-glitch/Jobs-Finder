#!/usr/bin/env python3
"""
Afghan MD Job Assistant
=======================

Review-first workflow:
    discover -> analyze -> prepare documents -> open application -> confirm -> track

AI is optional. Deterministic medical requirement extraction and matching work
without API keys or model CLIs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import webbrowser
from pathlib import Path
from typing import Any

import yaml
from playwright.async_api import async_playwright

from adapters.stagehand_adapter import apply_smart
from utils.discovery import discover_all_jobs
from utils.documents import prepare_application_bundle
from utils.job_watcher import run_job_watch_scan_sync
from utils.medical_matcher import NOT_ELIGIBLE_STATUS, match_job_against_profile
from utils.resume_parser import extract_resume_text
from utils.profile_builder import build_profile_from_cv_file
from utils.profile import save_profile
from utils.master_cv import create_master_cv
from utils.tracker import (
    delete_all,
    get_job_by_id,
    get_recommended_jobs,
    get_tailored_resume,
    get_unscored_jobs,
    is_already_seen,
    log_discovered,
    log_medical_match,
    print_stats,
    transition_application_state,
    update_tailored_resume,
)


PROFILE_PATH = Path("profile.yaml")


def load_profile(path: str = "profile.yaml") -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        print(f"❌ Profile not found: {path}")
        print("   Copy profile.yaml.example to profile.yaml or start the web app setup wizard.")
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        profile = yaml.safe_load(f) or {}

    personal = profile.get("personal", {})
    missing = [field for field in ["first_name", "last_name", "email"] if not personal.get(field)]
    if missing:
        print(f"❌ Missing required profile fields: {', '.join(missing)}")
        sys.exit(1)

    resume = profile.get("resume_path", "")
    if resume and not Path(resume).expanduser().exists():
        print(f"⚠ CV not found at: {resume}")
        print("  Matching will still run, but evidence from the CV will be unavailable.")
    return profile


async def analyze_and_store(job, profile: dict, resume_text: str) -> dict:
    report = match_job_against_profile(job.to_dict() if hasattr(job, "to_dict") else job, profile, resume_text=resume_text).to_dict()
    log_medical_match(job.id if hasattr(job, "id") else job["id"], report)
    return report


def cmd_watch(profile: dict):
    """Run one persistent job-watch scan and print a concise audit."""
    print("\n👀 Running Afghan Job Watch scan...\n")
    result = run_job_watch_scan_sync(profile)
    print(f"Scan ID: {result.get('scan_id')}")
    print(
        f"Discovered {result.get('discovered_count', 0)}; "
        f"deduplicated {result.get('deduplicated_count', 0)}; "
        f"new {result.get('new_count', 0)}; updated {result.get('updated_count', 0)}; "
        f"unchanged {result.get('unchanged_count', 0)}; closed {result.get('closed_count', 0)}"
    )
    print(
        f"READY_TO_APPLY {result.get('ready_to_apply_count', 0)}; "
        f"NEEDS_VERIFICATION {result.get('needs_verification_count', 0)}; "
        f"NOT_ELIGIBLE {result.get('not_eligible_count', 0)}"
    )
    if result.get("errors"):
        print("\nAdvanced/source warnings:")
        for error in result["errors"]:
            print(f"- {error.get('phase', 'source')}: {error.get('source', '')} {error.get('error', '')}")
    print_recommended()


async def cmd_discover(profile: dict):
    """Find Afghan medical jobs and analyze deterministic eligibility."""
    resume_text = extract_resume_text(profile.get("resume_path", ""))
    print("\n🔎 Finding Afghanistan medical jobs...\n")
    jobs = await discover_all_jobs(profile)
    if not jobs:
        print("No matching medical vacancies found. Check Settings/My Profile sources or try again later.")
        return

    new_count = 0
    analyzed_count = 0
    for i, job in enumerate(jobs, start=1):
        already = is_already_seen(job.id)
        if not already:
            log_discovered(job)
            new_count += 1
        report = await analyze_and_store(job, profile, resume_text)
        analyzed_count += 1
        print(f"[{i}/{len(jobs)}] {report['priority']}: {job.title} @ {job.company}")
        print(f"    {report['explanation']}")

    print(f"\nDone: {new_count} new jobs, {analyzed_count} analyzed.")
    print_recommended()


def print_recommended(limit: int = 10):
    jobs = get_recommended_jobs(limit=limit)
    print("\nWhich jobs should you look at today?")
    if not jobs:
        print("  No analyzed jobs yet. Run: python main.py discover")
        return
    for i, job in enumerate(jobs, start=1):
        print(f"  {i}. [{job.get('priority') or job.get('status')}] {job['title']} @ {job['company']} — {job.get('location') or 'Location not listed'}")
        if job.get("closing_date"):
            print(f"     Closing date: {job['closing_date']}")
        print(f"     ID: {job['id']}")


async def cmd_rescore(profile: dict):
    """Analyze jobs that do not yet have deterministic MD matching."""
    resume_text = extract_resume_text(profile.get("resume_path", ""))
    jobs = get_unscored_jobs()
    if not jobs:
        print("No un-analyzed jobs found.")
        return
    for i, row in enumerate(jobs, start=1):
        report = match_job_against_profile(row, profile, resume_text=resume_text).to_dict()
        log_medical_match(row["id"], report)
        print(f"[{i}/{len(jobs)}] {report['priority']}: {row['title']} @ {row['company']}")
    print_recommended()


def cmd_prepare(profile: dict, job_id: str):
    """Generate a complete review-first application package for a job."""
    job = get_job_by_id(job_id)
    if not job:
        print(f"Job not found: {job_id}")
        return
    resume_text = extract_resume_text(profile.get("resume_path", ""))
    report = match_job_against_profile(job, profile, resume_text=resume_text).to_dict()
    log_medical_match(job_id, report)
    if report.get("readiness_status") == NOT_ELIGIBLE_STATUS:
        print("Not preparing documents: deterministic matching classified this vacancy as NOT_ELIGIBLE.")
        print(report.get("explanation", ""))
        return
    docs = prepare_application_bundle(job, profile, report, resume_text=resume_text)
    update_tailored_resume(job_id, docs)
    package = docs.get("application_package", {})
    paths = docs.get("generated_paths", {})
    print(f"Prepared review package for {job['title']} @ {job['company']}.")
    print(f"Package status: {package.get('package_status', 'UNKNOWN')}")
    print("\n--- Suggested subject ---")
    print(docs.get("suggested_subject", ""))
    print("\n--- Generated files ---")
    for label, value in paths.items():
        print(f"{label}: {value}")
    print("\n--- Application package ---")
    print(package.get("text", ""))
    if docs.get("review_warnings"):
        print("\nReview warnings:")
        for warning in docs["review_warnings"]:
            print(f"- {warning}")


def cmd_open(job_id: str):
    """Open the real application page and mark it opened."""
    job = get_job_by_id(job_id)
    if not job:
        print(f"Job not found: {job_id}")
        return
    url = job.get("apply_url") or job.get("url")
    if not url:
        print("This job has no application URL. Open the source URL manually and verify application instructions.")
        return
    transition_application_state(job_id, "opened")
    print(f"Opening application page: {url}")
    webbrowser.open(url)


async def cmd_fill(profile: dict, job_id: str, live: bool = False):
    """Assist with safe form filling. Stops before submit unless explicitly confirmed."""
    job = get_job_by_id(job_id)
    if not job:
        print(f"Job not found: {job_id}")
        return
    if not job.get("apply_url"):
        print("Job has no application URL.")
        return

    dry_run = True
    if live:
        phrase = f"SUBMIT {job_id}"
        print("⚠ Final submission can send a real application.")
        print("Only continue after you personally reviewed the form and documents.")
        typed = input(f"Type '{phrase}' to allow final submit, or press Enter to dry-run: ").strip()
        dry_run = typed != phrase
        if dry_run:
            print("Proceeding in review-only dry-run mode.")

    from utils.brain import ClaudeBrain

    brain = ClaudeBrain(verbose=True, profile=profile)
    docs = get_tailored_resume(job_id)
    cover_letter = docs.get("cover_letter") or docs.get("tailored_cover_letter") or job.get("cover_letter", "")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=100)
        context = await browser.new_context(viewport={"width": 1600, "height": 1000})
        page = await context.new_page()
        success = await apply_smart(
            page,
            job.get("apply_url"),
            profile,
            brain,
            cover_letter=cover_letter,
            dry_run=dry_run,
            platform=job.get("platform", ""),
            company=job.get("company", ""),
            title=job.get("title", ""),
            description=job.get("description", ""),
        )
        if dry_run:
            transition_application_state(job_id, "opened")
            print("\nReview-only mode complete. Browser will stay open for 5 minutes.")
            await asyncio.sleep(300)
        else:
            ok, message = transition_application_state(job_id, "submitted", explicit_confirmation=True, note="Submitted via assisted browser flow")
            print("Submission tracked." if ok else f"Tracking warning: {message}")
        await browser.close()
        return success


def cmd_mark_submitted(job_id: str):
    phrase = f"SUBMITTED {job_id}"
    typed = input(f"If you manually submitted this application, type '{phrase}' to record it: ").strip()
    if typed != phrase:
        print("Not recorded.")
        return
    ok, message = transition_application_state(job_id, "submitted", explicit_confirmation=True, note="User confirmed manual submission")
    print("Recorded as submitted." if ok else f"Could not record: {message}")


def cmd_import_cv(cv_path: str, profile_path: str = "profile.yaml"):
    """Create a structured master profile from a user-supplied CV text/PDF file."""
    profile = build_profile_from_cv_file(cv_path, resume_path=cv_path)
    save_profile(profile, profile_path)
    print(f"Structured profile written to {profile_path}")
    print("Review My Profile before applying. License/registration remains Needs verification unless it is explicitly stated.")


def cmd_create_master_cv(profile_path: str = "profile.yaml", out_dir: str = "documents"):
    bundle = create_master_cv(profile_path, out_dir=out_dir)
    print("Master CV created:")
    print(f"  Markdown: {bundle.markdown_path}")
    print(f"  DOCX:     {bundle.docx_path}")
    print(f"  PDF:      {bundle.pdf_path}")
    print(f"  Review:   {bundle.review_path}")


def cmd_reset():
    count = delete_all()
    print(f"Deleted {count} jobs. Profile and ignored list are unchanged.")


def main():
    parser = argparse.ArgumentParser(description="Afghan MD Job Assistant — safe, deterministic, review-first")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("watch", help="Run one persistent Afghan Job Watch scan")
    subparsers.add_parser("discover", help="Find and analyze Afghanistan medical jobs once (legacy non-persistent command)")
    subparsers.add_parser("recommended", help="Show jobs to review today")
    subparsers.add_parser("stats", help="View application stats")
    subparsers.add_parser("reset", help="Delete tracked jobs")
    subparsers.add_parser("rescore", help="Analyze unscored/unmatched jobs")

    import_cv = subparsers.add_parser("import-cv", help="Build profile.yaml from a pasted/exported CV text or PDF file")
    import_cv.add_argument("cv_path")
    import_cv.add_argument("--profile", default="profile.yaml")

    master_cv = subparsers.add_parser("create-master-cv", help="Export the professional master CV to Markdown, DOCX, and PDF")
    master_cv.add_argument("--profile", default="profile.yaml")
    master_cv.add_argument("--out-dir", default="documents")

    prepare = subparsers.add_parser("prepare", help="Generate tailored CV and cover letter for a job")
    prepare.add_argument("job_id")

    open_cmd = subparsers.add_parser("open", help="Open a job's real application page")
    open_cmd.add_argument("job_id")

    fill = subparsers.add_parser("fill", help="Fill application form safely; dry-run by default")
    fill.add_argument("job_id")
    fill.add_argument("--live", action="store_true", help="Allow final submit only after explicit typed confirmation")

    submitted = subparsers.add_parser("mark-submitted", help="Record a manually submitted application")
    submitted.add_argument("job_id")

    server = subparsers.add_parser("server", help="Launch web app")
    server.add_argument("--port", type=int, default=8080)
    server.add_argument("--host", default="0.0.0.0")

    args = parser.parse_args()

    if args.command == "stats":
        print_stats()
        return
    if args.command == "reset":
        cmd_reset()
        return
    if args.command == "recommended":
        print_recommended()
        return
    if args.command == "server":
        from dashboard.server import run_server

        try:
            from scheduler import setup_scheduler

            setup_scheduler()
        except Exception as e:
            print(f"Scheduler setup warning: {e}")
        run_server(host=args.host, port=args.port)
        return

    if args.command == "import-cv":
        cmd_import_cv(args.cv_path, profile_path=args.profile)
        return

    if args.command == "create-master-cv":
        cmd_create_master_cv(profile_path=args.profile, out_dir=args.out_dir)
        return

    profile = load_profile()
    if args.command == "watch":
        cmd_watch(profile)
    elif args.command == "discover":
        asyncio.run(cmd_discover(profile))
    elif args.command == "rescore":
        asyncio.run(cmd_rescore(profile))
    elif args.command == "prepare":
        cmd_prepare(profile, args.job_id)
    elif args.command == "open":
        cmd_open(args.job_id)
    elif args.command == "fill":
        asyncio.run(cmd_fill(profile, args.job_id, live=args.live))
    elif args.command == "mark-submitted":
        cmd_mark_submitted(args.job_id)


if __name__ == "__main__":
    main()
