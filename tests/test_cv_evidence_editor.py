"""Applicant-owned work evidence can be expanded without inventing duties."""

from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from dashboard import server
from utils.profile import load_canonical_profile


def test_verified_role_detail_requires_literal_user_attestation(monkeypatch):
    original = load_canonical_profile(required=True)
    profile = copy.deepcopy(original)
    stored = []
    monkeypatch.setattr(server, "_runtime_profile", lambda required=False: profile)
    monkeypatch.setattr(server, "save_canonical_profile", lambda value: stored.append(copy.deepcopy(value)))
    client = TestClient(server.app)
    entries = profile["work_history"]
    index = next(i for i, entry in enumerate(entries) if entry.get("verified") is True)
    duty = (
        "Provided clinical assessment and SAM treatment according to verified "
        "existing TFU protocols, including follow-up documented in patient records."
    )
    url = "/api/profile/experience/add-responsibility"
    data = {"source_index": index, "text": duty}
    before = copy.deepcopy(profile)
    assert client.post(url, json=data).status_code == 400
    assert profile == before
    data["confirmation"] = "I personally confirm this responsibility is factual and belongs to this role"
    response = client.post(url, json=data)
    assert response.status_code == 200, response.text
    assert profile["work_history"][index]["responsibilities"][-1] == {"text": duty, "verified": True}
    assert stored and stored[-1] == profile
    assert client.post(url, json=data).status_code == 409


def test_verified_duty_cannot_be_attached_to_nonverified_or_unknown_role(monkeypatch):
    profile = copy.deepcopy(load_canonical_profile(required=True))
    monkeypatch.setattr(server, "_runtime_profile", lambda required=False: profile)
    client = TestClient(server.app)
    url = "/api/profile/experience/add-responsibility"
    payload = {
        "source_index": 1000,
        "text": "A factual description of personal role responsibilities should be placed here.",
        "confirmation": "I personally confirm this responsibility is factual and belongs to this role",
    }
    assert client.post(url, json=payload).status_code == 404
    payload["source_index"] = 0
    payload["text"] = "Invented"
    assert client.post(url, json=payload).status_code == 400


def test_profile_editor_is_present_in_dashboard():
    from utils.paths import PROJECT_ROOT

    source = (PROJECT_ROOT / "dashboard" / "static" / "app.js").read_text(encoding="utf-8")
    assert "data-action=\"add-responsibility\"" in source
    assert "/api/profile/experience/add-responsibility" in source
    assert "personally confirm this responsibility" in source
