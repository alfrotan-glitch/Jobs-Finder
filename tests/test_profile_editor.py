"""Owner-editable profile: durable, optimistic-locked, verified-only facts."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from dashboard import server
from utils import profile as profile_repository
from utils.profile_editor import CONFIRMATION, apply_editor_change, editor_snapshot


@pytest.fixture
def owner(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_repository, "CANONICAL_PROFILE_PATH", tmp_path / "profile.yaml")
    profile = {
        "personal": {
            "first_name": "Jane", "last_name": "Doe",
            "email": "jane@example.org", "phone": "+93 700 000 000",
            "verification": {"first_name": True, "last_name": True, "email": True, "phone": True},
        },
        "professional_summary": {"text": "Confirmed physician experience.", "verified": True},
        "work_history": [
            {
                "title": "Physician", "organization": "Example Clinic", "verified": True,
                "responsibilities": [{"text": "Provided clinical assessment and referral in primary care.", "verified": True}],
                "needs_verification": [{"text": "Supervised the team and led service coordination.", "verified": False}],
            },
        ],
        "preferences": {"roles": ["Doctor"], "locations": [{"name": "Kabul", "verified": True}]},
        "private_reference_boundary": {"release_requires_owner_approval": True},
    }
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    return TestClient(server.app), path


def _get(client):
    result = client.get("/api/profile/editor")
    assert result.status_code == 200
    return result.json()


def _save(client, version, change):
    return client.post("/api/profile/editor", json={"version": version, **change})


def test_editor_snapshots_are_filtered_and_do_not_expose_private_reference_notes(owner):
    client, _ = owner
    editor = _get(client)
    assert editor["personal"]["first_name"] == "Jane"
    assert "private_reference_boundary" not in editor
    assert editor["experience"][0]["pending"][0]["text"].startswith("Supervised")
    assert editor["documents"]["cv_layout"] == "comfortable"


def test_editing_contact_invalidates_only_changed_field_verification(owner):
    client, path = owner
    result = _save(client, _get(client)["version"], {
        "action": "personal", "field": "email", "value": "new@example.org",
    })
    assert result.status_code == 200
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["personal"]["email"] == "new@example.org"
    assert saved["personal"]["verification"]["email"] is False
    assert saved["personal"]["verification"]["phone"] is True
    assert saved["work_history"][0]["responsibilities"][0]["verified"] is True


def test_owner_confirmation_for_changed_fact_is_explicit(owner):
    client, path = owner
    result = _save(client, _get(client)["version"], {
        "action": "personal", "field": "email",
        "value": "verified@example.org", "confirmation": CONFIRMATION,
    })
    assert result.status_code == 200
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["personal"]["verification"]["email"] is True


def test_one_stale_form_cannot_overwrite_newer_profile(owner):
    client, path = owner
    original = _get(client)["version"]
    assert _save(client, original, {"action": "summary", "value": "New draft"}).status_code == 200
    before = path.read_bytes()
    conflict = _save(client, original, {"action": "summary", "value": "Old overwritten"})
    assert conflict.status_code == 409
    assert path.read_bytes() == before


def test_bulk_edits_are_all_or_nothing(owner):
    client, path = owner
    original = path.read_bytes()
    response = _save(client, _get(client)["version"], {
        "action": "bulk", "changes": [
            {"action": "personal", "field": "phone", "value": "+93 700 111 222"},
            {"action": "personal", "field": "not_a_field", "value": "bad"},
        ],
    })
    assert response.status_code == 409
    assert path.read_bytes() == original


def test_document_preferences_round_trip_and_future_cv_model(owner):
    client, path = owner
    response = _save(client, _get(client)["version"], {
        "action": "documents", "cv_layout": "compact", "letter_depth": "detailed",
    })
    assert response.status_code == 200
    assert response.json()["editor"]["documents"]["cv_layout"] == "compact"
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["document_preferences"]["cv_layout"] == "compact"
    from utils.documents import generate_master_cv
    model = generate_master_cv(profile_repository.load_canonical_profile(required=True))["master_cv_model"]
    assert model["cv_layout"] == "compact"


def test_verified_duties_are_not_replaced_by_unverified_edits(owner):
    client, path = owner
    response = _save(client, _get(client)["version"], {
        "action": "responsibility", "role_index": 0, "bullet_index": 0,
        "operation": "update", "value": "Managed outpatient clinical consultations and referrals for patients.",
    })
    assert response.status_code == 200
    responsibility = yaml.safe_load(path.read_text(encoding="utf-8"))["work_history"][0]["responsibilities"][0]
    assert responsibility["verified"] is False


def test_pending_draft_requires_exact_owner_attestation(owner):
    client, path = owner
    version = _get(client)["version"]
    data = {"action": "responsibility", "role_index": 0, "bullet_index": 0, "operation": "approve"}
    assert _save(client, version, data).status_code == 409
    assert _save(client, version, {**data, "confirmation": CONFIRMATION}).status_code == 200
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert len(saved["work_history"][0]["needs_verification"]) == 0
    assert saved["work_history"][0]["responsibilities"][-1]["verified"] is True


def test_no_arbitrary_schema_or_private_reference_injections(owner):
    client, path = owner
    before = path.read_bytes()
    assert _save(client, _get(client)["version"], {"action": "personal", "field": "professional_references",
        "value": "PRIVATE"}).status_code == 409
    assert path.read_bytes() == before


def test_shipped_editor_is_wired_into_real_html_and_js():
    html = Path("dashboard/templates/index.html").read_text(encoding="utf-8")
    script = Path("dashboard/static/app.js").read_text(encoding="utf-8")
    assert 'id="profileEditor"' in html
    assert "async function saveProfileEditor()" in script
    assert "/api/profile/editor" in script
    assert 'if (action === "save-profile-editor")' in script
    assert "function renderProfileEditor()" in script
