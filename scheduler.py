"""
Background scheduler — runs the continuous Afghan Job Watcher and legacy
maintenance checks on configurable intervals.

The watcher reuses the existing discovery orchestrator; this module only decides
when to run it and exposes status for the dashboard.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

scheduler = AsyncIOScheduler()
_last_results: dict[str, Any] = {"discover": None, "score": None, "job_watch": None}
_configured = False


def get_profile():
    """Load profile.yaml. Returns None if missing."""
    path = Path(__file__).parent / "profile.yaml"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _positive_float(value: Any, default: float, *, minimum: float = 0.01) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _positive_int(value: Any, default: int, *, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _deadline_days(value: Any) -> list[int]:
    if isinstance(value, str):
        import re
        value = [int(item) for item in re.findall(r"\d+", value)]
    if not isinstance(value, list):
        value = [7, 3, 1]
    days = sorted({int(item) for item in value if str(item).isdigit() and int(item) >= 0}, reverse=True)
    return days or [7, 3, 1]


def get_schedule_settings(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return effective scheduler settings with safe job-search defaults."""
    profile = profile or get_profile() or {}
    schedule_config = profile.get("schedule", {}) if isinstance(profile.get("schedule"), dict) else {}
    watcher_config = profile.get("watcher", {}) if isinstance(profile.get("watcher"), dict) else {}
    enabled = bool(watcher_config.get("enabled", schedule_config.get("enabled", True)))
    scan_interval = watcher_config.get(
        "scan_interval_hours",
        schedule_config.get("job_watch_interval_hours", schedule_config.get("discover_interval_hours", 6)),
    )
    score_minutes = schedule_config.get("score_interval_minutes", 60)
    follow_up_hours = schedule_config.get("follow_up_interval_hours", 6)
    return {
        "enabled": enabled,
        "job_watch_interval_hours": _positive_float(scan_interval, 6),
        "score_interval_minutes": _positive_int(score_minutes, 60),
        "follow_up_interval_hours": _positive_float(follow_up_hours, 6),
        "deadline_alert_days": _deadline_days(watcher_config.get("deadline_alert_days", schedule_config.get("deadline_alert_days", [7, 3, 1]))),
        "auto_prepare_ready_to_apply": bool(watcher_config.get("auto_prepare_ready_to_apply", False)),
    }


async def scheduled_job_watch_scan():
    """Run one persistent watcher scan: discover, match, notify, audit."""
    try:
        from utils.job_watcher import run_job_watch_scan

        profile = get_profile()
        if profile is None:
            return
        result = await run_job_watch_scan(profile)
        _last_results["job_watch"] = result
        _last_results["discover"] = result  # compatibility with existing dashboard labels
        print(
            "[Scheduler] Job watch scan complete: "
            f"{result.get('new_count', 0)} new, {result.get('updated_count', 0)} updated, "
            f"{result.get('unchanged_count', 0)} unchanged"
        )
    except Exception as e:  # pragma: no cover - scheduler safety net
        print(f"[Scheduler] Job watch scan failed: {e}")
        _last_results["job_watch"] = {"error": str(e), "timestamp": datetime.now().isoformat()}
        _last_results["discover"] = _last_results["job_watch"]


async def scheduled_discover():
    """Backward-compatible name used by older endpoints/tests."""
    await scheduled_job_watch_scan()


async def scheduled_score():
    """Analyze any legacy unscored jobs with deterministic medical matching."""
    try:
        from utils.tracker import get_unscored_jobs, log_medical_match
        from utils.medical_matcher import match_job_against_profile
        from utils.resume_parser import extract_resume_text

        profile = get_profile()
        if profile is None:
            return
        unscored = get_unscored_jobs()
        if not unscored:
            return

        resume_text = extract_resume_text(profile.get("resume_path", ""))
        scored = 0
        for job_row in unscored:
            try:
                report = match_job_against_profile(job_row, profile, resume_text=resume_text).to_dict()
                log_medical_match(job_row["id"], report)
                scored += 1
            except Exception:
                pass

        _last_results["score"] = {"scored": scored, "timestamp": datetime.now().isoformat()}
        print(f"[Scheduler] Analyzed {scored} legacy jobs")
    except Exception as e:  # pragma: no cover - scheduler safety net
        print(f"[Scheduler] Analysis failed: {e}")
        _last_results["score"] = {"error": str(e), "timestamp": datetime.now().isoformat()}


async def scheduled_email_check():
    """Check email for application status updates if configured."""
    try:
        from utils.email_checker import check_emails

        profile = get_profile()
        results = check_emails(profile)
        _last_results["email"] = {"checked": len(results), "timestamp": datetime.now().isoformat()}
    except Exception as e:
        print(f"[Scheduler] Email check failed: {e}")


async def scheduled_follow_up_check():
    """Check for overdue follow-ups and ghost alerts."""
    try:
        from utils.tracker import get_overdue_follow_ups, get_ghost_alerts

        overdue = get_overdue_follow_ups()
        ghosts = get_ghost_alerts(days=14)
        if overdue or ghosts:
            print(f"[Scheduler] Follow-up check: {len(overdue)} overdue, {len(ghosts)} ghosts")
        _last_results["follow_up"] = {
            "overdue": len(overdue),
            "ghosts": len(ghosts),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        print(f"[Scheduler] Follow-up check failed: {e}")


def setup_scheduler():
    """Configure scheduler jobs but do not start them yet."""
    global _configured
    profile = get_profile()
    if profile is None:
        print("[Scheduler] No profile.yaml found — skipping scheduler setup (waiting for setup)")
        return
    settings = get_schedule_settings(profile)

    # Avoid stacking duplicate jobs when setup_scheduler() is called again after setup,
    # and remove old jobs when the user disables scheduling.
    for job_id in ["discover", "score", "email", "follow_up"]:
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass

    if not settings["enabled"]:
        _configured = False
        if scheduler.running:
            scheduler.shutdown(wait=False)
        print("[Scheduler] Disabled in profile.yaml")
        return

    scheduler.add_job(
        scheduled_job_watch_scan,
        trigger=IntervalTrigger(hours=settings["job_watch_interval_hours"]),
        id="discover",
        name="Afghan Job Watch Scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        scheduled_score,
        trigger=IntervalTrigger(minutes=settings["score_interval_minutes"]),
        id="score",
        name="Legacy Unscored Job Matching",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    email_config = profile.get("email", {}) if isinstance(profile.get("email"), dict) else {}
    if email_config.get("enabled", False):
        email_hours = email_config.get("check_interval_hours", 12)
        scheduler.add_job(
            scheduled_email_check,
            trigger=IntervalTrigger(hours=email_hours),
            id="email",
            name="Email Check",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    scheduler.add_job(
        scheduled_follow_up_check,
        trigger=IntervalTrigger(hours=settings["follow_up_interval_hours"]),
        id="follow_up",
        name="Follow-up Check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    _configured = True
    print(
        "[Scheduler] Configured — Job watch every "
        f"{settings['job_watch_interval_hours']}h, legacy scoring every {settings['score_interval_minutes']}m"
    )


def start_scheduler():
    """Start the scheduler. Must be called from within a running event loop."""
    if _configured and not scheduler.running:
        scheduler.start()
        print("[Scheduler] Started")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[Scheduler] Stopped")


def get_scheduler_status() -> dict:
    """Get current scheduler status for the dashboard."""
    jobs_info = []
    try:
        for job in scheduler.get_jobs():
            jobs_info.append({
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
            })
    except Exception:
        pass
    return {
        "running": scheduler.running if hasattr(scheduler, "running") else False,
        "jobs": jobs_info,
        "settings": get_schedule_settings(get_profile() or {}),
        "last_results": _last_results,
    }
