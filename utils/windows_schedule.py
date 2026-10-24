"""Opt-in Windows Task Scheduler integration for Jobs-Finder.

No service, account credentials, SMTP secrets, or remote connection is used.
The scheduled task runs under the interactive signed-in Windows account and
continues checking while the dashboard is closed (but not while logged out).
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from utils.paths import PROJECT_ROOT

SCHEDULE_TIME = "09:00"
_SCRIPT = PROJECT_ROOT / "tools" / "windows_daily_check.ps1"


class ScheduleError(RuntimeError):
    """Task Scheduler denied or could not apply the requested change."""


def _execute(action: str) -> str:
    if os.name != "nt":
        raise ScheduleError("Automatic daily checks can only be enabled on Windows.")
    if action not in {"enable", "disable", "status"}:
        raise ValueError("Unsupported schedule action.")
    try:
        result = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(_SCRIPT), "-Action", action,
            ],
            capture_output=True, text=True, timeout=45, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScheduleError("Windows Task Scheduler could not be contacted.") from exc
    if result.returncode:
        details = (result.stderr or result.stdout or "").strip()
        # Don't echo system usernames, project paths or arbitrary PS output
        # into a local web API response.
        reason = details.lower()
        if "another jobs-finder checkout" in reason:
            raise ScheduleError(
                "The daily check is already assigned to a different Jobs-Finder installation. "
                "Disable it from that installation before enabling this one."
            )
        raise ScheduleError(
            "Windows rejected the scheduling operation. "
            + ("Try starting Jobs-Finder once before enabling daily checks."
               if "environment is missing" in reason
               else "Check Windows Task Scheduler permissions and try again.")
        )
    response = result.stdout.strip().splitlines()
    if not response or response[-1].strip() not in {"ENABLED", "DISABLED"}:
        raise ScheduleError("Windows did not confirm the scheduling operation.")
    return response[-1].strip()


def schedule_status() -> dict[str, Any]:
    if os.name != "nt":
        return {
            "supported": False, "enabled": False, "time": SCHEDULE_TIME,
            "message": "Windows daily scheduling is unavailable on this operating system.",
        }
    try:
        value = _execute("status")
    except ScheduleError as exc:
        return {"supported": True, "enabled": False, "time": SCHEDULE_TIME, "error": str(exc)}
    return {
        "supported": True, "enabled": value == "ENABLED", "time": SCHEDULE_TIME,
        "message": "Checks run when this Windows user is signed in, even if the browser is closed.",
    }


def set_schedule(enabled: bool) -> dict[str, Any]:
    value = _execute("enable" if enabled else "disable")
    expected = "ENABLED" if enabled else "DISABLED"
    if value != expected:
        raise ScheduleError("Windows did not confirm the requested state.")
    return schedule_status()
