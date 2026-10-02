"""Dashboard API tests: the backend is the sole authority for evidence and
verification status; the UI only displays/collects what these endpoints
return.
"""

import io

import pytest
import yaml
from fastapi.testclient import TestClient

from dashboard import server
from utils import tracker
from utils.discovery import ScanResult, SourceReport


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "PROFILE_PATH", tmp_path / "profile.yaml")
    monkeypatch.setattr(server, "UPLOADS_DIR", tmp_path / "resumes")
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    return TestClient(server.app)


def test_health_endpoint_has_no_fake_version_claim(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "version" not in body


def test_profile_missing_initially(client):
    response = client.get("/api/profile")
    assert response.status_code == 200
    assert response.json()["exists"] is False


def test_profile_review_empty_when_no_profile(client):
    response = client.get("/api/profile/review")
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is False
    assert body["fields"] == []


SYNTHETIC_CV = (
    "Jane Doe\nMedical Doctor (MD)\nEmail: jane.doe@example.org\n"
    "License: Afghan Medical Council registration, valid medical license\n"
    "Medical Exit Exam: Completed\nLanguages: English (fluent)\n"
)


def test_import_cv_creates_draft_that_needs_review(client):
    response = client.post(
        "/api/import-cv",
        files={"file": ("cv.txt", io.BytesIO(SYNTHETIC_CV.encode("utf-8")), "text/plain")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_draft"] is True
    assert body["fields"]
    assert all(field["status"] != "Verified" for field in body["fields"])


def test_import_cv_rejects_unsupported_file_type(client):
    response = client.post(
        "/api/import-cv",
        files={"file": ("cv.exe", io.BytesIO(b"not a cv"), "application/octet-stream")},
    )
    assert response.status_code == 400


def test_import_cv_backs_up_existing_profile(client, tmp_path):
    (tmp_path / "profile.yaml").write_text("personal:\n  first_name: Existing\n", encoding="utf-8")
    response = client.post(
        "/api/import-cv",
        files={"file": ("cv.txt", io.BytesIO(SYNTHETIC_CV.encode("utf-8")), "text/plain")},
    )
    assert response.status_code == 200
    backup = tmp_path / "profile.yaml.bak"
    assert backup.exists()
    assert "Existing" in backup.read_text(encoding="utf-8")


def test_confirm_endpoint_rejects_unknown_field(client):
    server.PROFILE_PATH.write_text("personal:\n  first_name: Jane\n", encoding="utf-8")
    response = client.post("/api/profile/confirm", json={"field": "not_a_real_field"})
    assert response.status_code == 400


def test_confirm_endpoint_flips_only_the_requested_verified_flag(client):
    profile = {
        "personal": {"first_name": "Jane", "last_name": "Doe", "email": "doctor@example.org"},
        "medical_education": [{"degree": "MD", "verified": False}],
        "license_registration": {"status": "Mentioned in CV; verify details", "verified": False},
    }
    server.PROFILE_PATH.write_text(yaml.safe_dump(profile), encoding="utf-8")

    response = client.post("/api/profile/confirm", json={"field": "medical_education"})
    assert response.status_code == 200

    updated = yaml.safe_load(server.PROFILE_PATH.read_text(encoding="utf-8"))
    assert updated["medical_education"][0]["verified"] is True
    # Unrelated field must not be silently verified by this call.
    assert updated["license_registration"]["verified"] is False


def test_confirm_endpoint_supports_confirming_one_personal_field(client):
    """Identity/contact/nationality/location are confirmed per field so one
    explicit click cannot silently verify unrelated personal facts."""
    profile = {
        "personal": {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "doctor@example.org",
            "nationality": "Afghan",
            "location": "Kabul",
        },
    }
    server.PROFILE_PATH.write_text(yaml.safe_dump(profile), encoding="utf-8")

    review = client.get("/api/profile/review").json()
    nationality_row = next(f for f in review["fields"] if f["key"] == "nationality")
    location_row = next(f for f in review["fields"] if f["key"] == "location")
    assert nationality_row["status"] == "Needs verification"
    assert nationality_row["confirm_field"] == "personal:nationality"
    assert location_row["status"] == "Needs verification"
    assert location_row["confirm_field"] == "personal:location"

    response = client.post("/api/profile/confirm", json={"field": "personal:nationality"})
    assert response.status_code == 200

    updated = yaml.safe_load(server.PROFILE_PATH.read_text(encoding="utf-8"))
    assert updated["personal"]["verification"]["nationality"] is True
    assert updated["personal"]["verification"].get("location") is not True

    review_after = client.get("/api/profile/review").json()
    nationality_row_after = next(f for f in review_after["fields"] if f["key"] == "nationality")
    location_row_after = next(f for f in review_after["fields"] if f["key"] == "location")
    assert nationality_row_after["status"] == "Verified"
    assert location_row_after["status"] == "Needs verification"


def test_confirm_endpoint_supports_confirming_a_specific_language_with_level(client):
    profile = {
        "personal": {"first_name": "Jane", "last_name": "Doe", "email": "doctor@example.org"},
        "languages": [
            {"name": "English", "level": "Needs verification", "verified": False},
            {"name": "Dari", "level": "Needs verification", "verified": False},
        ],
    }
    server.PROFILE_PATH.write_text(yaml.safe_dump(profile), encoding="utf-8")

    response = client.post("/api/profile/confirm", json={"field": "language:English", "level": "Fluent"})
    assert response.status_code == 200

    updated = yaml.safe_load(server.PROFILE_PATH.read_text(encoding="utf-8"))
    by_name = {item["name"]: item for item in updated["languages"]}
    assert by_name["English"]["verified"] is True
    assert by_name["English"]["level"] == "Fluent"
    assert by_name["Dari"]["verified"] is False


def test_confirm_endpoint_rejects_language_confirmation_without_a_level(client):
    profile = {"languages": [{"name": "English", "level": "Needs verification", "verified": False}]}
    server.PROFILE_PATH.write_text(yaml.safe_dump(profile), encoding="utf-8")
    response = client.post("/api/profile/confirm", json={"field": "language:English"})
    assert response.status_code == 400


def test_confirm_endpoint_rejects_placeholder_level_text(client):
    profile = {"languages": [{"name": "English", "level": "Needs verification", "verified": False}]}
    server.PROFILE_PATH.write_text(yaml.safe_dump(profile), encoding="utf-8")
    response = client.post("/api/profile/confirm", json={"field": "language:English", "level": "Unknown"})
    assert response.status_code == 400


def test_confirm_endpoint_rejects_language_not_present(client):
    profile = {"languages": [{"name": "Dari", "level": "Native", "verified": False}]}
    server.PROFILE_PATH.write_text(yaml.safe_dump(profile), encoding="utf-8")
    response = client.post("/api/profile/confirm", json={"field": "language:French", "level": "Fluent"})
    assert response.status_code == 400


def test_settings_endpoint_reflects_acbar_budget_not_a_toggle(client):
    response = client.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    # A normal ACBAR scan has no artificial page ceiling; a page cap is only
    # meaningful when a user explicitly configures it and must make the scan partial.
    assert body["acbar"]["max_pages"] is None
    assert body["acbar"]["detail_limit"] is None
    assert body["acbar"]["max_detail_concurrency"] > 0
    assert body["sources"]
    assert all(source.get("official_url") for source in body["sources"])
    assert body["background_scanning"] is False
    assert body["automatic_submission"] is False


def test_latest_scan_endpoint_returns_backend_persisted_scan(client):
    assert client.get("/api/scan/latest").json()["scan"] is None
    tracker.log_scan_result({
        "status": "PARTIAL_SCAN",
        "message": "Partial market scan.",
        "started_at": "2026-10-01T00:00:00+00:00",
        "finished_at": "2026-10-01T00:00:01+00:00",
        "jobs": [],
        "source_reports": [{"id": "acbar", "name": "ACBAR", "status": "PARTIAL", "listings_seen": 12}],
        "job_count": 0,
    })
    body = client.get("/api/scan/latest").json()
    assert body["scan"]["status"] == "PARTIAL_SCAN"
    assert body["scan"]["source_reports"][0]["status"] == "PARTIAL"


def test_find_requires_a_profile(client):
    response = client.post("/api/find")
    assert response.status_code == 400


def test_find_returns_authoritative_complete_scan_summary(client, monkeypatch):
    server.PROFILE_PATH.write_text("personal: {}\n", encoding="utf-8")
    report = SourceReport(
        id="acbar", name="ACBAR", tier="A", attempted=True, ok=True,
        status="PARTIAL", pages_requested=2, pages_succeeded=1, pages_failed=1,
        pagination_stop_reason="REQUEST_FAILED", listings_seen=4,
        listing_parse_failures=1, vacancies_parsed=2,
        not_processed_due_to_budget=1, irrelevant_excluded=1,
        relevant_retained=1, application_routes_found=1,
        application_routes_unavailable=0, partial_reasons=["LISTING_PAGE_FAILURE"],
    )
    scan = ScanResult("PARTIAL_SCAN", [], [report], "start", "finish", "Partial")

    async def fake_scan(profile):
        return scan

    monkeypatch.setattr(server, "run_discovery_scan", fake_scan)
    response = client.post("/api/find")
    assert response.status_code == 200
    body = response.json()
    assert body["source_reports"][0]["partial_reasons"] == ["LISTING_PAGE_FAILURE"]
    assert body["summary"]["pages_requested"] == 2
    assert body["summary"]["listings_seen"] == 4
    assert body["summary"]["recommended_from_scan"] == 0
