from pathlib import Path

from utils.profile import build_profile_evidence
from utils import tracker


def test_cv_claims_are_not_verified_and_unknown_language_stays_unverified():
    profile = {"languages": [{"name": "English", "level": "Needs verification"}]}
    evidence = build_profile_evidence(profile, "MD, registered physician with English language skills")
    assert not any(item.verified for item in evidence.items["md_degree"])
    assert not any(item.verified for item in evidence.items["language_english"])


def test_explicit_profile_verification_is_preserved():
    evidence = build_profile_evidence({"medical_education": [{"degree": "MD", "verified": True}]})
    assert any(item.verified for item in evidence.items["md_degree"])


def test_applied_transition_requires_exact_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    tracker.log_discovered({"id": "j", "title": "Role", "company": "Org", "url": "https://example.org", "apply_url": "https://example.org"})
    ok, _ = tracker.mark_applied_manually("j")
    assert not ok
    ok, _ = tracker.mark_applied_manually("j", confirmation="APPLIED j")
    assert ok


def test_default_server_binding_is_local_only():
    assert 'host: str = "127.0.0.1"' in Path("dashboard/server.py").read_text()
    assert 'default="127.0.0.1"' in Path("main.py").read_text()
