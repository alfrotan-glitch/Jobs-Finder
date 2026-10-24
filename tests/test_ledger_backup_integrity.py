"""Contract tests for complete local-ledger pagination and private backup exports."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from dashboard import server
from utils import backups, tracker
from utils.medical_requirements import canonical_source_fields


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "applications.db")
    conn = tracker.get_db()
    try:
        valid_metadata = json.dumps({
            "source_name": "ACBAR",
            "source_url": "https://www.acbar.org/en/jobs",
        })
        # A flood of unusable source rows must not hide 120 earlier,
        # correctly sourced vacancies and manually submitted packages.
        for index in range(450):
            conn.execute(
                """
                INSERT INTO vacancies(id,title,company,source,url,metadata_json,
                    discovered_at,updated_at,status)
                VALUES(?, 'Untrusted listing', 'Unknown', 'UNKNOWN', '', '{}',
                    '2026-11-01T00:00:00', '2026-11-01T00:00:00', 'FOUND')
                """,
                (f"invalid-{index:04d}",),
            )
        for index in range(120):
            status = "REVIEWED" if index < 108 else "PACKAGE_READY" if index < 114 else "APPLIED_MANUALLY"
            conn.execute(
                """
                INSERT INTO vacancies(id,title,company,source,url,metadata_json,
                    discovered_at,updated_at,status,readiness)
                VALUES(?, 'Medical Officer', 'Valid Health NGO', 'ACBAR', ?, ?,
                    '2026-10-24T00:00:00', '2026-10-24T00:00:00', ?, 'READY_TO_APPLY')
                """,
                (
                    f"valid-{index:04d}",
                    f"https://www.acbar.org/en/jobs/details/{145000 + index}/medical-officer",
                    valid_metadata,
                    status,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return TestClient(server.app)


def test_entire_ledger_counts_even_when_newer_untrusted_records_outnumber_page(ledger):
    first = ledger.get("/api/jobs?limit=100&offset=0")
    assert first.status_code == 200
    body = first.json()
    assert body["total"] == 120
    assert len(body["jobs"]) == 100
    assert body["has_more"] is True
    assert body["counts"]["applied"] == 6
    assert body["counts"]["package"] == 6
    assert body["counts"]["ready_to_apply"] == 114
    assert body["counts"]["reviewed"] == 108
    second = ledger.get("/api/jobs?limit=100&offset=100").json()
    assert len(second["jobs"]) == 20
    assert second["has_more"] is False
    ids = [item["id"] for item in body["jobs"] + second["jobs"]]
    assert len(ids) == len(set(ids)) == 120
    assert ids == sorted(ids)
    assert all(not value.startswith("invalid-") for value in ids)
    assert len(tracker.list_actionable_jobs(limit=120)) == 120


def test_old_packages_are_accessible_independently_of_all_jobs_page(ledger):
    result = ledger.get("/api/applications").json()
    assert result["total"] == 12
    assert len(result["jobs"]) == 12
    assert {item["status"] for item in result["jobs"]} == {"PACKAGE_READY", "APPLIED_MANUALLY"}
    assert ledger.get("/api/jobs/valid-0119").json()["status"] == "APPLIED_MANUALLY"
    assert ledger.get("/api/applications?limit=5&offset=10").json()["has_more"] is False


def test_invalid_pagination_values_are_bounded_and_do_not_drop_history(ledger):
    assert len(ledger.get("/api/jobs?limit=10000").json()["jobs"]) == 120
    result = ledger.get("/api/jobs?limit=0&offset=-50").json()
    assert len(result["jobs"]) == 1
    assert result["offset"] == 0
    assert result["total"] == 120


def test_official_online_form_takes_precedence_over_secondary_contact_email():
    job = {
        "id": "ctg-form",
        "title": "District Polio Officer",
        "company": "CTG",
        "url": "https://www.acbar.org/en/jobs/details/146110/district-polio-officer-dpo",
        "metadata": {
            "source_name": "ACBAR", "source_url": "https://www.acbar.org/en/jobs",
            "vacancy_url": "https://www.acbar.org/en/jobs/details/146110/district-polio-officer-dpo",
            "application_method": "WEB",
            "apply_url": "https://app.tayohr.io/jobs/detail/74521",
            "apply_email": "generic-contact@example.org",
        },
    }
    fields = canonical_source_fields(job)
    assert fields["application_method"] == "WEB"
    assert fields["apply_url"] == "https://app.tayohr.io/jobs/detail/74521"
    assert not fields["apply_email"]
    job["metadata"]["apply_url"] = ""
    fields = canonical_source_fields(job)
    assert fields["application_method"] == "UNAVAILABLE"
    assert not fields["direct_application_route_actionable"]
    job["metadata"]["application_method"] = "EMAIL"
    assert canonical_source_fields(job)["application_method"] == "EMAIL"


def test_consistent_private_zip_backup_and_integrity_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(backups, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "applications.db")
    profile = tmp_path / "profile.yaml"
    profile.write_text("personal:\n  first_name: Verified\n", encoding="utf-8")
    document = tmp_path / "documents" / "applications" / "cover_letter.txt"
    document.parent.mkdir(parents=True)
    document.write_text("Private application document", encoding="utf-8")
    outside = tmp_path.parent / "private_references_secret.yaml"
    outside.write_text("PRIVATE MUST NOT BE ARCHIVED", encoding="utf-8")
    with tracker.get_db() as conn:
        conn.execute(
            "INSERT INTO vacancies(id,title,company,status) VALUES('old','MD','Health NGO','APPLIED_MANUALLY')"
        )
    before = (tmp_path / "applications.db").read_bytes()
    name, payload = backups.backup_archive()
    assert name.startswith("jobs-finder-backup-")
    assert name.endswith(".zip")
    with ZipFile(io.BytesIO(payload)) as archive:
        assert set(archive.namelist()) == {
            "profile.yaml", "applications.db", "documents/applications/cover_letter.txt",
            "manifest.json",
        }
        manifest = json.loads(archive.read("manifest.json"))
        for entry, data in manifest["files"].items():
            content = archive.read(entry)
            assert len(content) == data["bytes"]
            assert hashlib.sha256(content).hexdigest() == data["sha256"]
        assert b"PRIVATE MUST NOT BE ARCHIVED" not in payload
        restored = tmp_path / "restore-proof.db"
        restored.write_bytes(archive.read("applications.db"))
    with sqlite3.connect(restored) as snapshot:
        assert snapshot.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert snapshot.execute("SELECT status FROM vacancies WHERE id='old'").fetchone()[0] == "APPLIED_MANUALLY"
    assert (tmp_path / "applications.db").read_bytes() == before
    assert profile.read_text(encoding="utf-8") == "personal:\n  first_name: Verified\n"


def test_backup_api_is_explicit_private_post_not_automatic(tmp_path, monkeypatch):
    monkeypatch.setattr(backups, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "applications.db")
    (tmp_path / "profile.yaml").write_text("personal: {}\n", encoding="utf-8")
    client = TestClient(server.app)
    assert client.get("/api/backup/export").status_code == 405
    response = client.post("/api/backup/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"].startswith("no-store")
    assert "applications.db" in ZipFile(io.BytesIO(response.content)).namelist()
    (tmp_path / "profile.yaml").unlink()
    assert client.post("/api/backup/export").status_code == 409
