"""Git-boundary regression for the one tracked canonical applicant profile."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_canonical_profile_is_tracked_and_not_ignored():
    """The real production profile must synchronize through ordinary Git."""
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

    assert profile.is_file()
    assert ignored.returncode != 0
    assert tracked.returncode == 0
    assert tracked.stdout.strip() == "profile.yaml"

    all_tracked_paths = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    tracked_profile_yamls = [
        path
        for path in all_tracked_paths
        if path.startswith(("profile.yaml", "profiles/"))
    ]
    # The example is documentation only. profile.yaml is the only tracked
    # production applicant record; no backup, alternate profile, or profile
    # directory may become a second real source of truth.
    assert sorted(tracked_profile_yamls) == ["profile.yaml", "profile.yaml.example"]
