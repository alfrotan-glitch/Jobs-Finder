"""Owner-controlled editing of the single canonical applicant profile.

Never trust a browser-provided YAML path or merge arbitrary dicts. Changes are
explicitly allowlisted, fingerprint-checked and verification-gated. The
canonical profile stays the only source for matcher, CV, and cover letter.
"""
from __future__ import annotations

from typing import Any

from utils.profile import (
    canonical_profile_fingerprint,
    is_unresolved_value,
    load_canonical_profile,
    save_canonical_profile,
)
from utils.source_registry import SOURCE_REGISTRY

IDENTITY_FIELDS = ("first_name", "last_name", "email", "phone", "location", "professional_title")
CONFIRMATION = "I confirm this is true and based on my own records"
DOCUMENT_LAYOUTS = ("comfortable", "compact")
CV_STYLES = ("clinical", "executive")
LETTER_DEPTHS = ("detailed", "standard")


class ProfileEditError(ValueError):
    pass


def _text(value: Any, *, maximum: int = 250, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or any(ord(char) == 0 for char in value) or len(value) > maximum:
        raise ProfileEditError("Invalid text value or field length.")
    cleaned = value.strip()
    if not cleaned and not allow_empty:
        raise ProfileEditError("This field cannot be left empty.")
    return cleaned


def editor_snapshot(profile: dict[str, Any]) -> dict[str, Any]:
    personal = profile.get("personal") or {}
    preferences = profile.get("preferences") or {}
    summary = profile.get("professional_summary") or {}
    if not isinstance(summary, dict):
        summary = {"text": "", "verified": False}
    experience = []
    for index, role in enumerate(profile.get("work_history") or []):
        if not isinstance(role, dict):
            continue
        experience.append({
            "index": index,
            "title": role.get("title") or "",
            "organization": role.get("organization") or "",
            "location": role.get("location") or "",
            "start": role.get("start") or "",
            "end": role.get("end") or "",
            "verified": role.get("verified") is True,
            "responsibilities": [
                {"index": i, "text": item.get("text") or "", "verified": item.get("verified") is True}
                for i, item in enumerate(role.get("responsibilities") or [])
                if isinstance(item, dict)
            ],
            "pending": [
                {"index": i, "text": item.get("text") or ""}
                for i, item in enumerate(role.get("needs_verification") or [])
                if isinstance(item, dict) and item.get("verified") is not True
                and not (
                    (profile.get("official_cv_approval") or {}).get("owner_approved") is True
                    and "system-authored scope draft" in str(item.get("basis") or "")
                )
            ],
        })
    locations = preferences.get("locations") or []
    raw_sources = profile.get("sources") or {}
    enabled = raw_sources.get("enabled") or [
        name for name, spec in SOURCE_REGISTRY.items() if spec.get("active")
    ]
    enabled = [name for name in enabled if name not in set(raw_sources.get("disabled") or [])]
    job_sources = profile.get("job_sources") or {}
    acbar = job_sources.get("acbar") or {}
    reliefweb = job_sources.get("reliefweb") or {}
    def safe_records(section: str, fields: tuple[str, ...]) -> list[dict[str, Any]]:
        return [
            {"index": index, "verified": item.get("verified") is True,
             **{key: item.get(key) or "" for key in fields}}
            for index, item in enumerate(profile.get(section) or [])
            if isinstance(item, dict)
        ]
    skill_records = []
    for group, items in (profile.get("skills") or {}).items():
        if isinstance(items, list):
            skill_records.extend(
                {"group": group, "index": index, "name": item.get("name") or "",
                 "verified": item.get("verified") is True}
                for index, item in enumerate(items) if isinstance(item, dict)
            )
    registration = profile.get("license_registration") or {}
    exam = profile.get("medical_exit_exam") or {}
    return {
        "version": canonical_profile_fingerprint(profile),
        "personal": {key: personal.get(key) or "" for key in IDENTITY_FIELDS},
        "personal_verified": {
            key: (personal.get("verification") or {}).get(key) is True
            for key in IDENTITY_FIELDS
        },
        "professional_summary": summary.get("text") or "",
        "professional_summary_verified": summary.get("verified") is True,
        "roles": [str(role) for role in preferences.get("roles") or [] if isinstance(role, str)],
        "locations": [str(item.get("name") or "") for item in locations if isinstance(item, dict)],
        "locations_verified": [item.get("verified") is True for item in locations if isinstance(item, dict)],
        "sources": {
            "enabled": enabled,
            "available": list(SOURCE_REGISTRY),
            "acbar_concurrency": acbar.get("max_detail_concurrency", 5),
            "acbar_timeout": acbar.get("timeout_seconds", 25),
            "reliefweb_limit": reliefweb.get("limit", 20),
            "reliefweb_timeout": reliefweb.get("timeout_seconds", 25),
        },
        "experience": experience,
        "education": safe_records("medical_education", ("degree", "field", "institution", "start", "end")),
        "certificates": safe_records("certificates", ("name",)),
        "languages": safe_records("languages", ("name", "level")),
        "skills": skill_records,
        "registration": {key: registration.get(key) or "" for key in
                         ("status", "authority", "number", "issue_date", "expiry_date")},
        "exam": {"status": exam.get("status") or ""},
        "documents": {
            "cv_layout": (profile.get("document_preferences") or {}).get("cv_layout", "comfortable"),
            "cv_style": (profile.get("document_preferences") or {}).get("cv_style", "clinical"),
            "letter_depth": (profile.get("document_preferences") or {}).get("letter_depth", "detailed"),
        },
    }


def apply_editor_change(profile: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Pure transform. The caller must validate version and save atomically."""
    if not isinstance(patch, dict):
        raise ProfileEditError("An editor change must be an object.")
    action = patch.get("action")
    if action == "bulk":
        changes = patch.get("changes")
        if not isinstance(changes, list) or not 1 <= len(changes) <= 20:
            raise ProfileEditError("Save between 1 and 20 validated fields per request.")
        for change in changes:
            if not isinstance(change, dict) or change.get("action") == "bulk":
                raise ProfileEditError("Nested bulk edits are not supported.")
            apply_editor_change(profile, change)
        return profile
    confirmed = patch.get("confirmation") == CONFIRMATION
    if action == "personal":
        key = patch.get("field")
        if key not in IDENTITY_FIELDS:
            raise ProfileEditError("This personal field is not editable.")
        value = _text(patch.get("value"), maximum=250)
        personal = profile.setdefault("personal", {})
        old = str(personal.get(key) or "").strip()
        if old != value:
            personal[key] = value
            # Never keep an old verification flag for a changed fact.
            personal.setdefault("verification", {})[key] = bool(confirmed and value and not is_unresolved_value(value))
        return profile
    if action == "summary":
        value = _text(patch.get("value"), maximum=2400)
        summary = profile.get("professional_summary") or {}
        if not isinstance(summary, dict):
            summary = {}
        old = str(summary.get("text") or "")
        summary["text"] = value
        if old != value:
            summary["verified"] = bool(confirmed and value and not is_unresolved_value(value))
        profile["professional_summary"] = summary
        return profile
    if action == "preferences":
        roles = patch.get("roles")
        if not isinstance(roles, list) or len(roles) > 25:
            raise ProfileEditError("Provide up to 25 preferred roles.")
        profile.setdefault("preferences", {})["roles"] = list(dict.fromkeys(
            _text(x, maximum=100, allow_empty=False) for x in roles
        ))
        return profile
    if action == "search":
        roles = patch.get("roles")
        locations = patch.get("locations")
        enabled = patch.get("enabled_sources")
        if not isinstance(roles, list) or len(roles) > 25:
            raise ProfileEditError("Provide up to 25 preferred roles.")
        if not isinstance(locations, list) or len(locations) > 20:
            raise ProfileEditError("Provide up to 20 preferred locations.")
        if not isinstance(enabled, list) or not enabled or any(
            not isinstance(item, str) or item not in SOURCE_REGISTRY for item in enabled
        ):
            raise ProfileEditError("Enable at least one supported job source.")
        def bounded_int(field: str, low: int, high: int) -> int:
            value = patch.get(field)
            if type(value) is not int or not low <= value <= high:
                raise ProfileEditError(f"{field} must be between {low} and {high}.")
            return value
        concurrency = bounded_int("acbar_concurrency", 1, 10)
        acbar_timeout = bounded_int("acbar_timeout", 5, 90)
        reliefweb_limit = bounded_int("reliefweb_limit", 1, 100)
        reliefweb_timeout = bounded_int("reliefweb_timeout", 5, 90)
        preferences = profile.setdefault("preferences", {})
        preferences["roles"] = list(dict.fromkeys(
            _text(value, maximum=100, allow_empty=False) for value in roles
        ))
        original = preferences.get("locations") or []
        old_names = {
            str(item.get("name") or "").casefold(): item
            for item in original if isinstance(item, dict)
        }
        updated_locations = []
        for value in locations:
            name = _text(value, maximum=100, allow_empty=False)
            if name.casefold() in [str(item["name"]).casefold() for item in updated_locations]:
                continue
            previous = old_names.get(name.casefold(), {})
            updated_locations.append({
                "name": name,
                "verified": previous.get("verified") is True or bool(confirmed),
            })
        preferences["locations"] = updated_locations
        profile["sources"] = {
            "enabled": list(dict.fromkeys(enabled)),
            "disabled": [name for name in SOURCE_REGISTRY if name not in enabled],
        }
        job_sources = profile.setdefault("job_sources", {})
        acbar = job_sources.setdefault("acbar", {})
        reliefweb = job_sources.setdefault("reliefweb", {})
        acbar["max_detail_concurrency"] = concurrency
        acbar["timeout_seconds"] = acbar_timeout
        reliefweb["limit"] = reliefweb_limit
        reliefweb["timeout_seconds"] = reliefweb_timeout
        return profile
    if action == "documents":
        layout = patch.get("cv_layout")
        depth = patch.get("letter_depth")
        style = patch.get("cv_style", "clinical")
        if layout not in DOCUMENT_LAYOUTS or depth not in LETTER_DEPTHS or style not in CV_STYLES:
            raise ProfileEditError("Select a supported CV layout and letter depth.")
        profile["document_preferences"] = {"cv_layout": layout, "letter_depth": depth, "cv_style": style}
        return profile
    if action == "work_role":
        values = {
            field: _text(patch.get(field) or "", maximum=250,
                         allow_empty=field not in {"title", "organization"})
            for field in ("title", "organization", "location", "start", "end")
        }
        roles = profile.setdefault("work_history", [])
        if not isinstance(roles, list) or len(roles) >= 100:
            raise ProfileEditError("The work-history list is full or invalid.")
        roles.append({**values, "verified": bool(confirmed), "responsibilities": []})
        return profile
    if action == "verify_record":
        section = patch.get("section")
        index = patch.get("index")
        group = patch.get("group")
        if not confirmed:
            raise ProfileEditError("Personally confirm this fact before making it CV evidence.")
        required = {
            "work_history": ("title", "organization"),
            "medical_education": ("degree", "institution"),
            "languages": ("name", "level"),
            "certificates": ("name",),
            "skills": ("name",),
        }
        if section not in required or type(index) is not int:
            raise ProfileEditError("Choose a valid record for verification.")
        if section == "skills":
            skills = profile.get("skills") or {}
            if not isinstance(group, str) or group not in skills:
                raise ProfileEditError("Select an existing skill group.")
            records = skills[group]
        else:
            records = profile.get(section) or []
        if not isinstance(records, list) or index < 0 or index >= len(records):
            raise ProfileEditError("Record does not exist.")
        record = records[index]
        if not isinstance(record, dict) or any(
            not isinstance(record.get(field), str)
            or not record[field].strip()
            or is_unresolved_value(record[field])
            for field in required[section]
        ):
            raise ProfileEditError("Fill in the required factual details before confirming.")
        record["verified"] = True
        return profile
    if action == "record":
        section = patch.get("section")
        key = patch.get("field")
        index = patch.get("index")
        create = patch.get("create") is True
        allowed = {
            "medical_education": {"degree", "field", "institution", "start", "end"},
            "work_history": {"title", "organization", "location", "start", "end"},
            "languages": {"name", "level"},
            "certificates": {"name"},
            "skills": {"name"},
            "license_registration": {"status", "authority", "number", "issue_date", "expiry_date"},
            "medical_exit_exam": {"status"},
        }
        if section not in allowed or key not in allowed[section]:
            raise ProfileEditError("This profile record or field is not editable.")
        if section == "work_history" and create:
            raise ProfileEditError("Use the complete new-role form instead.")
        value = _text(patch.get("value"), maximum=250, allow_empty=not create)
        if section in {"license_registration", "medical_exit_exam"}:
            if create or index is not None:
                raise ProfileEditError("This credential is a single profile record.")
            record = profile.setdefault(section, {})
        elif section == "skills":
            group = patch.get("group")
            skills = profile.get("skills") or {}
            if not isinstance(group, str) or group not in skills or not isinstance(skills[group], list):
                raise ProfileEditError("Select a supported skill category.")
            records = skills[group]
            if create:
                records.append({"name": value, "verified": confirmed})
                return profile
            if type(index) is not int or not 0 <= index < len(records):
                raise ProfileEditError("Invalid skill index.")
            record = records[index]
        else:
            records = profile.setdefault(section, [])
            if not isinstance(records, list):
                raise ProfileEditError("Unsupported record list.")
            if create:
                if len(records) >= 100:
                    raise ProfileEditError("This list has reached its safe maximum.")
                record = {key: value, "verified": confirmed}
                records.append(record)
                return profile
            if type(index) is not int or not 0 <= index < len(records):
                raise ProfileEditError("Invalid record index.")
            record = records[index]
        if not isinstance(record, dict):
            raise ProfileEditError("Unsupported profile record.")
        if str(record.get(key) or "") != value:
            record[key] = value
            record["verified"] = bool(confirmed and value and not is_unresolved_value(value))
        return profile
    if action == "responsibility":
        idx = patch.get("role_index")
        bullet_idx = patch.get("bullet_index")
        operation = patch.get("operation")
        if type(idx) is not int or idx < 0 or idx >= len(profile.get("work_history") or []):
            raise ProfileEditError("Select a valid work-history position.")
        role = profile["work_history"][idx]
        if not isinstance(role, dict) or role.get("verified") is not True:
            raise ProfileEditError("The professional role must be verified first.")
        if operation == "approve":
            pending = role.get("needs_verification") or []
            if type(bullet_idx) is not int or not 0 <= bullet_idx < len(pending):
                raise ProfileEditError("Select a valid pending responsibility.")
            if not confirmed:
                raise ProfileEditError("Personal confirmation is required to approve an unverified draft.")
            item = pending.pop(bullet_idx)
            value = _text(item.get("text"), maximum=1200, allow_empty=False)
            role["needs_verification"] = pending
            role.setdefault("responsibilities", []).append({"text": value, "verified": True})
            return profile
        bullets = role.setdefault("responsibilities", [])
        if not isinstance(bullets, list):
            raise ProfileEditError("Invalid responsibilities field.")
        if operation == "add":
            value = _text(patch.get("value"), maximum=1200, allow_empty=False)
            if len(value) < 20:
                raise ProfileEditError("A responsibility needs at least 20 characters.")
            if any(str(x.get("text") or "").casefold() == value.casefold() for x in bullets if isinstance(x, dict)):
                raise ProfileEditError("This responsibility is already listed.")
            bullets.append({"text": value, "verified": confirmed})
            return profile
        if type(bullet_idx) is not int or not 0 <= bullet_idx < len(bullets):
            raise ProfileEditError("Select a valid responsibility.")
        if operation == "verify":
            if not confirmed:
                raise ProfileEditError("Personal confirmation is required for this duty.")
            record = bullets[bullet_idx]
            if not isinstance(record, dict):
                raise ProfileEditError("Invalid work detail.")
            factual_text = _text(record.get("text"), maximum=1200, allow_empty=False)
            if len(factual_text) < 20:
                raise ProfileEditError("Provide a substantive responsibility before verifying it.")
            record["verified"] = True
            return profile
        if operation == "delete":
            bullets.pop(bullet_idx)
            return profile
        if operation == "update":
            value = _text(patch.get("value"), maximum=1200, allow_empty=False)
            if len(value) < 20:
                raise ProfileEditError("A responsibility needs at least 20 characters.")
            old = bullets[bullet_idx]
            if not isinstance(old, dict):
                raise ProfileEditError("Unsupported responsibility record.")
            if str(old.get("text") or "") != value:
                bullets[bullet_idx] = {"text": value, "verified": confirmed}
            return profile
    raise ProfileEditError("Unsupported profile edit.")


def update_profile(patch: dict[str, Any]) -> dict[str, Any]:
    profile = load_canonical_profile(required=True)
    current = canonical_profile_fingerprint(profile)
    if patch.get("version") != current:
        raise ProfileEditError("Profile was modified elsewhere. Reload to avoid losing changes.")
    apply_editor_change(profile, patch)
    save_canonical_profile(profile)
    return editor_snapshot(profile)
