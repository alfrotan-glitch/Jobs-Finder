"""Best-effort Windows desktop notification for opt-in scheduled job checks.

This is only a lightweight desktop convenience. The persisted SQLite inbox
always contains the actual alerts even when Windows notification settings,
Focus Assist, or session restrictions hide the popup.
"""

from __future__ import annotations

import os
import subprocess

from utils.paths import PROJECT_ROOT


def show_alert_balloon(count: int) -> bool:
    if os.name != "nt" or not 1 <= count <= 999:
        return False
    script = PROJECT_ROOT / "tools" / "windows_alert_balloon.ps1"
    try:
        subprocess.Popen(
            [
                "powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(script),
                "-Count", str(int(count)),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except OSError:
        # No exception may undermine a successfully saved vacancy/alert scan.
        return False
