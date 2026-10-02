from pathlib import Path

from utils import tracker
from utils.profile import build_profile_evidence


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


def test_unverified_structured_degree_does_not_satisfy_match():
    from utils.medical_matcher import (
        NEEDS_VERIFICATION_STATUS,
        match_job_against_profile,
    )
    report = match_job_against_profile(
        {"title": "Medical Officer", "description": "Medical Degree required. Apply to hr@example.org."},
        {"medical_education": [{"degree": "MD", "verified": False}]},
    )
    assert report.readiness_status == NEEDS_VERIFICATION_STATUS
    assert any(item.key == "md_degree" and item.status == "Needs verification" for item in report.requirement_matches)


def test_tracking_rejects_wrong_and_missing_confirmation_and_unknown_job(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    ok, _ = tracker.mark_applied_manually("missing", confirmation="APPLIED missing")
    assert not ok
    tracker.log_discovered({"id": "j2", "title": "Role", "company": "Org", "url": "https://example.org"})
    assert not tracker.mark_applied_manually("j2", confirmation="yes")[0]
    assert not tracker.mark_applied_manually("j2")[0]
    assert tracker.mark_applied_manually("j2", confirmation="APPLIED j2")[0]
    assert tracker.mark_applied_manually("j2", confirmation="APPLIED j2")[0]
