"""Dashboard confirmation must never bulk-verify independent profile facts."""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from dashboard import server
from utils import profile as profile_repository
from utils import tracker


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_repository, "CANONICAL_PROFILE_PATH", tmp_path / "profile.yaml")
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    return TestClient(server.app)


def test_dashboard_refuses_to_bulk_verify_multiple_education_entries(client):
    canonical = profile_repository.canonical_profile_path()
    canonical.write_text(
        yaml.safe_dump(
            {
                "medical_education": [
                    {"degree": "MD", "verified": False},
                    {"degree": "MPH", "verified": False},
                ]
            }
        ),
        encoding="utf-8",
    )

    review = client.get("/api/profile/review").json()
    degree = next(field for field in review["fields"] if field["key"] == "md_degree")
    assert degree["confirm_field"] is None

    response = client.post("/api/profile/confirm", json={"field": "medical_education"})
    assert response.status_code == 400
    updated = yaml.safe_load(canonical.read_text(encoding="utf-8"))
    assert [item["verified"] for item in updated["medical_education"]] == [False, False]
