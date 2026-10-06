"""Git-boundary regression for the one private applicant profile."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_canonical_profile_is_ignored_and_never_tracked():
    root = Path(__file__).resolve().parents[1]
    profile = root / "profile.yaml"

    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", str(profile)],
        cwd=root,
        check=False,
    )
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", "profile.yaml"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert ignored.returncode == 0
    assert tracked.returncode != 0
