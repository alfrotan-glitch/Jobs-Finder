"""Fail-closed evidence linking saved employer documents to the active generator.

A saved PDF is a static artifact. Upgrading the app or changing verified
work facts must NOT silently make the old saved PDF look current. Legacy
packages without this stamp are stale by design and must be regenerated.
No application is sent automatically.
"""
from __future__ import annotations

from typing import Any

from utils.profile import canonical_profile_fingerprint

GENERATOR_REVISION = "2026-10-27-role-curated-official-cv-v2"


def generation_stamp(profile: dict[str, Any], documents: dict[str, Any]) -> dict[str, Any]:
    cv = documents.get("tailored_cv_model") or {}
    return {
        "revision": GENERATOR_REVISION,
        "profile_sha256": canonical_profile_fingerprint(profile),
        "full_verified_duty_count": int(cv.get("full_verified_duty_count") or 0),
        "selected_duty_count": int(cv.get("selected_duty_count") or 0),
    }


def package_freshness(package: dict[str, Any] | None, profile: dict[str, Any]) -> dict[str, Any]:
    if not package or not package.get("package_status"):
        return {"current": False, "reason": "no_saved_application_package"}
    stamp = package.get("generation") or {}
    if not isinstance(stamp, dict) or stamp.get("revision") != GENERATOR_REVISION:
        return {"current": False, "reason": "old_cv_generator"}
    if not profile or stamp.get("profile_sha256") != canonical_profile_fingerprint(profile):
        return {"current": False, "reason": "profile_changed"}
    if int(stamp.get("selected_duty_count") or 0) < 1:
        return {"current": False, "reason": "no_verified_cv_evidence"}
    return {"current": True, "reason": "verified_current_generation"}
