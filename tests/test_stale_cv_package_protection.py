"""A static CV generated with an old engine must never be treated as updated."""
from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from dashboard import server
from utils.package_freshness import generation_stamp, package_freshness
from utils.profile import load_canonical_profile


def _package(profile):
    return {
        "package_status": "READY_FOR_REVIEW",
        "generation": generation_stamp(
            profile, {"tailored_cv_model": {
                "selected_duty_count": 15, "full_verified_duty_count": 24,
            }},
        ),
    }


def test_legacy_and_profile_changed_employer_pdfs_need_regeneration():
    profile = load_canonical_profile(required=True)
    current = _package(profile)
    assert package_freshness(current, profile) == {
        "current": True, "reason": "verified_current_generation",
    }
    old = {"package_status": "READY_FOR_REVIEW"}
    assert package_freshness(old, profile)["reason"] == "old_cv_generator"
    revised = deepcopy(profile)
    revised["personal"]["professional_title"] = "Changed locally after export"
    assert package_freshness(current, revised)["reason"] == "profile_changed"
    wrong_revision = deepcopy(current)
    wrong_revision["generation"]["revision"] = "2026-10-01-old-cv"
    assert package_freshness(wrong_revision, profile)["current"] is False


def test_job_detail_exposes_staleness_before_offering_old_pdf(monkeypatch):
    job = {
        "id": "historical-medical-coordinator",
        "title": "Medical Coordinator",
        "package": {"package_status": "READY_FOR_REVIEW"},
    }
    monkeypatch.setattr(server, "get_job_by_id", lambda _id: deepcopy(job))
    response = TestClient(server.app).get("/api/jobs/historical-medical-coordinator")
    assert response.status_code == 200
    assert response.json()["package_freshness"]["current"] is False


def test_old_prepared_package_cannot_open_or_download_unsent_email(monkeypatch):
    job = {
        "id": "historical-medical-coordinator",
        "title": "Medical Coordinator",
        "package": {"package_status": "READY_FOR_REVIEW"},
    }
    monkeypatch.setattr(server, "get_job_by_id", lambda _id: deepcopy(job))
    def should_never_compose(*args, **kwargs):
        raise AssertionError("An obsolete package must not reach email composition.")
    monkeypatch.setattr(server, "build_email_draft", should_never_compose)
    client = TestClient(server.app)
    response = client.get("/api/jobs/historical-medical-coordinator/email-draft.eml")
    assert response.status_code == 409
    assert "Regenerate" in response.json()["detail"]
    response = client.post("/api/jobs/historical-medical-coordinator/open-email")
    assert response.status_code == 409
    assert "Regenerate" in response.json()["detail"]


def test_real_medical_coordinator_curated_cv_has_substantive_primary_roles():
    from utils.documents import generate_tailored_documents

    profile = load_canonical_profile(required=True)
    job = {"title": "Medical Coordinator", "description":
           "Medical coordination, supervision of health facilities, monitoring, TFU and health-team reporting."}
    model = generate_tailored_documents(job, profile, {})["tailored_cv_model"]
    jobs = model["experience"]
    assert len(jobs) == 5
    assert len(jobs[0]["bullets"]) >= 4
    assert len(jobs[1]["bullets"]) >= 4
    assert 11 <= model["selected_duty_count"] <= model["full_verified_duty_count"]
    assert model["full_verified_duty_count"] == 24
    assert model["is_employer_curated"] is True
    assert model["references"] == ["Available on request for shortlisted applications."]
