"""FastAPI dashboard for the final small Jobs-Finder product."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from utils.discovery import run_discovery_scan
from utils.documents import prepare_application_bundle
from utils.medical_matcher import NOT_ELIGIBLE_STATUS, match_job_against_profile
from utils.resume_parser import extract_resume_text
from utils.tracker import (
    get_job_by_id,
    get_recommended_jobs,
    list_jobs,
    log_discovered,
    log_medical_match,
    mark_applied_manually,
    stats,
    update_tailored_resume,
)

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "profile.yaml"

app = FastAPI(title="Jobs-Finder", version="3.0")
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
    return {
        "name": " ".join(str(personal.get(key, "")).strip() for key in ["first_name", "last_name"]).strip(),
        "email": personal.get("email", ""),
        "phone": personal.get("phone", ""),
        "location": personal.get("location", ""),
        "resume_path": profile.get("resume_path", ""),
        "roles": (profile.get("preferences") or {}).get("roles", []) if isinstance(profile.get("preferences"), dict) else [],
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/api/health")
def health():
    return {"ok": True, "product": "Jobs-Finder", "version": "3.0"}


@app.get("/api/profile")
def api_profile():
    profile = load_profile(False)
    return {"exists": bool(profile), "summary": profile_summary(profile)}


@app.get("/api/recommended")
def api_recommended(limit: int = 20):
    return {"jobs": get_recommended_jobs(limit=limit)}


@app.get("/api/jobs")
def api_jobs(limit: int = 200):
    return {"jobs": list_jobs(limit=limit)}


@app.get("/api/stats")
def api_stats():
    return stats()


@app.post("/api/find")
async def api_find():
    profile = load_profile(True)
    scan = await run_discovery_scan(profile)
    resume_text = extract_resume_text(profile.get("resume_path", ""))
    for job in scan.jobs:
        log_discovered(job)
        report = match_job_against_profile(job.to_dict(), profile, resume_text=resume_text).to_dict()
        log_medical_match(job.id, report)
    return scan.to_dict()


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
def api_mark_applied(job_id: str):
    ok, message = mark_applied_manually(job_id)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    return {"ok": True, "message": message}


def run_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    uvicorn.run("dashboard.server:app", host=host, port=port, reload=False)
