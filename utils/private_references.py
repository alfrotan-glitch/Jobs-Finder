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

import hashlib
import json
import os
import tempfile
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


# Private *editing* is deliberately separate from vacancy-specific release.
# A normal Windows installation needs no environment-variable setup to save
# owner-owned referee contacts. The store is ALWAYS outside the Git checkout.
def private_reference_editor_path() -> Path:
    configured = os.environ.get(PRIVATE_REFERENCES_ENV, "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
    else:
        root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "share")).expanduser()
        path = (root / "Jobs-Finder" / "private_references.yaml").resolve()
    checkout = PROJECT_ROOT.resolve()
    if path == checkout or checkout in path.parents:
        raise PrivateReferenceError("Private references must be stored outside the public Git checkout.")
    return path


_REFERENCE_FIELDS = ("name", "role", "organization", "phone", "email", "relationship")
_MAX_PRIVATE_ENTRIES = 30


def _clean_reference_entries(entries: object) -> list[dict[str, str]]:
    if not isinstance(entries, list) or len(entries) > _MAX_PRIVATE_ENTRIES:
        raise PrivateReferenceError("Supply a list of up to 30 professional referees.")
    cleaned: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - set(_REFERENCE_FIELDS):
            raise PrivateReferenceError("Reference entries contain unsupported fields.")
        row = {}
        for field in _REFERENCE_FIELDS:
            value = entry.get(field) or ""
            if not isinstance(value, str) or len(value) > 300 or any(ord(c) < 32 for c in value):
                raise PrivateReferenceError("Invalid reference contact field.")
            row[field] = value.strip()
        if not row["name"]:
            raise PrivateReferenceError("Every reference requires a name.")
        cleaned.append(row)
    return cleaned


def read_private_reference_editor() -> dict[str, object]:
    path = private_reference_editor_path()
    if not path.exists():
        entries: list[dict[str, str]] = []
    else:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            entries = _clean_reference_entries((data or {}).get("entries"))
        except (OSError, yaml.YAMLError, AttributeError) as exc:
            raise PrivateReferenceError("Could not read local private references.") from exc
    # A digest prevents stale forms from overwriting other local changes.
    version = hashlib.sha256(json.dumps(entries, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"entries": entries, "version": version, "stored_locally": True}


def save_private_reference_editor(entries: object, *, expected_version: str) -> dict[str, object]:
    current = read_private_reference_editor()
    if expected_version != current["version"]:
        raise PrivateReferenceError("Private references changed elsewhere. Reload before saving.")
    rows = _clean_reference_entries(entries)
    path = private_reference_editor_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".refs-", suffix=".tmp", delete=False
        ) as file:
            yaml.safe_dump({"entries": rows}, file, allow_unicode=True, sort_keys=False)
            file.flush()
            os.fsync(file.fileno())
            tmp = file.name
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError as exc:
        raise PrivateReferenceError("Cannot save private reference contacts.") from exc
    finally:
        if tmp:
            Path(tmp).unlink(missing_ok=True)
    return read_private_reference_editor()
