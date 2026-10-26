"""FastAPI dashboard for the final small Jobs-Finder product.

The backend remains authoritative: every verification/eligibility judgement is
computed here (via utils.profile / utils.medical_matcher) and only displayed
by the frontend. The browser never re-implements matching or verification
logic.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from utils.alerts import (
    list_alerts,
    mark_alert_read,
    mark_all_alerts_read,
    record_deadline_alerts,
    record_scan_alerts,
)
from utils.backups import (
    MAX_ARCHIVE_BYTES,
    BackupError,
    backup_archive,
    verify_backup_archive,
)
from utils.discovery import (
    ACBAR_DEFAULT_DETAIL_CONCURRENCY,
    ACBAR_DEFAULT_TIMEOUT_SECONDS,
    RELIEFWEB_DEFAULT_LIMIT,
    RELIEFWEB_DEFAULT_TIMEOUT_SECONDS,
    is_expired,
    run_discovery_scan,
)
from utils.documents import prepare_application_bundle, write_master_cv
from utils.email_drafts import (
    EmailDraftError,
    build_email_draft,
    open_windows_email_draft,
)
from utils.medical_matcher import NOT_ELIGIBLE_STATUS, match_job_against_profile
from utils.paths import CANONICAL_DB_PATH, PROJECT_ROOT
from utils.profile import (
    PERSONAL_VERIFICATION_FIELDS,
    CanonicalProfileError,
    build_profile_evidence,
    is_unresolved_value,
    load_canonical_profile,
    save_canonical_profile,
)
from utils.profile_builder import build_profile_from_cv_file
from utils.recommendations import evaluate_scan_jobs
from utils.scan_guard import ScanAlreadyRunning, exclusive_scan
from utils.source_registry import SOURCE_REGISTRY, source_registry_for_settings
from utils.tracker import (
    get_actionable_jobs_by_ids,
    get_job_by_id,
    get_latest_scan,
    get_recommended_jobs,
    list_actionable_jobs_page,
    list_recent_scans,
    log_medical_match,
    log_scan_result,
    mark_applied_manually,
    stats,
    update_tailored_resume,
)
from utils.windows_schedule import ScheduleError, schedule_status, set_schedule

# The dashboard and CLI intentionally expose the same canonical locations.
ROOT = PROJECT_ROOT
DB_PATH = CANONICAL_DB_PATH

# CV previews are transient and intentionally bounded.  The dashboard is a
# local workstation tool, not a general-purpose file-processing service; an
# upload above this size offers no practical CV-review benefit and could force
# the server to buffer excessive private data in memory.
MAX_CV_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MiB
CV_UPLOAD_CHUNK_BYTES = 64 * 1024

# The product does not expose a public API surface, so Swagger/ReDoc/OpenAPI
# endpoints are disabled rather than leaving interactive documentation on a
# dashboard that may display private applicant data.
app = FastAPI(title="Jobs-Finder", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(ROOT / "dashboard" / "static")), name="static")
templates = Jinja2Templates(directory=str(ROOT / "dashboard" / "templates"))

# Prevent overlapping dashboard scans from racing to replace the latest saved
# recommendation collection. CLI scanning remains a separate, manual command.
_SCAN_LOCK = asyncio.Lock()


def _is_trusted_local_host(request: Request) -> bool:
    """Reject DNS-rebinding Host headers before exposing local applicant data.

    The dashboard has no authentication and is designed for loopback use.
    ``testserver`` is the in-process TestClient hostname, not a public domain.
    Check the parsed hostname (not a string prefix) and validate any port.
    """
    raw = request.headers.get("host", "")
    if not raw or any(character in raw for character in ",/@?#\\"):
        return False
    try:
        parsed = urlsplit(f"http://{raw}")
        if parsed.path or parsed.query or parsed.fragment or parsed.username is not None:
            return False
        port = parsed.port  # Reject malformed/non-numeric ports.
        return parsed.hostname in {"localhost", "127.0.0.1", "::1", "testserver"} and (port is None or port > 0)
    except ValueError:
        return False


def _is_trusted_local_client(request: Request) -> bool:
    """Refuse remote TCP clients even if a custom Uvicorn launch binds to LAN.

    Host headers are supplied by the caller and cannot establish local origin.
    The shipped launcher/CLI independently restrict listening to loopback,
    while this guard covers direct ASGI/Uvicorn entry points as a second layer.
    The in-process Starlette TestClient uses the special 'testclient' peer.
    """
    peer = request.client.host if request.client else ""
    if peer == "testclient":
        return True
    try:
        address = ipaddress.ip_address(peer)
    except (ValueError, TypeError):
        return False
    if address.version == 6 and address.ipv4_mapped:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


def _is_same_origin_browser_request(request: Request) -> bool:
    """Accept same-origin browser writes while rejecting cross-site requests.

    Jobs-Finder deliberately has no browser authentication because its normal
    deployment is the loopback-only local dashboard.  This check is a focused
    CSRF boundary for the rare case a user explicitly binds it elsewhere: a
    browser that sends Origin or Referer metadata may change state only from
    the dashboard's own origin.  Header-less non-browser calls remain useful
    for local CLI/test tooling and are not an authentication mechanism.
    """
    expected = urlsplit(str(request.base_url))
    supplied = request.headers.get("origin") or request.headers.get("referer")
    if not supplied:
        return True
    candidate = urlsplit(supplied)
    return candidate.scheme == expected.scheme and candidate.netloc == expected.netloc


@app.middleware("http")
async def _protect_browser_responses(request: Request, call_next):
    """Apply privacy defaults and same-origin protection to every route."""
    if not _is_trusted_local_client(request):
        response = JSONResponse(status_code=403, content={"detail": "Remote clients are not allowed. Jobs-Finder is local-only."})
    elif not _is_trusted_local_host(request):
        response = JSONResponse(status_code=400, content={"detail": "Untrusted Host header. Use the local Jobs-Finder address."})
    elif request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and not _is_same_origin_browser_request(request):
        response = JSONResponse(
            status_code=403,
            content={"detail": "Cross-origin state-changing requests are not allowed."},
        )
    else:
        response = await call_next(request)

    # Profile details, generated documents, and scan history are private local
    # data.  Keep them out of browser/proxy caches and prohibit framing and
    # MIME sniffing. The CSP matches the shipped self-hosted HTML/CSS/JS only.
    response.headers.setdefault("Cache-Control", "no-store, max-age=0, private")
    response.headers.setdefault("Pragma", "no-cache")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), microphone=(), payment=(), usb=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; "
        "object-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'",
    )
    return response


async def _read_bounded_cv_upload(file: UploadFile) -> bytes:
    """Read an uploaded CV in bounded chunks, rejecting it before parsing."""
    data = bytearray()
    while True:
        chunk = await file.read(CV_UPLOAD_CHUNK_BYTES)
        if not chunk:
            return bytes(data)
        data.extend(chunk)
        if len(data) > MAX_CV_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"CV upload is too large. The maximum supported size is {MAX_CV_UPLOAD_BYTES // (1024 * 1024)} MiB.",
            )


def _runtime_profile(required: bool = False) -> dict[str, Any]:
    """HTTP adapter around the sole canonical applicant-profile repository.

    This deliberately performs no YAML/path handling of its own.  In
    particular it cannot fall back to profile.yaml.example, an import draft,
    a backup, or a resume cache.
    """
    try:
        return load_canonical_profile(required=required)
    except CanonicalProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    personal = profile.get("personal", {}) if isinstance(profile.get("personal"), dict) else {}
    preferences = profile.get("preferences") or {}
    preferences = preferences if isinstance(preferences, dict) else {}

    def display_locations(items: Any) -> list[str]:
        values: list[str] = []
        for item in items if isinstance(items, list) else []:
            value = (item.get("name") or item.get("value") or item.get("location")) if isinstance(item, dict) else item
            if value and not is_unresolved_value(value):
                values.append(str(value))
        return values

    professional_title = personal.get("professional_title") or ""
    return {
        "name": " ".join(str(personal.get(key, "")).strip() for key in ["first_name", "last_name"]).strip(),
        "title": str(professional_title),
        "email": personal.get("email", ""),
        "phone": personal.get("phone", ""),
        "location": personal.get("location", ""),
        "roles": preferences.get("roles", []) if isinstance(preferences.get("roles"), list) else [],
        "locations": display_locations(preferences.get("locations")),
    }


def _clean_value(value: Any) -> str:
    text = str(value or "").strip()
    return "" if is_unresolved_value(text) else text


def _verified_responsibility_texts(value: Any) -> list[str]:
    """Verified responsibility text from a canonical entry.

    ``responsibilities`` is verification-gated: only an item carrying a literal
    ``verified: true`` is confirmed professional experience. This mirrors
    ``utils.documents`` so the owner's review view and the generated document
    agree on what counts as a fact.
    """
    texts: list[str] = []
    if not isinstance(value, list):
        return texts
    for item in value:
        if isinstance(item, dict) and item.get("verified") is True:
            text = _clean_value(item.get("text"))
            if text:
                texts.append(text)
    return texts


def _pending_responsibility_texts(item: dict[str, Any]) -> list[str]:
    """Duty drafts held back from generated documents, for owner confirmation."""
    texts: list[str] = []
    for entry in item.get("needs_verification") or []:
        if isinstance(entry, dict) and entry.get("verified") is not True:
            text = _clean_value(entry.get("text"))
            if text:
                texts.append(text)
    return texts


def _date_range(item: dict[str, Any]) -> str:
    """Human-readable supplied dates, using the same rule as the generated CV.

    Only the *format* of a supplied value changes ("2020-10" reads "Oct 2020");
    an unsupplied date stays empty, and no precision is ever added.
    """
    from utils.documents import _display_period

    start = _display_period(_clean_value(item.get("start")))
    end = _display_period(_clean_value(item.get("end")))
    return f"{start} – {end}" if start and end else start or end


def _profile_details(profile: dict[str, Any]) -> dict[str, Any]:
    """Professional, read-only profile view for the UI.

    This intentionally returns display fields only. It does not expose raw YAML,
    internal verification flags, evidence IDs, or matching keys.
    """
    summary = profile_summary(profile)
    # The attractive public-facing profile preview must use exactly the same
    # verified-only summary as the Master CV. Previously this displayed a raw
    # unverified owner draft or an empty box even when a strong verified CV
    # summary could be generated. The source file remains unchanged.
    from utils.documents import _verified_profile_summary, generate_master_cv

    professional_summary = _verified_profile_summary(profile)
    if not professional_summary and build_profile_evidence(profile).has_verified("md_degree"):
        professional_summary = generate_master_cv(profile)["master_cv_model"]["profile"]

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
    for source_index, item in enumerate(profile.get("work_history") or []):
        if not isinstance(item, dict):
            continue
        gated = "responsibilities" in item or "needs_verification" in item
        verified = _verified_responsibility_texts(item.get("responsibilities"))
        pending = _pending_responsibility_texts(item)
        if not gated:
            # Owner-authored free-form profile shape: bullet lists carry no
            # per-item verification flag, so they are shown as supplied.
            free_form = item.get("bullets") or item.get("duties") or item.get("achievements") or []
            if isinstance(free_form, str):
                free_form = [free_form]
            verified = [_clean_value(bullet) for bullet in free_form if _clean_value(bullet)]
        experience.append(
            {
                "source_index": source_index,
                "title": _clean_value(item.get("title")),
                "organization": _clean_value(item.get("organization")),
                "location": _clean_value(item.get("location")),
                "dates": _date_range(item),
                "bullets": verified,
                "pending_bullets": pending,
            }
        )

    education = []
    for item in (profile.get("medical_education") or []):
        if isinstance(item, dict):
            education.append(
                {
                    "degree": _clean_value(item.get("degree")),
                    "institution": _clean_value(item.get("institution")),
                    "location": _clean_value(item.get("country") or item.get("location")),
                    "dates": _date_range(item),
                }
            )

    raw_registration = profile.get("license_registration")
    registration: dict[str, Any] = raw_registration if isinstance(raw_registration, dict) else {}
    raw_exit_exam = profile.get("medical_exit_exam")
    exit_exam: dict[str, Any] = raw_exit_exam if isinstance(raw_exit_exam, dict) else {}
    languages = []
    for item in profile.get("languages") or []:
        if isinstance(item, dict):
            name = _clean_value(item.get("name"))
            level = _clean_value(item.get("level"))
            if name:
                languages.append({"name": name, "level": level})

    skills = []
    raw_skills_value = profile.get("skills")
    raw_skills: dict[str, Any] = raw_skills_value if isinstance(raw_skills_value, dict) else {}
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
        "training": named_items(profile.get("certificates") or []),
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
    ("professional_title", "Professional identity/title", "personal:professional_title"),
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
CONFIRMABLE_FIELDS = {"medical_education", "license_registration", "medical_exit_exam"}


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
    # Runtime readiness is derived from canonical profile.yaml only.  CV
    # imports are transient previews and resume/cache text is never evidence
    # for the production applicant.
    evidence = build_profile_evidence(profile)
    fields = []
    for key, label, confirm_field in REVIEW_FIELDS:
        status = _field_status(evidence, key)
        actionable_confirm_field = confirm_field if status != "Missing" else None
        # A collection has no safe one-click "verify all" action. Hide the
        # generic education button when it contains more than one entry; the
        # owner must review the entries individually in canonical profile.yaml.
        if confirm_field == "medical_education":
            education = profile.get("medical_education")
            if not isinstance(education, list) or len([item for item in education if isinstance(item, dict)]) != 1:
                actionable_confirm_field = None
        fields.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "evidence": evidence.evidence_text(key)[:2],
                "confirm_field": actionable_confirm_field,
            }
        )
    return {"fields": fields}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/api/health")
def health():
    return {"ok": True, "product": "Jobs-Finder"}


@app.get("/api/profile")
def api_profile():
    profile = _runtime_profile(False)
    return {"exists": bool(profile), "summary": profile_summary(profile)}


@app.get("/api/profile/details")
def api_profile_details():
    profile = _runtime_profile(False)
    if not profile:
        return {"exists": False, "details": {}}
    return {"exists": True, "details": _profile_details(profile)}


@app.get("/api/generated-file")
def api_generated_file(path: str, download: bool = False):
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
    # A PDF or text document opens directly for an accessible in-browser
    # review. Word documents are downloaded (they cannot be rendered safely
    # by browsers); a user may explicitly download any of the three formats.
    disposition = "attachment" if download or resolved.suffix.lower() == ".docx" else "inline"
    return FileResponse(str(resolved), filename=resolved.name, content_disposition_type=disposition)


@app.get("/api/profile/review")
def api_profile_review():
    profile = _runtime_profile(False)
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
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="A JSON object is required to confirm a profile field.")
    field = str(payload.get("field") or "")
    if not _is_confirmable(field):
        raise HTTPException(status_code=400, detail=f"Unsupported field: {field}")
    profile = _runtime_profile(True)

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
    elif field == "medical_education":
        target = profile.get(field)
        entries = [item for item in target if isinstance(item, dict)] if isinstance(target, list) else []
        # The one-click review view has no entry selector. It may safely
        # confirm a single education fact, but must never bulk-verify several
        # degrees merely because they share a list field.
        if len(entries) != 1:
            raise HTTPException(
                status_code=400,
                detail="Confirm medical_education entries individually in profile.yaml; the dashboard will not bulk-verify multiple facts.",
            )
        entries[0]["verified"] = True
    else:
        target = profile.get(field)
        if not isinstance(target, dict):
            raise HTTPException(status_code=400, detail=f"{field} is not present in profile.yaml.")
        target["verified"] = True

    save_canonical_profile(profile)
    return {"ok": True, "message": f"{field} marked verified in profile.yaml.", "review": _profile_review_payload(profile)}


@app.post("/api/profile/experience/add-responsibility")
async def api_add_verified_responsibility(request: Request):
    """Save owner-attested real job responsibilities, never generated claims."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Submit the responsibility form as JSON.") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid responsibility.")
    source_index = payload.get("source_index")
    text_value = payload.get("text")
    confirmation = payload.get("confirmation")
    if type(source_index) is not int or not isinstance(text_value, str):
        raise HTTPException(status_code=400, detail="Choose the exact role and provide a factual responsibility.")
    import re
    normalized = re.sub(r"\\s+", " ", text_value).strip()
    if len(normalized) < 30 or len(normalized) > 1200:
        raise HTTPException(status_code=400, detail="Write a substantive factual responsibility (30–1200 characters).")
    if confirmation != "I personally confirm this responsibility is factual and belongs to this role":
        raise HTTPException(status_code=400, detail="Confirm this experience is accurate before saving.")
    profile = _runtime_profile(True)
    work = profile.get("work_history")
    if not isinstance(work, list) or not 0 <= source_index < len(work):
        raise HTTPException(status_code=404, detail="The selected work-history role does not exist.")
    entry = work[source_index]
    if not isinstance(entry, dict) or entry.get("verified") is not True:
        raise HTTPException(status_code=409, detail="Confirm the work-history role before adding verified duties.")
    existing = entry.get("responsibilities") or []
    if not isinstance(existing, list):
        raise HTTPException(status_code=409, detail="The canonical responsibilities field must be a list.")
    if any(isinstance(item, dict) and str(item.get("text", "")).casefold() == normalized.casefold() for item in existing):
        raise HTTPException(status_code=409, detail="This responsibility already exists for the selected role.")
    existing.append({"text": normalized, "verified": True})
    entry["responsibilities"] = existing
    save_canonical_profile(profile)
    return {"ok": True, "message": "Your verified responsibility was added to your canonical profile and will appear in new CVs.", "experience": _profile_details(profile)["experience"]}


@app.post("/api/import-cv")
async def api_import_cv(file: UploadFile = File(...)):
    """Return an unverified, request-local CV preview without changing state.

    The upload is placed in a system temporary directory only long enough for
    local text extraction, then deleted.  It never writes profile.yaml, a
    backup, a draft profile, ``resumes/``, or a resume cache.  Consequently an
    imported sample CV can never become the production applicant.
    """
    allowed_suffixes = {".pdf", ".txt", ".md", ".markdown", ".rst", ".csv"}
    suffix = Path(file.filename or "cv.txt").suffix.lower() or ".txt"
    try:
        if suffix not in allowed_suffixes:
            raise HTTPException(status_code=400, detail="Unsupported file type. Upload a PDF or plain-text CV.")
        content = await _read_bounded_cv_upload(file)
    finally:
        # Starlette normally cleans this up after the request, but closing it
        # here makes the preview's non-retention guarantee explicit on both
        # success and every early error path.
        await file.close()

    with tempfile.TemporaryDirectory(prefix="jobs-finder-cv-preview-") as directory:
        uploaded_path = Path(directory) / f"uploaded_cv{suffix}"
        uploaded_path.write_bytes(content)
        # An empty path is intentional: no temporary upload location can be
        # retained in a profile-shaped preview or canonical applicant record.
        preview = build_profile_from_cv_file(str(uploaded_path))

    return {
        "ok": True,
        "persisted": False,
        "message": "CV import preview only. Your canonical profile.yaml was not changed; manually add only facts you confirm.",
        "preview": _profile_review_payload(preview),
    }


@app.get("/api/settings")
def api_settings():
    """Truthful, read-only view of current system configuration.

    Nothing here is an editable toggle: these values reflect the actual
    current discovery budget and active sources. If a value is not actually
    configurable from the UI, it is presented as current configuration, not
    as a control.
    """
    profile = _runtime_profile(False)
    acbar_cfg = ((profile.get("job_sources") or {}).get("acbar") or {}) if isinstance(profile, dict) else {}
    reliefweb_cfg = ((profile.get("job_sources") or {}).get("reliefweb") or {}) if isinstance(profile, dict) else {}
    return {
        "sources": source_registry_for_settings(),
        "acbar": {
            "max_detail_concurrency": acbar_cfg.get("max_detail_concurrency", ACBAR_DEFAULT_DETAIL_CONCURRENCY),
            "timeout_seconds": acbar_cfg.get("timeout_seconds", ACBAR_DEFAULT_TIMEOUT_SECONDS),
            "note": (SOURCE_REGISTRY.get("acbar", {}).get("settings_note") or "ACBAR pagination is followed to the source's real end and every relevant detail page is processed."),
        },
        "reliefweb": {
            "limit": reliefweb_cfg.get("limit", RELIEFWEB_DEFAULT_LIMIT),
            "timeout_seconds": reliefweb_cfg.get("timeout_seconds", RELIEFWEB_DEFAULT_TIMEOUT_SECONDS),
        },
        "background_scanning": False,
        "automatic_submission": False,
    }


def _scan_context(scan: dict[str, Any]) -> dict[str, str] | None:
    """Small, explicit provenance record for a persisted scan collection.

    Recommendation rows are stored scan results, not a live market feed. The
    dashboard needs this timestamp/status context alongside the authoritative
    collection so it can never imply that a historical scan is current.
    """
    if not isinstance(scan, dict) or not scan:
        return None
    return {
        "status": str(scan.get("status") or ""),
        "started_at": str(scan.get("started_at") or ""),
        "finished_at": str(scan.get("finished_at") or ""),
    }


@app.get("/api/recommended")
def api_recommended(limit: int = 200):
    """Serve saved-scan recommendations, updating real-time display safety.

    Scan membership/order remain authoritative. A later request may exclude
    deadlines that have since passed, and overlays the live stored package
    and progress. Original historical scan counts are never rewritten.
    """
    latest = get_latest_scan() or {}
    entries = latest.get("recommendations")
    if isinstance(entries, list):
        fresh = get_actionable_jobs_by_ids([str(entry.get("id")) for entry in entries if isinstance(entry, dict) and entry.get("id")])
        merged = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            row = fresh.get(str(entry.get("id") or ""))
            if row:
                # The saved scan decides *which* role was recommended, but the
                # stored row is the actual state of this user's documents and
                # application. Otherwise "Review package" loses its files
                # every time the browser loads the Recommended page.
                entry = {
                    **entry,
                    **{
                        key: row[key]
                        for key in ("status", "package_status", "package", "documents", "readiness")
                        if key in row
                    },
                    "metadata": row.get("metadata") or entry.get("metadata") or {},
                }
            if is_expired(entry) or entry.get("status") == "APPLIED_MANUALLY":
                continue
            merged.append(entry)
        return {"jobs": merged[:limit], "data_origin": "latest_saved_scan", "scan": _scan_context(latest)}
    return {"jobs": get_recommended_jobs(limit=limit), "data_origin": "stored_history", "scan": None}


@app.get("/api/jobs")
def api_jobs(limit: int = 100, offset: int = 0):
    """Exact actionable ledger with stable pages; never fabricate 200 total."""
    return list_actionable_jobs_page(limit=limit, offset=offset)


@app.get("/api/applications")
def api_applications(limit: int = 100, offset: int = 0):
    """An independent view over ALL saved package/application records."""
    return list_actionable_jobs_page(
        limit=limit, offset=offset,
        statuses=("PACKAGE_READY", "PACKAGE_NEEDS_INPUT", "APPLIED_MANUALLY"),
    )


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
    if _SCAN_LOCK.locked():
        raise HTTPException(status_code=409, detail="A vacancy scan is already running. Please use the result of that scan.")
    async with _SCAN_LOCK:
        try:
            with exclusive_scan():
                profile = _runtime_profile(True)
                scan = await run_discovery_scan(profile)
                # The single canonical matcher/recorder shared with the CLI.
                evaluate_scan_jobs(scan, profile)
                result = scan.to_dict()
                log_scan_result(result)
                record_scan_alerts(scan)
                record_deadline_alerts()
                return result
        except ScanAlreadyRunning as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/alerts")
def api_alerts(limit: int = 50):
    """Persistent local inbox of first-time matches and deadline reminders."""
    return list_alerts(limit=limit)


@app.post("/api/alerts/{alert_id}/read")
def api_alert_read(alert_id: int):
    if not mark_alert_read(alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True}


@app.post("/api/alerts/read-all")
def api_alert_read_all():
    return {"ok": True, "marked": mark_all_alerts_read()}


@app.get("/api/monitor/schedule")
def api_monitor_schedule():
    return schedule_status()


@app.post("/api/monitor/schedule")
async def api_set_monitor_schedule(request: Request):
    """Explicit user opt-in/out; no hidden auto-monitoring on dashboard load."""
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="A JSON settings object is required.") from exc
    if not isinstance(payload, dict) or type(payload.get("enabled")) is not bool:
        raise HTTPException(status_code=400, detail="The enabled setting must be true or false.")
    try:
        return set_schedule(payload["enabled"])
    except ScheduleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/master-cv")
def api_master_cv():
    """Write the position-neutral Master CV from verified canonical evidence.

    This is a local generation action, not a submission. It reads only the
    canonical profile, writes TXT/DOCX/PDF under ignored ``documents/``, and
    never mutates ``profile.yaml``.
    """
    profile = _runtime_profile(True)
    master = write_master_cv(profile, out_dir=ROOT / "documents" / "master_cv")
    return {
        "ok": True,
        "position_neutral": bool(master.get("position_neutral")),
        "documents": master.get("generated_paths", {}),
        "review_warnings": master.get("review_warnings", []),
        "no_submission_performed": True,
    }


@app.post("/api/backup/export")
def api_backup_export():
    """Owner-triggered local archive; never creates a remote copy."""
    try:
        filename, contents = backup_archive()
    except BackupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=contents,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store, max-age=0, private",
        },
    )


@app.post("/api/backup/verify")
async def api_backup_verify(file: UploadFile = File(...)):
    """Independently inspect a user-selected ZIP; never restore or copy it."""
    try:
        if not (file.filename or "").lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Select a Jobs-Finder ZIP backup.")
        content = bytearray()
        while chunk := await file.read(64 * 1024):
            content.extend(chunk)
            if len(content) > MAX_ARCHIVE_BYTES:
                raise HTTPException(status_code=413, detail="The backup exceeds the safe size limit.")
        try:
            return verify_backup_archive(bytes(content))
        except BackupError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    job = get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    return job


@app.post("/api/jobs/{job_id}/prepare")
def api_prepare(job_id: str):
    profile = _runtime_profile(True)
    job = get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    if job.get("status") == "APPLIED_MANUALLY":
        raise HTTPException(status_code=409, detail="This application was already marked as submitted manually. The saved application record has been preserved.")
    if is_expired(job):
        raise HTTPException(status_code=409, detail="This vacancy has passed its stated deadline. Review the official posting for a reopened vacancy instead.")
    report = match_job_against_profile(job, profile).to_dict()
    if report.get("readiness_status") == NOT_ELIGIBLE_STATUS:
        raise HTTPException(status_code=409, detail="This vacancy is NOT_ELIGIBLE; no application package was generated.")
    # Do not change a previously prepared/applicant-tracked record before
    # the replacement files have actually been generated successfully.
    docs = prepare_application_bundle(job, profile, report, out_dir=ROOT / "documents" / "applications")
    log_medical_match(job_id, report)
    update_tailored_resume(job_id, docs)
    return {"job_id": job_id, "documents": docs.get("generated_paths", {}), "package": docs.get("application_package", {})}


@app.get("/api/jobs/{job_id}/email-draft.eml")
def api_email_draft(job_id: str):
    job = get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    if is_expired(job):
        raise HTTPException(status_code=409, detail="This vacancy has expired.")
    try:
        filename, content = build_email_draft(job, project_root=ROOT)
    except EmailDraftError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="message/rfc822",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/api/jobs/{job_id}/open-email")
def api_open_email(job_id: str):
    job = get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    if is_expired(job):
        raise HTTPException(status_code=409, detail="This vacancy has expired.")
    try:
        _filename, content = build_email_draft(job, project_root=ROOT)
        directory = ROOT / "documents" / "email_drafts"
        directory.mkdir(parents=True, exist_ok=True)
        # Repeated clicks must not create unlimited private duplicate drafts.
        # Keep one current unsent draft for each job, with atomic replacement.
        key = hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:32]
        path = directory / f"Jobs-Finder-{key}-UNSENT.eml"
        import uuid
        temporary = directory / f".{key}-{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        open_windows_email_draft(path)
    except EmailDraftError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"opened": True, "sent": False, "message": "Email draft opened in Windows. Review and press Send yourself."}


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
    """Never expose the unauthenticated applicant dashboard to the network.

    Windows launcher, CLI and direct Python callers share this boundary.
    Host-header checks do not replace network-layer access control.
    """
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Jobs-Finder is private: the dashboard must bind only to localhost.")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("Dashboard port must be in the range 1-65535.")
    uvicorn.run("dashboard.server:app", host=host, port=port, reload=False)
