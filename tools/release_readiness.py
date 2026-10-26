"""Read-only Windows handover preflight for Jobs-Finder.

No Internet access, scan, applications, email, database migration, or
modification of the canonical profile. The document smoke test uses only
fictional data and cleans its temporary files.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _check_database(path: Path) -> dict[str, str]:
    if not path.exists():
        return {"status": "WARN", "detail": "No local applications.db yet; first-use scan/database history cannot be verified."}
    if path.is_symlink() or not path.is_file():
        return {"status": "BLOCK", "detail": "Local database is not a regular file."}
    try:
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5) as connection:
            check = connection.execute("PRAGMA quick_check").fetchone()
        if check and check[0] == "ok":
            return {"status": "PASS", "detail": "Existing local SQLite database passes read-only quick_check."}
        return {"status": "BLOCK", "detail": "Local database failed integrity check; do not use until restored."}
    except (sqlite3.Error, OSError):
        return {"status": "BLOCK", "detail": "Could not read the local SQLite database safely."}


def _check_git(root: Path) -> dict[str, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, check=True, timeout=8,
        )
        return {
            "status": "WARN" if result.stdout.strip() else "PASS",
            "detail": "Local edits exist; back up profile and reconcile before git pull."
            if result.stdout.strip() else "Tracked checkout has no local changes.",
        }
    except (OSError, subprocess.SubprocessError):
        return {"status": "WARN", "detail": "Git checkout cleanliness could not be verified."}


def _smoke_documents() -> dict[str, str]:
    """Exercise actual PDF and editable DOCX renderers on synthetic facts."""
    import pdfplumber
    from docx import Document

    from utils.document_design import render_professional_document_artifacts

    model = {
        "name": "Example Candidate",
        "headline": "Medical Professional",
        "application_focus": "TFU Medical Doctor",
        "contact_lines": ["Example Province", "candidate@example.org"],
        "profile": "Verified example profile for a simulated document smoke test.",
        "expertise": [{"group": "Medical care", "items": ["Patient care", "Clinical reporting"]}],
        "experience": [{
            "role": "Example Doctor", "org": "Example Clinic", "loc": "Example Province",
            "dates": "2021–2023", "bullets": [
                "Conducted clinical patient assessments and maintained documentation."
            ],
        }],
        "education": ["MD — Example Medical College"],
        "registration": [], "exit_exam": [], "certifications": [],
        "languages": [("English", "Fluent")], "references": ["Available on request"],
        "cv_layout": "comfortable", "cv_style": "executive",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="jobs-finder-preflight-") as folder:
            result = render_professional_document_artifacts(
                "Example CV", Path(folder) / "example_cv", document_type="cv",
                canonical_cv_model=model,
            )
            word = Document(result["docx"])
            paragraphs = "\n".join(p.text for p in word.paragraphs)
            with pdfplumber.open(result["pdf"]) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            needle = "Conducted clinical patient assessments"
            if needle not in paragraphs or needle not in text:
                return {"status": "BLOCK", "detail": "Word/PDF rendering lost synthetic work evidence."}
        return {"status": "PASS", "detail": "Synthetic editable Word and searchable PDF produced with complete evidence."}
    except Exception as exc:
        return {"status": "BLOCK", "detail": f"Word/PDF smoke test failed: {type(exc).__name__}."}


def collect_readiness() -> dict[str, object]:
    from utils.paths import CANONICAL_DB_PATH
    from utils.profile import load_canonical_profile

    checks: dict[str, dict[str, str]] = {}
    supported = (3, 11) <= sys.version_info[:2] <= (3, 12)
    checks["python"] = {
        "status": "PASS" if supported else "BLOCK",
        "detail": f"Python {sys.version_info.major}.{sys.version_info.minor}; supported 3.11 or 3.12.",
    }
    try:
        profile = load_canonical_profile(required=True)
        roles = [r for r in profile.get("work_history") or [] if isinstance(r, dict) and r.get("verified") is True]
        duties = sum(
            sum(1 for duty in r.get("responsibilities") or []
                if isinstance(duty, dict) and duty.get("verified") is True and duty.get("text"))
            for r in roles
        )
        required_contact = profile.get("personal") or {}
        verified = required_contact.get("verification") or {}
        contacts_ok = all(bool(required_contact.get(k)) and verified.get(k) is True
                          for k in ("first_name", "last_name", "email", "phone"))
        checks["profile"] = {
            "status": "PASS" if roles and duties and contacts_ok else "BLOCK",
            "detail": f"Verified professional profile: {len(roles)} roles and {duties} actual duty statements; "
                      + ("identity/contact verified." if contacts_ok else "identity/contact confirmation required."),
        }
    except Exception as exc:
        checks["profile"] = {
            "status": "BLOCK", "detail": f"Canonical profile unavailable: {type(exc).__name__}."
        }
    checks["database"] = _check_database(Path(CANONICAL_DB_PATH))
    checks["git"] = _check_git(ROOT)
    checks["documents"] = _smoke_documents()
    checks["private_references"] = {
        "status": "WARN",
        "detail": "Private referee contacts are NOT in the main ZIP; download their separate JSON backup in My Profile.",
    }
    checks["github_visibility"] = {
        "status": "WARN",
        "detail": "Offline preflight cannot confirm GitHub Private status. Verify this manually before sharing PII.",
    }
    checks["windows_browser_uat"] = {
        "status": "WARN",
        "detail": "CI does not prove actual local browser/email-client operation; test real UI and unsent .eml.",
    }
    blockers = [key for key, value in checks.items() if value["status"] == "BLOCK"]
    return {
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "kind": "read-only-local-handover-preflight",
        "decision": "HOLD" if blockers else "READY_FOR_WINDOWS_UAT_NOT_PRODUCTION",
        "blocking_checks": blockers,
        "checks": checks,
        "scope": "Offline only; no vacancies fetched, emails sent or personal documents exported.",
    }


def main() -> int:
    report = collect_readiness()
    print("JOBS-FINDER — LOCAL RELEASE READINESS")
    print("Decision:", report["decision"])
    for name, item in report["checks"].items():
        print(f"[{item['status']}] {name}: {item['detail']}")
    # Avoid writing profile/contact details to disk. A local report contains
    # only status metadata and a UTC timestamp.
    out = ROOT / "generated" / "release_readiness.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Local report:", out)
    return 1 if report["decision"] == "HOLD" else 0


if __name__ == "__main__":
    raise SystemExit(main())
