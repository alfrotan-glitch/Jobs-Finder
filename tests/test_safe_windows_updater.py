"""Safe updater acceptance: no destructive Git operations or owner-data loss."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "Update_Jobs_Finder_Safely.bat"


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True, timeout=35)


def test_updater_never_stashes_resets_or_forces_profile_overwrites():
    script = UPDATER.read_text(encoding="utf-8").lower()
    assert "git fetch --quiet origin main" in script
    assert "git merge --ff-only fetch_head" in script
    assert "git status --porcelain --untracked-files=no" in script
    assert "copy /y \"profile.yaml\"" in script
    assert "if defined local_changes" in script
    assert not any(value in script for value in (
        "git reset", "git stash push", "git stash pop",
        "git clean", "git checkout --", "git merge --no-ff",
    ))


@pytest.mark.skipif(os.name != "nt", reason="Native Windows batch acceptance")
def test_windows_updater_fast_forwards_clean_checkout_and_holds_dirty_profile(tmp_path):
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    installed = tmp_path / "installed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.name", "Synthetic CI")
    _git(seed, "config", "user.email", "synthetic@example.test")
    (seed / "README.txt").write_text("v1", encoding="utf-8")
    (seed / "profile.yaml").write_text("synthetic: approved\n", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "synthetic initial")
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, timeout=35)
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    subprocess.run(["git", "clone", "-b", "main", str(remote), str(installed)], check=True, capture_output=True, timeout=35)
    shutil.copy2(UPDATER, installed / UPDATER.name)

    (seed / "README.txt").write_text("v2", encoding="utf-8")
    _git(seed, "add", "README.txt")
    _git(seed, "commit", "-m", "synthetic update 2")
    _git(seed, "push", "origin", "main")

    env = os.environ.copy()
    env["CI"] = "1"
    env["LOCALAPPDATA"] = str(tmp_path / "private-local")
    env["JOBS_FINDER_PORT"] = "59673"

    def update():
        return subprocess.run(["cmd.exe", "/d", "/c", str(installed / UPDATER.name)],
                              cwd=installed, env=env, capture_output=True, text=True, timeout=90)

    first = update()
    assert first.returncode == 0, first.stdout + first.stderr
    assert (installed / "README.txt").read_text(encoding="utf-8") == "v2"
    backups = list((tmp_path / "private-local" / "Jobs-Finder" / "UpdateBackups").glob("profile-before-update-*.yaml"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "synthetic: approved\n"

    (seed / "README.txt").write_text("v3", encoding="utf-8")
    _git(seed, "add", "README.txt")
    _git(seed, "commit", "-m", "synthetic update 3")
    _git(seed, "push", "origin", "main")
    (installed / "profile.yaml").write_text("synthetic: owner-local-change\n", encoding="utf-8")

    second = update()
    assert second.returncode != 0
    assert "HOLD" in second.stdout
    assert (installed / "profile.yaml").read_text(encoding="utf-8") == "synthetic: owner-local-change\n"
    assert (installed / "README.txt").read_text(encoding="utf-8") == "v2"
    copies = list((tmp_path / "private-local" / "Jobs-Finder" / "UpdateBackups").glob("profile-before-update-*.yaml"))
    assert any(p.read_text(encoding="utf-8") == "synthetic: owner-local-change\n" for p in copies)
