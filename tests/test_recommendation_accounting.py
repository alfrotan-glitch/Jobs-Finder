"""Recommendation accounting: one authority, one collection.

``utils/recommendations.py`` is the single authority, so every surface counts
and renders the same collection:

* ``scan.recommendations`` is built ONCE from the scan's own (job, match)
  pairs; ``recommended_from_scan == len(scan.recommendations)`` structurally.
* The CLI prints exactly that collection; ``/api/find``, ``/api/recommended``
  and persisted scan activity serve the same collection — no recomputation.
* Broad discovery keeps programme/operations roles reviewable in the jobs
  list, but the recommendation gate requires a positively compatible
  professional-role classification, so a generic "Project Manager" on a health
  project is never recommended to an MD profile.
"""

import asyncio
from datetime import date

import pytest
import yaml
from fastapi.testclient import TestClient

import main
from dashboard import server
from utils import tracker
from utils.discovery import Job, ScanResult, SourceReport
from utils.medical_requirements import analyze_professional_role
from utils.recommendations import collect_scan_recommendations, is_recommendable

TODAY = date(2026, 10, 1)

MD_PROFILE = {
    "personal": {"first_name": "Jane", "last_name": "Doe", "email": "doctor@example.org", "gender": "male", "nationality": "Afghan"},
    "medical_education": [{"degree": "MD (Doctor of Medicine)", "verified": True}],
    "license_registration": {"status": "Valid medical professional registration/license", "verified": True},
    "medical_exit_exam": {"status": "Completed", "verified": True},
    "clinical_experience": {"years": 6},
    "ngo_humanitarian_experience": {"years": 5},
    "work_history": [
        {
            "title": "TFU Medical Doctor",
            "organization": "Action Against Hunger",
            "start": "2021-01",
            "end": "2023-06",
            "verified": True,
            "skills": ["IMAM", "CMAM", "HMIS", "supervision", "reporting"],
        }
    ],
    "preferences": {"locations": ["Afghanistan"], "field_deployment": True},
    "languages": [
        {"name": "Dari", "level": "Native", "verified": True},
        {"name": "English", "level": "Professional", "verified": True},
    ],
}


def fixture_job(identifier, title, description, *, closing="2026-12-31"):
    return Job(
        identifier,
        title,
        "Example NGO",
        "Kabul",
        f"https://www.acbar.org/en/jobs/details/{identifier}/{identifier}",
        "hr@example.org",
        "acbar",
        description,
        metadata={
            "source_name": "ACBAR",
            "source": "ACBAR",
            "source_url": "https://www.acbar.org/en/jobs",
            "vacancy_url": f"https://www.acbar.org/en/jobs/details/{identifier}/{identifier}",
            "application_method": "EMAIL",
            "apply_email": "hr@example.org",
            "closing_date": closing,
        },
    )


MD_JOB = fixture_job(
    "101",
    "Medical Doctor (MD)",
    "Job Requirements Graduated from a registered and recognized medical faculty, passed the exit exam. "
    "Having 3 years of relevant work experience in similar health facilities. HMIS reporting. "
    "Fluency in English. Send your CV to hr@example.org before 2026-12-31.",
)
NUTRITION_TRAINER_JOB = fixture_job(
    "102",
    "Nutrition Trainer",
    "Train facility staff on IMAM, CMAM, therapeutic feeding and malnutrition treatment protocols. "
    "Support supervision of health facilities and MoPH reporting. Apply hr@example.org by 2026-12-31.",
)
PM_JOB = fixture_job(
    "103",
    "Project Manager",
    "Manage the health and nutrition project budget, donor reporting and logistics. "
    "Liaise with MoPH and cluster partners. 5 years project management experience. Apply hr@example.org.",
)
CLIC_JOB = fixture_job(
    "104",
    "CLIC Operator",
    "Operate the ACBAR CLIC payment platform, register applicants, data entry and reporting. Apply hr@example.org.",
)
PHARMACIST_JOB = fixture_job(
    "105",
    "Pharmacist",
    "BSc Pharmacy with valid pharmacy licence required. Manage pharmacy stock. Apply hr@example.org.",
)


def matched_pairs(scan, profile=MD_PROFILE):
    """Real matcher outcomes for every retained scan job (production path)."""
    from utils.medical_matcher import match_job_against_profile

    return [(job.to_dict(), match_job_against_profile(job.to_dict(), profile, today=TODAY).to_dict()) for job in scan.jobs]


def scan_with(*jobs):
    report = SourceReport(id="acbar", name="ACBAR", tier="A", attempted=True, ok=True, status="SCANNED")
    return ScanResult("SCAN_COMPLETE", list(jobs), [report], "start", "finish", "Scan completed.")


# ---------------------------------------------------------------------------
# 1. The gate: broad discovery stays, incompatible roles are not recommended
# ---------------------------------------------------------------------------


def test_generic_programme_role_on_health_project_is_only_ambiguous():
    role = analyze_professional_role(
        "Project Manager",
        "Manage the health and nutrition project budget and donor reporting. Liaise with MoPH.",
    )
    assert role["classification"] not in {"md_physician_role", "health_public_health_compatible"}


def test_health_domain_trainer_role_is_positively_compatible():
    role = analyze_professional_role(
        "Nutrition Trainer",
        "Train staff on IMAM, CMAM, therapeutic feeding and malnutrition treatment. Supervise health facilities.",
    )
    assert role["classification"] == "health_public_health_compatible"


def test_recommendation_gate_matrix():
    md = MD_JOB.to_dict()
    pm = PM_JOB.to_dict()
    assert is_recommendable(md, {"readiness_status": "READY_TO_APPLY"})
    assert is_recommendable(md, {"readiness_status": "NEEDS_VERIFICATION"})
    assert not is_recommendable(md, {"readiness_status": "NOT_ELIGIBLE"})
    assert not is_recommendable(pm, {"readiness_status": "NEEDS_VERIFICATION"})
    assert not is_recommendable(pm, {"readiness_status": "READY_TO_APPLY"})
    assert not is_recommendable(md, {})


def test_collection_excludes_ambiguous_and_incompatible_roles():
    scan = scan_with(MD_JOB, NUTRITION_TRAINER_JOB, PM_JOB, CLIC_JOB, PHARMACIST_JOB)
    pairs = matched_pairs(scan)
    scan.record_match_results(pairs)
    titles = {entry["title"] for entry in scan.recommendations}
    assert "Medical Doctor (MD)" in titles
    assert "Nutrition Trainer" in titles
    assert "Project Manager" not in titles
    assert "CLIC Operator" not in titles
    assert "Pharmacist" not in titles
    # Structural invariants: the summary count IS the collection length.
    assert scan.recommended_from_scan == len(scan.recommendations) == 2
    assert scan.summary()["recommended_from_scan"] == 2
    # Counters still account for EVERY retained job independently.
    totals = scan.summary()
    assert totals["not_eligible_from_scan"] >= 1  # pharmacist is proven incompatible


def test_recommendations_are_ready_first_then_closing_date():
    early = fixture_job("201", "Medical Officer", "MD required, exit exam. Apply hr@example.org.", closing="2026-11-01")
    late = fixture_job("202", "Clinical Mentor", "Mentor and supervise clinical teams in OPD treatment and MoPH reporting. Apply hr@example.org.", closing="2026-10-15")
    pairs = [
        (early.to_dict(), {"readiness_status": "READY_TO_APPLY"}),
        (late.to_dict(), {"readiness_status": "NEEDS_VERIFICATION"}),
    ]
    entries = collect_scan_recommendations(pairs)
    assert [entry["id"] for entry in entries] == ["201", "202"]


# ---------------------------------------------------------------------------
# 2. CLI: printed list == summary count (requested validation #5/#6)
# ---------------------------------------------------------------------------


def _recommended_count_line(output: str) -> int:
    for line in output.splitlines():
        if line.startswith("Recommended from this scan:"):
            return int(line.rsplit(":", 1)[1].strip())
    raise AssertionError(f"summary count line missing:\n{output}")


def _printed_recommendation_titles(output: str) -> list[str]:
    import re

    lines = output.splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == "Recommended vacancies:")
    titles = []
    for line in lines[start + 1:]:
        stripped = line.strip()
        if not stripped:
            break
        match = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if match:
            titles.append(match.group(2))
    return titles


def test_cli_scan_prints_exactly_the_authoritative_collection(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")

    async def fake_scan(profile, today=None):
        return scan_with(MD_JOB, NUTRITION_TRAINER_JOB, PM_JOB, CLIC_JOB, PHARMACIST_JOB)

    monkeypatch.setattr(main, "run_discovery_scan", fake_scan)
    asyncio.run(main.cmd_scan(dict(MD_PROFILE)))
    output = capsys.readouterr().out
    count = _recommended_count_line(output)
    titles = _printed_recommendation_titles(output)
    assert len(titles) == count == 2
    assert not any("Project Manager" in title or "CLIC Operator" in title for title in titles)


# ---------------------------------------------------------------------------
# 3. Dashboard + scan activity: same collection everywhere
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "PROFILE_PATH", tmp_path / "profile.yaml")
    monkeypatch.setattr(server, "UPLOADS_DIR", tmp_path / "resumes")
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    return TestClient(server.app)


def test_dashboard_find_recommended_and_scan_activity_agree(client, monkeypatch):
    (server.PROFILE_PATH).write_text(yaml.safe_dump(dict(MD_PROFILE)), encoding="utf-8")

    async def fake_scan(profile):
        return scan_with(MD_JOB, NUTRITION_TRAINER_JOB, PM_JOB, CLIC_JOB, PHARMACIST_JOB)

    monkeypatch.setattr(server, "run_discovery_scan", fake_scan)
    response = client.post("/api/find")
    assert response.status_code == 200
    body = response.json()
    # One collection, one count.
    assert body["summary"]["recommended_from_scan"] == len(body["recommendations"]) == 2
    ordered_ids = [entry["id"] for entry in body["recommendations"]]
    assert not any(entry["title"] == "Project Manager" for entry in body["recommendations"])

    recommended = client.get("/api/recommended").json()["jobs"]
    assert [entry["id"] for entry in recommended] == ordered_ids

    latest = client.get("/api/scan/latest").json()["scan"]
    assert latest["summary"]["recommended_from_scan"] == 2
    assert [entry["id"] for entry in latest["recommendations"]] == ordered_ids

    scans = client.get("/api/scans").json()["scans"]
    assert [entry["id"] for entry in scans[0]["recommendations"]] == ordered_ids


def test_tracker_stored_view_uses_the_same_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    scan = scan_with(MD_JOB, PM_JOB)
    pairs = matched_pairs(scan)
    for (job_data, report) in pairs:
        tracker.log_discovered(job_data)
        tracker.log_medical_match(job_data["id"], report)
    stored = tracker.get_recommended_jobs()
    titles = {job["title"] for job in stored}
    assert "Medical Doctor (MD)" in titles
    assert "Project Manager" not in titles
