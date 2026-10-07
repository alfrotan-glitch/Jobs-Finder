"""Opt-in private-reference boundary.

Reference contact details are intentionally *not* applicant-profile facts.  The
tracked ``profile.yaml`` carries only the policy boundary; private reference
metadata, if the owner elects to keep it locally, must be in an explicitly
selected file outside the repository.  This module is never used by matching,
recommendations, documents, dashboard profile output, SQLite persistence, or
normal package serialization.

There is no automatic release path.  A caller has to prove both that a vacancy
explicitly requires references and that the owner explicitly approved a release
for that vacancy before this module will read any contact metadata.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from utils.paths import PROJECT_ROOT

PRIVATE_REFERENCES_ENV = "JOBS_FINDER_PRIVATE_REFERENCES_PATH"


class PrivateReferenceError(ValueError):
    """Raised when a private-reference release request is unsafe or malformed."""


def private_reference_store_path() -> Path | None:
    """Return an explicitly configured external private-reference path only.

    No default path, repository-relative path, fallback file, or browser/cache
    store is accepted. This avoids silently creating or reading a second public
    applicant record.
    """
    configured = os.environ.get(PRIVATE_REFERENCES_ENV, "").strip()
    if not configured:
        return None
    path = Path(configured).expanduser().resolve()
    if path == PROJECT_ROOT or PROJECT_ROOT in path.parents:
        raise PrivateReferenceError(
            f"{PRIVATE_REFERENCES_ENV} must point outside the Jobs-Finder repository; private references cannot be stored in tracked or generated project files."
        )
    return path


def load_approved_private_references(*, vacancy_requires_references: bool, owner_approved: bool) -> list[dict[str, str]]:
    """Load references only for an explicit, approved vacancy-specific release.

    The returned data is deliberately not persisted or logged by this module.
    Normal product flows do not call this function; they show a generic manual
    checklist instead.  The narrow API exists so a future owner-controlled
    export can enforce the same two approvals rather than discovering an
    unprotected local default file.
    """
    if not vacancy_requires_references:
        raise PrivateReferenceError("Private references may be released only when the vacancy explicitly requires them.")
    if not owner_approved:
        raise PrivateReferenceError("Private references require explicit owner approval for this vacancy.")
    path = private_reference_store_path()
    if path is None:
        raise PrivateReferenceError(f"No private-reference store is configured ({PRIVATE_REFERENCES_ENV}).")
    if not path.is_file():
        raise PrivateReferenceError("Configured private-reference store does not exist or is not a regular file.")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PrivateReferenceError("Private-reference store could not be read.") from exc
    entries = loaded.get("entries") if isinstance(loaded, dict) else None
    if not isinstance(entries, list):
        raise PrivateReferenceError("Private-reference store must contain an entries list.")
    safe_entries: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # Preserve only deliberate, printable contact fields. Unknown/private
        # notes are not transported accidentally into an export.
        cleaned = {key: str(entry.get(key) or "").strip() for key in ("name", "role", "phone", "email")}
        if cleaned["name"]:
            safe_entries.append(cleaned)
    return safe_entries
