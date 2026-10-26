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

IDENTITY_FIELDS = ("first_name", "last_name", "email", "phone", "location", "professional_title")
CONFIRMATION = "I confirm this is true and based on my own records"
DOCUMENT_LAYOUTS = ("comfortable", "compact")
LETTER_DEPTHS = ("detailed", "standard")


class ProfileEditError(ValueError):
    pass


def _text(value: Any, *, maximum: int = 250, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or "\\x00" in value or len(value) > maximum:
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
            ],
        })
    locations = preferences.get("locations") or []
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
        "experience": experience,
        "documents": {
            "cv_layout": (profile.get("document_preferences") or {}).get("cv_layout", "comfortable"),
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
    if action == "documents":
        layout = patch.get("cv_layout")
        depth = patch.get("letter_depth")
        if layout not in DOCUMENT_LAYOUTS or depth not in LETTER_DEPTHS:
            raise ProfileEditError("Select a supported CV layout and letter depth.")
        profile["document_preferences"] = {"cv_layout": layout, "letter_depth": depth}
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
