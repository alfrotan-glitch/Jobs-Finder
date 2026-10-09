"""Dashboard API tests: the backend is the sole authority for evidence and
verification status; the UI only displays/collects what these endpoints
return.
"""

import io
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from dashboard import server
from utils import profile as profile_repository
from utils import tracker
from utils.discovery import ScanResult, SourceReport


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_repository, "CANONICAL_PROFILE_PATH", tmp_path / "profile.yaml")
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


SYNTHETIC_CV = (Path(__file__).parent / "fixtures" / "sample_jane_doe_cv.txt").read_text(encoding="utf-8")


def test_import_cv_returns_unverified_preview_without_creating_a_profile(client, tmp_path):
    response = client.post(
        "/api/import-cv",
        files={"file": ("cv.txt", io.BytesIO(SYNTHETIC_CV.encode("utf-8")), "text/plain")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["persisted"] is False
    assert body["preview"]["fields"]
    assert all(field["status"] != "Verified" for field in body["preview"]["fields"])
    assert not profile_repository.canonical_profile_path().exists()
    assert not (tmp_path / "profile.yaml.bak").exists()
    assert not (tmp_path / "resumes").exists()


def test_import_cv_rejects_unsupported_file_type(client):
    response = client.post(
        "/api/import-cv",
        files={"file": ("cv.exe", io.BytesIO(b"not a cv"), "application/octet-stream")},
    )
    assert response.status_code == 400


def test_import_cv_cannot_overwrite_or_create_a_competing_profile(client, tmp_path):
    canonical = profile_repository.canonical_profile_path()
    original = "personal:\n  first_name: Existing\n"
    canonical.write_text(original, encoding="utf-8")
    response = client.post(
        "/api/import-cv",
        files={"file": ("cv.txt", io.BytesIO(SYNTHETIC_CV.encode("utf-8")), "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["persisted"] is False
    assert canonical.read_text(encoding="utf-8") == original
    assert not (tmp_path / "profile.yaml.bak").exists()
    assert not (tmp_path / "resumes").exists()


def test_confirm_endpoint_rejects_unknown_field(client):
    profile_repository.canonical_profile_path().write_text("personal:\n  first_name: Jane\n", encoding="utf-8")
    response = client.post("/api/profile/confirm", json={"field": "not_a_real_field"})
    assert response.status_code == 400


def test_confirm_endpoint_flips_only_the_requested_verified_flag(client):
    profile = {
        "personal": {"first_name": "Jane", "last_name": "Doe", "email": "doctor@example.org"},
        "medical_education": [{"degree": "MD", "verified": False}],
        "license_registration": {"status": "Mentioned in CV; verify details", "verified": False},
    }
    profile_repository.canonical_profile_path().write_text(yaml.safe_dump(profile), encoding="utf-8")

    response = client.post("/api/profile/confirm", json={"field": "medical_education"})
    assert response.status_code == 200

    updated = yaml.safe_load(profile_repository.canonical_profile_path().read_text(encoding="utf-8"))
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
    profile_repository.canonical_profile_path().write_text(yaml.safe_dump(profile), encoding="utf-8")

    review = client.get("/api/profile/review").json()
    nationality_row = next(f for f in review["fields"] if f["key"] == "nationality")
    location_row = next(f for f in review["fields"] if f["key"] == "location")
    assert nationality_row["status"] == "Needs verification"
    assert nationality_row["confirm_field"] == "personal:nationality"
    assert location_row["status"] == "Needs verification"
    assert location_row["confirm_field"] == "personal:location"

    response = client.post("/api/profile/confirm", json={"field": "personal:nationality"})
    assert response.status_code == 200

    updated = yaml.safe_load(profile_repository.canonical_profile_path().read_text(encoding="utf-8"))
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
    profile_repository.canonical_profile_path().write_text(yaml.safe_dump(profile), encoding="utf-8")

    response = client.post("/api/profile/confirm", json={"field": "language:English", "level": "Fluent"})
    assert response.status_code == 200

    updated = yaml.safe_load(profile_repository.canonical_profile_path().read_text(encoding="utf-8"))
    by_name = {item["name"]: item for item in updated["languages"]}
    assert by_name["English"]["verified"] is True
    assert by_name["English"]["level"] == "Fluent"
    assert by_name["Dari"]["verified"] is False


def test_confirm_endpoint_rejects_language_confirmation_without_a_level(client):
    profile = {"languages": [{"name": "English", "level": "Needs verification", "verified": False}]}
    profile_repository.canonical_profile_path().write_text(yaml.safe_dump(profile), encoding="utf-8")
    response = client.post("/api/profile/confirm", json={"field": "language:English"})
    assert response.status_code == 400


def test_confirm_endpoint_rejects_placeholder_level_text(client):
    profile = {"languages": [{"name": "English", "level": "Needs verification", "verified": False}]}
    profile_repository.canonical_profile_path().write_text(yaml.safe_dump(profile), encoding="utf-8")
    response = client.post("/api/profile/confirm", json={"field": "language:English", "level": "Unknown"})
    assert response.status_code == 400


def test_confirm_endpoint_rejects_language_not_present(client):
    profile = {"languages": [{"name": "Dari", "level": "Native", "verified": False}]}
    profile_repository.canonical_profile_path().write_text(yaml.safe_dump(profile), encoding="utf-8")
    response = client.post("/api/profile/confirm", json={"field": "language:French", "level": "Fluent"})
    assert response.status_code == 400


def test_settings_endpoint_reflects_acbar_connection_settings_not_budgets(client):
    response = client.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    assert "max_pages" not in body["acbar"]
    assert "detail_limit" not in body["acbar"]
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
    profile_repository.canonical_profile_path().write_text("personal: {}\n", encoding="utf-8")
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


def test_professional_title_is_confirmed_as_a_personal_field(client):
    profile = {"personal": {"first_name": "Jane", "last_name": "Doe", "professional_title": "Medical Doctor"}}
    profile_repository.canonical_profile_path().write_text(yaml.safe_dump(profile), encoding="utf-8")

    review = client.get("/api/profile/review").json()
    title_row = next(f for f in review["fields"] if f["key"] == "professional_title")
    assert title_row["status"] == "Needs verification"
    assert title_row["confirm_field"] == "personal:professional_title"

    response = client.post("/api/profile/confirm", json={"field": "personal:professional_title"})
    assert response.status_code == 200

    updated = yaml.safe_load(profile_repository.canonical_profile_path().read_text(encoding="utf-8"))
    assert updated["personal"]["verification"]["professional_title"] is True
    assert "professional_title" not in {key for key in updated if key != "personal"}

    review_after = client.get("/api/profile/review").json()
    title_after = next(f for f in review_after["fields"] if f["key"] == "professional_title")
    assert title_after["status"] == "Verified"


# ---------------------------------------------------------------------------
# Position-neutral Master CV from the dashboard
#
# The dashboard's Master CV button is a local generation action: it must be
# driven by the canonical profile, must produce all three artifacts, and must
# never mutate the canonical profile or claim an application was submitted.
# ---------------------------------------------------------------------------


CANONICAL_DASHBOARD_PROFILE = {
    "personal": {
        "first_name": "Dashboard",
        "last_name": "Applicant",
        "professional_title": "Medical Doctor / Health & Nutrition Specialist",
        "email": "dashboard.applicant@example.org",
        "phone": "+93 700 555 111",
        "location": "Kabul, Afghanistan",
        "verification": {
            "first_name": True,
            "last_name": True,
            "professional_title": True,
            "email": True,
            "phone": True,
            "location": True,
        },
    },
    "medical_education": [{"degree": "Doctor of Medicine (MD)", "field": "Curative Medicine", "institution": "Verified Medical University", "start": "2013", "end": "2020", "verified": True}],
    "license_registration": {"status": "Valid medical professional registration/license", "verified": True},
    "medical_exit_exam": {"status": "Completed", "verified": True},
    "clinical_experience": {"years": "> 3", "verified": True},
    "work_history": [
        {
            "title": "Health & Nutrition Supervisor",
            "organization": "Verified NGO",
            "location": "Daikundi, Afghanistan",
            "responsibilities": [
                "Supervised health and nutrition service delivery across the supported coverage areas",
                "Supported IMAM/CMAM implementation, including SAM/MAM case identification and OTP service linkage",
                "Conducted field monitoring visits and reviewed service records to support timely HMIS reporting",
                "Coordinated with MoPH and health-authority counterparts on BPHS/EPHS-aligned service delivery",
            ],
            "verified": True,
        }
    ],
    "skills": {
        "medical": [{"name": "IMAM/CMAM", "verified": True}],
        "public_health": [{"name": "HMIS/DHIS2", "verified": True}],
        "management": [{"name": "Team supervision/capacity building", "verified": True}],
    },
    "certificates": [{"name": "Safeguarding & PSEA — Verified NGO — 2024", "verified": True}],
    "languages": [
        {"name": "Dari/Persian", "level": "Native", "verified": True},
        {"name": "English", "level": "Fluent", "verified": True},
    ],
}


def test_master_cv_endpoint_writes_all_artifacts_without_mutating_or_submitting(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_repository, "CANONICAL_PROFILE_PATH", tmp_path / "profile.yaml")
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(server, "ROOT", tmp_path)
    profile_repository.save_canonical_profile(CANONICAL_DASHBOARD_PROFILE)
    before = profile_repository.canonical_profile_path().read_bytes()

    response = TestClient(server.app).post("/api/master-cv")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["position_neutral"] is True
    assert body["no_submission_performed"] is True
    paths = body["documents"]
    for kind in ["txt", "docx", "pdf"]:
        assert Path(paths[kind]).is_file(), kind
    text = Path(paths["txt"]).read_text(encoding="utf-8")
    assert "Dashboard Applicant" in text
    assert "PROFESSIONAL SUMMARY" in text
    assert "CORE PROFESSIONAL COMPETENCIES" in text
    assert "PROFESSIONAL EXPERIENCE" in text
    assert "IMAM/CMAM" in text
    assert "Available on request for shortlisted applications." in text
    # Generation is a local write only: the canonical profile is untouched.
    assert profile_repository.canonical_profile_path().read_bytes() == before


def _repository_documents_snapshot() -> dict[str, tuple[int, int]]:
    """Size and mtime of every file under the repository's ignored documents/ folder."""
    from utils.paths import PROJECT_ROOT

    root = PROJECT_ROOT / "documents"
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_dashboard_master_cv_never_writes_to_the_repository_documents_folder(tmp_path, monkeypatch):
    """Regression: the endpoint once wrote to the repo's documents/ despite the test's ROOT patch."""
    monkeypatch.setattr(profile_repository, "CANONICAL_PROFILE_PATH", tmp_path / "profile.yaml")
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(server, "ROOT", tmp_path)
    profile_repository.save_canonical_profile(CANONICAL_DASHBOARD_PROFILE)
    before = _repository_documents_snapshot()

    response = TestClient(server.app).post("/api/master-cv")

    assert response.status_code == 200
    written = Path(response.json()["documents"]["pdf"]).resolve()
    assert tmp_path.resolve() in written.parents
    assert _repository_documents_snapshot() == before


def test_generation_output_directories_do_not_depend_on_the_working_directory():
    """Defaults are anchored to the project root, never the process CWD (see utils/paths.py)."""
    import inspect

    from utils.documents import prepare_application_bundle, write_master_cv
    from utils.paths import PROJECT_ROOT

    for function in (write_master_cv, prepare_application_bundle):
        default = Path(inspect.signature(function).parameters["out_dir"].default)
        assert default.is_absolute(), function.__name__
        assert PROJECT_ROOT in default.parents, function.__name__


def test_profile_view_separates_confirmed_scope_from_unconfirmed_drafts(tmp_path, monkeypatch):
    """The owner-facing view must never pass a draft off as confirmed experience.

    ``responsibilities`` is verification-gated. The review page shows the
    confirmed scope as the role's bullets and lists the held-back drafts
    separately, so the owner can confirm or discard them. Raw profile objects
    (including their internal `verified`/`basis` keys) must never be stringified
    into the page.
    """
    real_profile = profile_repository.load_canonical_profile(required=True)
    monkeypatch.setattr(profile_repository, "CANONICAL_PROFILE_PATH", tmp_path / "profile.yaml")
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    profile_repository.save_canonical_profile(real_profile)

    response = TestClient(server.app).get("/api/profile/details")

    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    experience = body["details"]["experience"]
    assert len(experience) == 5
    confirmed_total = 0
    draft_total = 0
    for role in experience:
        confirmed_total += len(role["bullets"])
        draft_total += len(role["pending_bullets"])
        for bullet in role["bullets"]:
            assert "{" not in bullet and "'verified'" not in bullet, bullet
            assert "basis" not in bullet, bullet
            assert "NEEDS_VERIFICATION" not in bullet, bullet
        for draft in role["pending_bullets"]:
            assert "{" not in draft and "NEEDS_VERIFICATION" not in draft, draft
    assert confirmed_total == 6  # the applicant-supplied duties restored to the roles
    assert draft_total == 24  # every held-back draft is still visible to the owner


def test_profile_view_drafts_are_never_listed_as_confirmed_experience(tmp_path, monkeypatch):
    """A duty the applicant never supplied must not appear as a role's bullets."""
    real_profile = profile_repository.load_canonical_profile(required=True)
    monkeypatch.setattr(profile_repository, "CANONICAL_PROFILE_PATH", tmp_path / "profile.yaml")
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    profile_repository.save_canonical_profile(real_profile)

    payload = TestClient(server.app).get("/api/profile/details").json()["details"]
    confirmed = [bullet for role in payload["experience"] for bullet in role["bullets"]]
    drafts = [draft for role in payload["experience"] for draft in role["pending_bullets"]]

    for role in real_profile["work_history"]:
        for item in role["needs_verification"]:
            assert item["text"] not in confirmed
            assert item["text"] in drafts
    # Confirmed responsibilities restate the applicant's own supplied CV
    # evidence for that role -- never a held draft and never a new claim.
    supplied = real_profile["applicant_supplied_source"]["supplied_role_notes"]

    def role_key(text: str) -> str:
        return re.sub(r"[^a-z]+", "", str(text).lower())

    # The applicant's own role labels differ slightly from the normalized
    # titles ("Health and Nutrition Supervisor" vs "Health & Nutrition
    # Supervisor"), so match on the role identity, not on exact spelling.
    supplied_by_role = {
        role_key(note["role"]): note["supplied"] for note in supplied
    }
    supplied_sequence = [note["supplied"] for note in supplied]

    def normalise(text: str) -> str:
        return " ".join(str(text).replace(".", " ").split()).lower()

    for index, (role, entry) in enumerate(zip(payload["experience"], real_profile["work_history"])):
        assert role["bullets"], entry["title"]
        notes = supplied_by_role.get(role_key(entry["title"])) or supplied_sequence[index]
        supplied_text = normalise(" ".join(notes))
        for bullet in role["bullets"]:
            assert supplied_text, (entry["title"], bullet)
            shared = {
                token
                for token in re.split(r"[^a-z]+", normalise(bullet))
                if len(token) > 4 and token in supplied_text
            }
            assert len(shared) >= 3, (entry["title"], bullet, sorted(shared))
