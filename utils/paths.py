"""Canonical filesystem locations for the Jobs-Finder project.

The application is a local project, not an installed service.  Keeping these
locations in one module prevents the CLI, dashboard, and tracker from deriving
paths from their own current working directory or from different assumptions
about where the repository was launched.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_DB_PATH = (PROJECT_ROOT / "applications.db").resolve()
CANONICAL_PROFILE_PATH = (PROJECT_ROOT / "profile.yaml").resolve()


def project_path(path: str | Path) -> Path:
    """Resolve a project-relative path without consulting the process CWD."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()
