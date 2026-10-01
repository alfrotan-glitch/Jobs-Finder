"""FastAPI dashboard for the final small Jobs-Finder product.

The backend remains authoritative: every verification/eligibility judgement is
computed here (via utils.profile / utils.medical_matcher) and only displayed
by the frontend. The browser never re-implements matching or verification
logic.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import uvicorn
import yaml
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from utils.discovery import (
    ACBAR_DEFAULT_DETAIL_CONCURRENCY,
    ACBAR_DEFAULT_DETAIL_LIMIT,
    ACBAR_DEFAULT_MAX_PAGES,
    ACBAR_DEFAULT_TIMEOUT_SECONDS,
    RELIEFWEB_DEFAULT_LIMIT,
    RELIEFWEB_DEFAULT_TIMEOUT_SECONDS,
    run_discovery_scan,
)
from utils.documents import prepare_application_bundle
from utils.medical_matcher import NOT_ELIGIBLE_STATUS, match_job_against_profile
from utils.profile import PERSONAL_VERIFICATION_FIELDS, build_profile_evidence, is_unresolved_value, save_profile
from utils.source_registry import SOURCE_REGISTRY, source_registry_for_settings
from utils.profile_builder import build_profile_from_cv_file
from utils.resume_parser import extract_resume_text
from utils.tracker import (
    get_job_by_id,
    get_latest_scan,
    get_recommended_jobs,
    list_actionable_jobs,
    list_recent_scans,
    log_discovered,
    log_medical_match,
    log_scan_result,
    mark_applied_manually,
    stats,
    update_tailored_resume,
)

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "profile.yaml"
UPLOADS_DIR = ROOT / "resumes"

app = FastAPI(title="Jobs-Finder")
app.mount("/static", StaticFiles(directory=str(ROOT / "dashboard" / "static")), name="static")
templates = Jinja2Templates(directory=str(ROOT / "dashboard" / "templates"))


def load_profile(required: bool = False) -> dict[str, Any]:
    if not PROFILE_PATH.exists():
        if required:
            raise HTTPException(status_code=400, detail="profile.yaml is missing. Copy profile.yaml.example and enter verified facts.")
        return {}
    return yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8")) or {}


def profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    professional_title: Any = personal.get("professional_title") or profile.get("professional_title") or ""
    if isinstance(professional_title, dict):
        professional_title = professional_title.get("text") or professional_title.get("value") or professional_title.get("title") or ""
    return {
        "name": " ".join(str(personal.get(key, "")).strip() for key in ["first_name", "last_name"]).strip(),
        "title": professional_title if isinstance(professional_title, str) else "",
        "email": personal.get("email", ""),
        "phone": personal.get("phone", ""),
        "location": personal.get("location", ""),
        "resume_path": profile.get("resume_path", ""),
        "roles": (profile.get("preferences") or {}).get("roles", []) if isinstance(profile.get("preferences"), dict) else [],
        "locations": (profile.get("preferences") or {}).get("locations", []) if isinstance(profile.get("preferences"), dict) else [],
        "is_draft": str(profile.get("profile_status", "")).upper() == "DRAFT",
        "draft_note": profile.get("profile_status_note", ""),
    }


def _clean_value(value: Any) -> str:
    text = str(value or "").strip()
    return "" if is_unresolved_value(text) else text


def _date_range(item: dict[str, Any]) -> str:
    start = _clean_value(item.get("start") or item.get("start_date") or item.get("from"))
    end = _clean_value(item.get("end") or item.get("end_date") or item.get("to"))
    return f"{start} – {end}" if start and end else start or end


def _profile_details(profile: dict[str, Any]) -> dict[str, Any]:
    """Professional, read-only profile view for the UI.

    This intentionally returns display fields only. It does not expose raw YAML,
    internal verification flags, evidence IDs, or matching keys.
    """
    summary = profile_summary(profile)
    professional_summary = profile.get("professional_summary") or profile.get("summary") or ""
    if isinstance(professional_summary, dict):
        professional_summary = professional_summary.get("text") or professional_summary.get("value") or ""

    def named_items(value: Any) -> list[str]:
        out: list[str] = []
        if isinstance(value, dict):
            name = _clean_value(value.get("name") or value.get("title"))
            if name:
                out.append(name)
            for key, child in value.items():
                if key not in {"name", "title", "verified"}:
                    out.extend(named_items(child))
        elif isinstance(value, list):
            for child in value:
                out.extend(named_items(child))
        elif value not in (None, ""):
            text = _clean_value(value)
            if text:
                out.append(text)
        deduped: list[str] = []
        for item in out:
            if item not in deduped:
                deduped.append(item)
        return deduped

    experience = []
    for item in profile.get("work_history") or profile.get("experience") or []:
        if not isinstance(item, dict):
            continue
        bullets = item.get("bullets") or item.get("responsibilities") or []
        if isinstance(bullets, str):
            bullets = [bullets]
        experience.append(
            {
                "title": _clean_value(item.get("title") or item.get("role")),
                "organization": _clean_value(item.get("organization") or item.get("employer")),
                "location": _clean_value(item.get("location")),
                "dates": _date_range(item),
                "bullets": [_clean_value(bullet) for bullet in bullets if _clean_value(bullet)],
            }
        )

    education = []
    for item in (profile.get("medical_education") or []) + (profile.get("education") or []):
        if isinstance(item, dict):
            education.append(
                {
                    "degree": _clean_value(item.get("degree") or item.get("title") or item.get("name")),
                    "institution": _clean_value(item.get("institution") or item.get("school") or item.get("university")),
                    "location": _clean_value(item.get("country") or item.get("location")),
                    "dates": _date_range(item),
                }
            )

    registration = profile.get("license_registration") if isinstance(profile.get("license_registration"), dict) else {}
    exit_exam = profile.get("medical_exit_exam") if isinstance(profile.get("medical_exit_exam"), dict) else {}
    languages = []
    for item in profile.get("languages") or []:
        if isinstance(item, dict):
            name = _clean_value(item.get("name") or item.get("language"))
            level = _clean_value(item.get("level") or item.get("proficiency"))
            if name:
                languages.append({"name": name, "level": level})

    skills = []
    raw_skills = profile.get("skills") if isinstance(profile.get("skills"), dict) else {}
    for group, values in raw_skills.items():
        items = named_items(values)
        if items:
            skills.append({"group": str(group).replace("_", " ").title(), "items": items})

    return {
        "summary": summary,
        "professional_summary": _clean_value(professional_summary),
        "experience": experience,
        "education": education,
        "registration": {
            "authority": _clean_value(registration.get("authority") or registration.get("council")),
            "status": _clean_value(registration.get("status")),
        },
        "medical_exit_exam": {"status": _clean_value(exit_exam.get("status"))},
        "training": named_items(profile.get("certificates") or profile.get("certifications") or profile.get("training") or []),
        "skills": skills,
        "languages": languages,
    }


# ---------------------------------------------------------------------------
# Profile review -- a small, honest, nontechnical-friendly verification view.
#
# The backend decides every status label here; the frontend only renders the
# "key"/"label"/"status"/"evidence" fields returned below. This keeps the
# single canonical verification contract (utils.profile) as the sole source
# of truth, with no duplicate logic in JavaScript.
# ---------------------------------------------------------------------------

# (evidence key, label, confirm_field) -- confirm_field is the value the
# browser must send to POST /api/profile/confirm to mark this fact verified,
# or None when no one-click confirm is available for it yet (those facts
# still require editing profile.yaml directly).
REVIEW_FIELDS: list[tuple[str, str, str | None]] = [
    ("professional_title", "Professional identity/title", "professional_title"),
    ("first_name", "First name", "personal:first_name"),
    ("last_name", "Last name", "personal:last_name"),
    ("email", "Email address", "personal:email"),
    ("phone", "Phone number", "personal:phone"),
    ("gender", "Gender", "personal:gender"),
    ("nationality", "Nationality", "personal:nationality"),
    ("location", "Current location", "personal:location"),
    ("md_degree", "Medical degree (MD)", "medical_education"),
    ("license_registration", "Medical license / registration", "license_registration"),
    ("medical_exit_exam", "Medical Exit Exam", "medical_exit_exam"),
    ("language_english", "English language", "language:English"),
    ("language_dari", "Dari language", "language:Dari"),
    ("language_pashto", "Pashto language", "language:Pashto"),
    ("willing_to_relocate", "Willing to relocate", None),
    ("field_deployment", "Field deployment availability", None),
]

# Allow-listed fields a user can explicitly confirm from the browser. Each
# entry mutates only the matching `verified` flag inside profile.yaml -- it
# never invents a value, a number, a date, or a document. Personal fields are
# confirmed one at a time under personal.verification.<field>, so confirming
# an email cannot silently verify gender, nationality, or location.
CONFIRMABLE_FIELDS = {"medical_education", "license_registration", "medical_exit_exam", "professional_title"}


def _is_confirmable(field: str) -> bool:
    if field.startswith("personal:"):
        return field.split(":", 1)[1] in PERSONAL_VERIFICATION_FIELDS
    return field in CONFIRMABLE_FIELDS or field.startswith("language:")


def _field_status(evidence, key: str) -> str:
    if evidence.has_verified(key):
        return "Verified"
    if evidence.has(key):
        return "Needs verification"
    return "Missing"


def _profile_review_payload(profile: dict[str, Any]) -> dict[str, Any]:
    resume_text = extract_resume_text(profile.get("resume_path", ""))
    evidence = build_profile_evidence(profile, resume_text=resume_text)
    fields = []
    for key, label, confirm_field in REVIEW_FIELDS:
        status = _field_status(evidence, key)
        fields.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "evidence": evidence.evidence_text(key)[:2],
                "confirm_field": confirm_field if status != "Missing" else None,
            }
        )
    return {
        "is_draft": str(profile.get("profile_status", "")).upper() == "DRAFT",
        "draft_note": profile.get("profile_status_note", ""),
        "fields": fields,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/api/health")
def health():
    return {"ok": True, "product": "Jobs-Finder"}


@app.get("/api/profile")
def api_profile():
    profile = load_profile(False)
    return {"exists": bool(profile), "summary": profile_summary(profile)}


@app.get("/api/profile/details")
def api_profile_details():
    profile = load_profile(False)
    if not profile:
        return {"exists": False, "details": {}}
    return {"exists": True, "details": _profile_details(profile)}


@app.get("/api/generated-file")
def api_generated_file(path: str):
    """Open a generated package artifact for user review.

    Only files under the local ignored documents/ directory are served. This is
    a review/open action, not submission or sending.
    """
    raw_path = Path(path)
    candidate = raw_path if raw_path.is_absolute() else ROOT / raw_path
    resolved = candidate.resolve()
    documents_root = (ROOT / "documents").resolve()
    if documents_root not in [resolved, *resolved.parents]:
        raise HTTPException(status_code=400, detail="Only generated application documents can be opened.")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Generated file not found.")
    if resolved.suffix.lower() not in {".txt", ".pdf", ".docx"}:
        raise HTTPException(status_code=400, detail="Unsupported generated file type.")
    return FileResponse(str(resolved), filename=resolved.name)


@app.get("/api/profile/review")
def api_profile_review():
    profile = load_profile(False)
    if not profile:
        return {"exists": False, "is_draft": False, "draft_note": "", "fields": []}
    return {"exists": True, **_profile_review_payload(profile)}


@app.post("/api/profile/confirm")
async def api_profile_confirm(request: Request):
    """Flip an explicit `verified: true` flag the user has confirmed by hand.

    This never invents a license number, date, certificate, or any other
    fact -- it only lets the user confirm that a fact already present in
    their profile is true, which is the one and only way (besides editing
    profile.yaml directly) that a fact becomes verified evidence.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    field = str((payload or {}).get("field") or "")
    if not _is_confirmable(field):
        raise HTTPException(status_code=400, detail=f"Unsupported field: {field}")
    profile = load_profile(True)

    if field.startswith("language:"):
        # A language is only meaningfully verified once both an explicit
        # proficiency level AND `verified: true` are present -- a bare
        # `verified: true` next to a placeholder level like "Needs
        # verification" is treated as a contradiction and stays unverified
        # (see utils.profile._add_languages). The caller must therefore also
        # supply the level the user is confirming.
        name = field.split(":", 1)[1].strip()
        level = str((payload or {}).get("level") or "").strip()
        if not level or is_unresolved_value(level):
            raise HTTPException(status_code=400, detail="A proficiency level (e.g. Fluent, Native, Professional, Basic) is required to confirm a language.")
        languages = profile.get("languages")
        matched = False
        if isinstance(languages, list):
            for item in languages:
                if isinstance(item, dict) and str(item.get("name", "")).strip().lower() == name.lower():
                    item["level"] = level
                    item["verified"] = True
                    matched = True
        if not matched:
            raise HTTPException(status_code=400, detail=f"No '{name}' entry found in profile.yaml languages.")
    elif field.startswith("personal:"):
        key = field.split(":", 1)[1].strip()
        personal = profile.setdefault("personal", {})
        if not isinstance(personal, dict):
            raise HTTPException(status_code=400, detail="personal is not a mapping in profile.yaml.")
        value = personal.get(key)
        if value in (None, "") or is_unresolved_value(value):
            raise HTTPException(status_code=400, detail=f"personal.{key} has no resolved value to verify.")
        verification = personal.setdefault("verification", {})
        if not isinstance(verification, dict):
            raise HTTPException(status_code=400, detail="personal.verification is not a mapping in profile.yaml.")
        verification[key] = True
    elif field == "professional_title":
        personal = profile.get("personal") if isinstance(profile.get("personal"), dict) else {}
        if personal.get("professional_title") and not is_unresolved_value(personal.get("professional_title")):
            verification = personal.setdefault("verification", {})
            if not isinstance(verification, dict):
                raise HTTPException(status_code=400, detail="personal.verification is not a mapping in profile.yaml.")
            verification["professional_title"] = True
        else:
            title = profile.get("professional_title")
            if isinstance(title, dict):
                value = title.get("text") or title.get("value") or title.get("title")
                if not value or is_unresolved_value(value):
                    raise HTTPException(status_code=400, detail="professional_title has no resolved value to verify.")
                title["verified"] = True
            elif title and not is_unresolved_value(title):
                profile["professional_title"] = {"value": str(title), "verified": True}
            else:
                raise HTTPException(status_code=400, detail="professional_title has no resolved value to verify.")
    elif field == "medical_education":
        target = profile.get(field)
        if not isinstance(target, list) or not target:
            raise HTTPException(status_code=400, detail="No medical_education entry to confirm.")
        for item in target:
            if isinstance(item, dict):
                item["verified"] = True
    else:
        target = profile.get(field)
        if not isinstance(target, dict):
            raise HTTPException(status_code=400, detail=f"{field} is not present in profile.yaml.")
        target["verified"] = True

    save_profile(profile, PROFILE_PATH)
    return {"ok": True, "message": f"{field} marked verified in profile.yaml.", "review": _profile_review_payload(profile)}


@app.post("/api/import-cv")
async def api_import_cv(file: UploadFile = File(...)):
    """Build a DRAFT profile from an uploaded CV for the user to review.

    The result always needs review: nothing extracted from the CV is written
    as verified. If profile.yaml already exists it is preserved as
    profile.yaml.bak before being replaced, so a browser-based import never
    silently destroys previously confirmed facts.
    """
    allowed_suffixes = {".pdf", ".txt", ".md", ".markdown", ".rst", ".csv"}
    suffix = Path(file.filename or "cv.txt").suffix.lower() or ".txt"
    if suffix not in allowed_suffixes:
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload a PDF or plain-text CV.")
    content = await file.read()
    UPLOADS_DIR.mkdir(exist_ok=True)
    stored_path = UPLOADS_DIR / f"cv_{uuid.uuid4().hex}{suffix}"
    stored_path.write_bytes(content)

    profile = build_profile_from_cv_file(str(stored_path))

    if PROFILE_PATH.exists():
        backup_path = PROFILE_PATH.parent / f"{PROFILE_PATH.name}.bak"
        backup_path.write_text(PROFILE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    save_profile(profile, PROFILE_PATH)
    return {
        "ok": True,
        "message": "Draft profile created from your CV. Review every field below before scanning or applying.",
        **_profile_review_payload(profile),
    }


@app.get("/api/settings")
def api_settings():
    """Truthful, read-only view of current system configuration.

    Nothing here is an editable toggle: these values reflect the actual
    current discovery budget and active sources. If a value is not actually
    configurable from the UI, it is presented as current configuration, not
    as a control.
    """
    profile = load_profile(False)
    acbar_cfg = ((profile.get("job_sources") or {}).get("acbar") or {}) if isinstance(profile, dict) else {}
    reliefweb_cfg = ((profile.get("job_sources") or {}).get("reliefweb") or {}) if isinstance(profile, dict) else {}
    return {
        "sources": source_registry_for_settings(),
        "acbar": {
            "max_pages": acbar_cfg.get("max_pages", ACBAR_DEFAULT_MAX_PAGES),
            "detail_limit": acbar_cfg.get("detail_limit", ACBAR_DEFAULT_DETAIL_LIMIT),
            "max_detail_concurrency": acbar_cfg.get("max_detail_concurrency", ACBAR_DEFAULT_DETAIL_CONCURRENCY),
            "timeout_seconds": acbar_cfg.get("timeout_seconds", ACBAR_DEFAULT_TIMEOUT_SECONDS),
            "note": (SOURCE_REGISTRY.get("acbar", {}).get("settings_note") or "Bounded scan budget -- not a claim that the entire source archive is scanned on every run."),
        },
        "reliefweb": {
            "limit": reliefweb_cfg.get("limit", RELIEFWEB_DEFAULT_LIMIT),
            "timeout_seconds": reliefweb_cfg.get("timeout_seconds", RELIEFWEB_DEFAULT_TIMEOUT_SECONDS),
        },
        "background_scanning": False,
        "automatic_submission": False,
    }


@app.get("/api/recommended")
def api_recommended(limit: int = 20):
    return {"jobs": get_recommended_jobs(limit=limit)}


@app.get("/api/jobs")
def api_jobs(limit: int = 200):
    return {"jobs": list_actionable_jobs(limit=limit)}


@app.get("/api/stats")
def api_stats():
    return stats()


@app.get("/api/scan/latest")
def api_scan_latest():
    return {"scan": get_latest_scan()}


@app.get("/api/scans")
def api_scans(limit: int = 10):
    return {"scans": list_recent_scans(limit=limit)}


@app.post("/api/find")
async def api_find():
    profile = load_profile(True)
    scan = await run_discovery_scan(profile)
    resume_text = extract_resume_text(profile.get("resume_path", ""))
    match_results = []
    for job in scan.jobs:
        log_discovered(job)
        report = match_job_against_profile(job.to_dict(), profile, resume_text=resume_text).to_dict()
        match_results.append(report)
        log_medical_match(job.id, report)
    scan.record_match_results(match_results)
    result = scan.to_dict()
    log_scan_result(result)
    return result


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    job = get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    return job


@app.post("/api/jobs/{job_id}/prepare")
def api_prepare(job_id: str):
    profile = load_profile(True)
    job = get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    resume_text = extract_resume_text(profile.get("resume_path", ""))
    report = match_job_against_profile(job, profile, resume_text=resume_text).to_dict()
    log_medical_match(job_id, report)
    if report.get("readiness_status") == NOT_ELIGIBLE_STATUS:
        raise HTTPException(status_code=409, detail="This vacancy is NOT_ELIGIBLE; no application package was generated.")
    docs = prepare_application_bundle(job, profile, report, resume_text=resume_text)
    update_tailored_resume(job_id, docs)
    return {"job_id": job_id, "documents": docs.get("generated_paths", {}), "package": docs.get("application_package", {})}


@app.post("/api/jobs/{job_id}/mark-applied")
async def api_mark_applied(job_id: str, request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    confirmation = payload.get("confirmation", "") if isinstance(payload, dict) else ""
    ok, message = mark_applied_manually(job_id, confirmation=confirmation)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    return {"ok": True, "message": message}


def run_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    uvicorn.run("dashboard.server:app", host=host, port=port, reload=False)
