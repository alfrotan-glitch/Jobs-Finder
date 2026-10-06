"""Regression coverage for the one-applicant canonical profile architecture.

Test-only profile mappings are deliberately created under pytest temporary
paths.  They are not production records.  The production identity check reads
the ignored, repository-root canonical file only when it is present locally.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from dashboard import server
from utils import profile as profile_repository
from utils import resume_parser, tracker
from utils.documents import prepare_application_bundle
from utils.medical_matcher import match_job_against_profile
from utils.paths import PROJECT_ROOT
from utils.profile import (
    CanonicalProfileError,
    CanonicalProfileMissingError,
    build_profile_evidence,
    canonical_profile_fingerprint,
    load_canonical_profile,
    save_canonical_profile,
)
from utils.recommendations import evaluate_scan_jobs

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_CV = (FIXTURES / "sample_jane_doe_cv.txt").read_text(encoding="utf-8")
SAMPLE_NAME = SAMPLE_CV.splitlines()[0]
SAMPLE_EMAIL = next(line.split(":", 1)[1].strip() for line in SAMPLE_CV.splitlines() if line.startswith("Email:"))


CANONICAL_TEST_PROFILE = {
    "personal": {
        "first_name": "Canonical",
        "last_name": "Applicant",
        "professional_title": "Medical Doctor (MD)",
        "email": "",
        "phone": "",
        "location": "Kabul",
        "verification": {
            "first_name": True,
            "last_name": True,
            "professional_title": True,
            "email": False,
            "phone": False,
            "location": True,
        },
    },
    "medical_education": [{"degree": "Medical Doctor (MD)", "verified": True}],
    "license_registration": {"status": "Valid medical professional registration/license", "verified": True},
    "medical_exit_exam": {"status": "Completed", "verified": True},
    "clinical_experience": {"years": "> 3", "verified": True},
    "skills": {"medical": [{"name": "HMIS/DHIS2", "verified": True}]},
    "languages": [
        {"name": "Dari", "level": "Native", "verified": True},
        {"name": "English", "level": "Fluent", "verified": True},
    ],
    "preferences": {"locations": [{"name": "Kabul", "verified": True}]},
}


@pytest.fixture
def isolated_canonical_profile(tmp_path, monkeypatch):
    """Create one test-local *canonical* profile, never an alternate runtime path."""
    monkeypatch.setattr(profile_repository, "CANONICAL_PROFILE_PATH", tmp_path / "profile.yaml")
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "applications.db")
    save_canonical_profile(CANONICAL_TEST_PROFILE)
    return CANONICAL_TEST_PROFILE


def _medical_job() -> dict:
    return {
        "id": "canonical-profile-job",
        "title": "Medical Doctor (MD)",
        "company": "Example Health Organization",
        "location": "Kabul",
        "url": "https://jobs.example.org/vacancies/canonical-profile-job",
        "apply_url": "recruitment@example.org",
        "description": (
            "Medical Doctor (MD) required. Valid medical registration, Medical Exit Exam, "
            "3 years clinical experience, HMIS reporting, and fluent English required. "
            "Apply to recruitment@example.org by 2026-12-31."
        ),
        "metadata": {
            "source_name": "ACBAR",
            "source_url": "https://jobs.example.org/source",
            "vacancy_url": "https://jobs.example.org/vacancies/canonical-profile-job",
        },
    }


def test_sample_identity_is_isolated_to_the_test_fixture():
    """No source file outside tests/fixtures may contain the sample applicant."""
    excluded_parts = {".git", ".venv", ".pytest_cache", "__pycache__"}
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file() or excluded_parts.intersection(path.parts) or path == FIXTURES / "sample_jane_doe_cv.txt":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        assert SAMPLE_NAME not in text, path
        assert SAMPLE_EMAIL not in text, path


def test_profile_example_is_never_a_runtime_fallback(tmp_path, monkeypatch):
    """A sample/template beside a missing canonical file must remain inert."""
    monkeypatch.setattr(profile_repository, "CANONICAL_PROFILE_PATH", tmp_path / "profile.yaml")
    (tmp_path / "profile.yaml.example").write_text(
        "personal:\n  first_name: Jane\n  last_name: Doe\n",
        encoding="utf-8",
    )

    assert load_canonical_profile() == {}
    with pytest.raises(CanonicalProfileMissingError):
        load_canonical_profile(required=True)

    # The template itself can never be accepted as a runtime profile, even if
    # a caller attempts to point the canonical location directly at it.
    monkeypatch.setattr(profile_repository, "CANONICAL_PROFILE_PATH", tmp_path / "profile.yaml.example")
    monkeypatch.setattr(profile_repository, "PROFILE_TEMPLATE_PATH", tmp_path / "profile.yaml.example")
    with pytest.raises(CanonicalProfileError, match="schema/template"):
        load_canonical_profile(required=True)


def test_all_runtime_entry_points_and_major_subsystems_share_one_canonical_profile(
    isolated_canonical_profile, monkeypatch, tmp_path
):
    """Dashboard, CLI, matcher/recommendations, and package generation agree."""
    canonical = load_canonical_profile(required=True)
    assert canonical == CANONICAL_TEST_PROFILE
    assert main._require_canonical_profile() == canonical
    assert server._runtime_profile(required=True) == canonical
    assert canonical_profile_fingerprint(canonical) == canonical_profile_fingerprint()

    # The dashboard is another view of exactly the same repository, not a
    # stateful/profile-owning service.
    client = TestClient(server.app)
    dashboard_identity = client.get("/api/profile").json()["summary"]
    assert dashboard_identity["name"] == "Canonical Applicant"
    assert dashboard_identity["location"] == "Kabul"

    job = _medical_job()
    report = match_job_against_profile(job, canonical, today=date(2026, 10, 1)).to_dict()
    assert report["profile_evidence"] == build_profile_evidence(canonical, today=date(2026, 10, 1)).to_dict()

    # Recommendations use the same supplied canonical mapping; the tracker
    # write is replaced here so this remains a pure architecture test.
    import utils.tracker as tracker_module

    monkeypatch.setattr(tracker_module, "log_discovered_and_medical_match", lambda job, report: None)

    class Scan:
        jobs = [job]

        def record_match_results(self, pairs):
            self.pairs = pairs

    scan = Scan()
    evaluate_scan_jobs(scan, canonical)
    assert scan.pairs[0][1]["profile_evidence"] == report["profile_evidence"]

    bundle = prepare_application_bundle(job, canonical, report, out_dir=tmp_path / "documents")
    rendered = "\n".join(
        [
            Path(bundle["generated_paths"]["tailored_cv"]["txt"]).read_text(encoding="utf-8"),
            Path(bundle["generated_paths"]["cover_letter"]["txt"]).read_text(encoding="utf-8"),
            bundle["application_package"]["email_draft"]["body"],
        ]
    )
    assert "Canonical Applicant" in rendered
    assert SAMPLE_NAME not in rendered
    assert SAMPLE_EMAIL not in rendered


def test_database_has_no_applicant_profile_store(isolated_canonical_profile):
    """SQLite is a vacancy/activity store, never a competing applicant source."""
    connection = tracker.get_db()
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    finally:
        connection.close()
    assert tables == {"vacancies", "scan_runs"}
    assert load_canonical_profile(required=True) == CANONICAL_TEST_PROFILE


def test_legacy_resume_cache_cannot_supply_sample_identity_to_production_matching_or_documents(
    isolated_canonical_profile, tmp_path
):
    """A forged legacy cache is ignored; only the explicit source file is read."""
    source_cv = tmp_path / "actual-cv.txt"
    source_cv.write_text("Canonical Applicant\nMedical Doctor (MD)\n", encoding="utf-8")
    legacy_cache = tmp_path / ".cache"
    legacy_cache.mkdir()
    digest = hashlib.sha256(source_cv.read_bytes()).hexdigest()
    (legacy_cache / f"resume_{digest}.txt").write_text(
        f"{SAMPLE_NAME}\n{SAMPLE_EMAIL}\n", encoding="utf-8"
    )
    assert resume_parser.extract_resume_text(str(source_cv)) == source_cv.read_text(encoding="utf-8")

    canonical = load_canonical_profile(required=True)
    job = _medical_job()
    report = match_job_against_profile(job, canonical, today=date(2026, 10, 1)).to_dict()
    bundle = prepare_application_bundle(job, canonical, report, out_dir=tmp_path / "documents")
    generated = Path(bundle["generated_paths"]["tailored_cv"]["txt"]).read_text(encoding="utf-8")
    production_output = json.dumps({"match": report, "document": generated})
    assert SAMPLE_NAME not in production_output
    assert SAMPLE_EMAIL not in production_output


def test_import_cv_is_preview_only_and_cannot_create_an_alternate_profile(
    isolated_canonical_profile, tmp_path, capsys
):
    source_cv = tmp_path / "sample-cv.txt"
    source_cv.write_text(SAMPLE_CV, encoding="utf-8")
    before = profile_repository.canonical_profile_path().read_text(encoding="utf-8")

    main.cmd_import_cv(str(source_cv))

    assert "preview only" in capsys.readouterr().out.lower()
    assert profile_repository.canonical_profile_path().read_text(encoding="utf-8") == before
    assert not list(tmp_path.glob("*.bak"))
    assert list(tmp_path.glob("*.yaml")) == [profile_repository.canonical_profile_path()]


def test_experience_duration_requires_its_own_verified_flag():
    unverified = build_profile_evidence({"clinical_experience": {"years": "> 3", "verified": False}})
    verified = build_profile_evidence({"clinical_experience": {"years": "> 3", "verified": True}})
    assert not unverified.has_verified("clinical_experience_years")
    assert verified.verified_values("clinical_experience_years") == [3.0]
    assert verified.evidence_text("clinical_experience_years", verified_only=True) == ["more than 3 years clinical experience"]


def test_real_runtime_profile_identity_is_consistent_and_contains_no_invented_registration_data(tmp_path):
    """Local integration assertion for the ignored production applicant file.

    A clean CI checkout has no private profile.yaml by design, so it skips this
    test.  In a real local runtime it proves the confirmed applicant identity
    flows unchanged into matching and generated documents.
    """
    if not profile_repository.canonical_profile_path().exists():
        pytest.skip("profile.yaml is ignored private runtime data and is absent in this checkout")

    profile = load_canonical_profile(required=True)
    personal = profile["personal"]
    # Keep actual applicant data out of tracked source. The private profile
    # itself carries the owner-confirmed values; this integration test proves
    # only that resolved/verified identity and core credential fields flow
    # through the real runtime without inventing sensitive identifiers.
    for key in ["first_name", "last_name", "professional_title", "email", "phone", "location"]:
        assert str(personal.get(key) or "").strip()
        assert personal.get("verification", {}).get(key) is True
    assert profile["license_registration"]["number"] == ""
    assert profile["license_registration"]["issue_date"] == ""
    assert profile["license_registration"]["expiry_date"] == ""

    job = _medical_job()
    report = match_job_against_profile(job, profile, today=date(2026, 10, 1)).to_dict()
    bundle = prepare_application_bundle(job, profile, report, out_dir=tmp_path / "real-applicant-documents")
    rendered = "\n".join(
        [
            Path(bundle["generated_paths"]["tailored_cv"]["txt"]).read_text(encoding="utf-8"),
            Path(bundle["generated_paths"]["cover_letter"]["txt"]).read_text(encoding="utf-8"),
            bundle["application_package"]["email_draft"]["body"],
        ]
    )
    assert f"{personal['first_name']} {personal['last_name']}" in rendered
    assert SAMPLE_NAME not in rendered
    assert SAMPLE_EMAIL not in rendered
