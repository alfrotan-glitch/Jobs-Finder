"""Private referee editor: contact data stays off Git and out of applications."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from dashboard import server
from utils import private_references as references
from utils.documents import generate_master_cv
from utils.profile import load_canonical_profile


@pytest.fixture
def secure_store(tmp_path, monkeypatch):
    dest = tmp_path / "appdata" / "Jobs-Finder" / "private_references.yaml"
    monkeypatch.setattr(references, "private_reference_editor_path", lambda: dest)
    return dest


def _sample_reference():
    return {
        "name": "Sample Clinical Referee",
        "role": "Supervisor",
        "organization": "Sample Hospital",
        "phone": "+93 700 111 222",
        "email": "referee@example.org",
        "relationship": "Clinical supervisor",
    }


def test_private_reference_list_edit_save_and_remove(secure_store):
    client = TestClient(server.app)
    first = client.get("/api/profile/references")
    assert first.status_code == 200
    assert first.json()["entries"] == []
    saved = client.post("/api/profile/references", json={
        "version": first.json()["version"], "entries": [_sample_reference()],
    })
    assert saved.status_code == 200
    assert secure_store.is_file()
    assert references.PROJECT_ROOT.resolve() not in secure_store.resolve().parents
    entries = yaml.safe_load(secure_store.read_text(encoding="utf-8"))["entries"]
    assert entries == [_sample_reference()]
    updated = deepcopy(entries[0])
    updated["organization"] = "Updated Hospital"
    second = client.post("/api/profile/references", json={
        "version": saved.json()["version"], "entries": [updated],
    })
    assert second.status_code == 200
    assert client.get("/api/profile/references").json()["entries"][0]["organization"] == "Updated Hospital"
    removed = client.post("/api/profile/references", json={
        "version": second.json()["version"], "entries": [],
    })
    assert removed.status_code == 200
    assert yaml.safe_load(secure_store.read_text(encoding="utf-8"))["entries"] == []


def test_private_ref_stale_update_and_invalid_name_are_rejected(secure_store):
    client = TestClient(server.app)
    old = client.get("/api/profile/references").json()["version"]
    assert client.post("/api/profile/references", json={
        "version": old, "entries": [_sample_reference()],
    }).status_code == 200
    before = secure_store.read_bytes()
    assert client.post("/api/profile/references", json={
        "version": old, "entries": [],
    }).status_code == 409
    assert client.post("/api/profile/references", json={
        "version": client.get("/api/profile/references").json()["version"],
        "entries": [{"name": "", "email": "anonymous@example.org"}],
    }).status_code == 409
    assert secure_store.read_bytes() == before


def test_private_contacts_do_not_leak_to_master_cv_or_profile_editor(secure_store):
    client = TestClient(server.app)
    digest = client.get("/api/profile/references").json()["version"]
    assert client.post("/api/profile/references", json={
        "version": digest, "entries": [_sample_reference()],
    }).status_code == 200
    profile = client.get("/api/profile/editor").json()
    assert "referee@example.org" not in str(profile)
    result = generate_master_cv(load_canonical_profile(required=True))["master_cv_text"]
    assert "referee@example.org" not in result
    assert "+93 700 111 222" not in result
    assert "Sample Clinical Referee" not in result


def test_external_reference_file_defaults_outside_repository(tmp_path, monkeypatch):
    monkeypatch.delenv(references.PRIVATE_REFERENCES_ENV, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "windows-appdata"))
    path = references.private_reference_editor_path()
    assert path.parent == tmp_path / "windows-appdata" / "Jobs-Finder"
    assert references.PROJECT_ROOT not in path.parents
