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


def _languages(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for name in ["Dari", "Pashto", "English"]:
        if re.search(rf"\b{name}\b", text, flags=re.I):
            out.append({"name": name, "level": "Needs verification"})
    return out or [{"name": "Dari", "level": "Needs verification"}, {"name": "Pashto", "level": "Needs verification"}, {"name": "English", "level": "Needs verification"}]


def build_profile_from_cv_text(text: str, *, resume_path: str = "") -> dict[str, Any]:
    first, last = _name_from_text(text)
    md_found = bool(re.search(r"\b(MD|M\.D\.|Medical Doctor|Doctor of Medicine)\b", text, flags=re.I))
    license_found = bool(re.search(r"\b(medical\s+(?:license|licence|registration)|Afghan Medical Council|medical council)\b", text, flags=re.I))
    exit_exam_found = bool(re.search(r"\bexit\s+exam", text, flags=re.I))

    return {
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
        "medical_education": [{"degree": "MD", "institution": "Needs verification", "graduation_year": "Needs verification", "verified": md_found}],
        "license_registration": {
            "authority": "Needs verification",
            "number": "",
            "issue_date": "",
            "expiry_date": "",
            "status": "Mentioned in CV; verify details" if license_found else "Needs verification",
            "verified": license_found,
        },
        "medical_exit_exam": {"status": "Mentioned in CV; verify details" if exit_exam_found else "Needs verification", "verified": exit_exam_found},
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
            "acbar": {"timeout_seconds": 25, "detail_limit": 30, "urls": ["https://www.acbar.org/en/jobs", "https://www.acbar.org/en/jobs?page=2", "https://www.acbar.org/en/jobs?page=3"]},
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
