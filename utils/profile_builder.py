"""Conservative profile builder from a user-supplied CV.

This creates a draft for human review. It intentionally avoids inferring exact
license numbers, dates, years of experience, certificates, or employers unless
plain text is copied into review notes. The user must verify profile.yaml before
using it for matching or documents.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from utils.resume_parser import extract_resume_text


def _email(text: str) -> str:
    match = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text, flags=re.I)
    return match.group(0) if match else ""


def _phone(text: str) -> str:
    match = re.search(r"(?:\+?93|0)?[\s\-]?(?:7\d{2}|\d{3})[\s\-]?\d{3}[\s\-]?\d{3}", text)
    return match.group(0).strip() if match else ""


def _name_from_text(text: str) -> tuple[str, str]:
    for line in text.splitlines()[:12]:
        cleaned = re.sub(r"[^A-Za-z\s.'-]", " ", line).strip()
        words = [w for w in cleaned.split() if len(w) > 1]
        if 2 <= len(words) <= 5 and not any(w.lower() in {"email", "phone", "curriculum", "vitae", "resume"} for w in words):
            return words[0], " ".join(words[1:])
    return "", ""


def _languages(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name in ["Dari", "Pashto", "English"]:
        if re.search(rf"\b{name}\b", text, flags=re.I):
            out.append({"name": name, "level": "Needs verification", "verified": False})
    return out or [
        {"name": "Dari", "level": "Needs verification", "verified": False},
        {"name": "Pashto", "level": "Needs verification", "verified": False},
        {"name": "English", "level": "Needs verification", "verified": False},
    ]


def build_profile_from_cv_text(text: str, *, resume_path: str = "") -> dict[str, Any]:
    """Build a conservative DRAFT profile from CV text for human review.

    CRITICAL INVARIANT: nothing extracted from CV text may ever be written
    with ``verified: true``. Regex matches below (MD mention, license mention,
    exit-exam mention) only ever influence the human-readable status note
    ("Mentioned in CV; verify details") -- they NEVER set the explicit
    ``verified`` flag. Only a human editing profile.yaml after reviewing the
    draft can change ``verified`` to ``true``. This matches the canonical
    verification contract in utils/profile.py: a fact is verified only when
    its source explicitly establishes verification, and a CV is never such a
    source by itself.
    """
    first, last = _name_from_text(text)
    md_mentioned = bool(re.search(r"\b(MD|M\.D\.|Medical Doctor|Doctor of Medicine)\b", text, flags=re.I))
    license_mentioned = bool(re.search(r"\b(medical\s+(?:license|licence|registration)|Afghan Medical Council|medical council)\b", text, flags=re.I))
    exit_exam_mentioned = bool(re.search(r"\bexit\s+exam", text, flags=re.I))

    return {
        "profile_status": "DRAFT",
        "profile_status_note": (
            "This profile was generated from a CV import and has not been reviewed. "
            "Every field is a draft; nothing here is verified until you confirm it and "
            "set the matching 'verified: true' field in profile.yaml."
        ),
        "personal": {
            "first_name": first,
            "last_name": last,
            "email": _email(text),
            "phone": _phone(text),
            "location": "Needs verification",
            "nationality": "Needs verification",
            "gender": "",
            "linkedin": "",
        },
        "resume_path": resume_path,
        "medical_education": [
            {
                "degree": "MD",
                "institution": "Needs verification",
                "graduation_year": "Needs verification",
                "status": "Mentioned in CV; verify details" if md_mentioned else "Needs verification",
                "verified": False,
            }
        ],
        "license_registration": {
            "authority": "Needs verification",
            "number": "",
            "issue_date": "",
            "expiry_date": "",
            "status": "Mentioned in CV; verify details" if license_mentioned else "Needs verification",
            "verified": False,
        },
        "medical_exit_exam": {
            "status": "Mentioned in CV; verify details" if exit_exam_mentioned else "Needs verification",
            "verified": False,
        },
        "clinical_experience": {"years": "", "settings": []},
        "work_history": [],
        "skills": {"medical": ["Clinical care"], "public_health": [], "management": []},
        "languages": _languages(text),
        "certificates": [],
        "ngo_humanitarian_experience": {"years": "", "organizations": []},
        "preferences": {
            "roles": ["Medical Officer", "Medical Doctor", "Physician", "Public Health Officer", "Nutrition / TSFP health roles"],
            "locations": ["Afghanistan"],
            "willing_to_relocate": "Needs verification",
            "field_deployment": "Needs verification",
        },
        "sources": {"enabled": [], "disabled": []},
        "job_sources": {
            "acbar": {"timeout_seconds": 25, "detail_limit": 30, "max_pages": 6, "max_detail_concurrency": 5},
            "reliefweb": {"timeout_seconds": 25, "limit": 20},
        },
        "source_cv_note": "Drafted from a supplied CV. Review every field before matching or applying; missing facts remain Needs verification.",
    }


def build_profile_from_cv_file(cv_path: str, *, resume_path: str | None = None) -> dict[str, Any]:
    text = extract_resume_text(cv_path)
    if not text:
        path = Path(cv_path)
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
    return build_profile_from_cv_text(text, resume_path=resume_path or cv_path)
