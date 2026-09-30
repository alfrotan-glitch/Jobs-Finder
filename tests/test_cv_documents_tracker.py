from pathlib import Path

from utils.discovery import Job, deduplicate_jobs
from utils.documents import generate_tailored_documents
from utils.medical_matcher import match_job_against_profile
from utils.resume_parser import extract_resume_text, parse_cv_evidence
from utils import tracker


def test_text_cv_parsing_and_evidence(tmp_path):
    cv = tmp_path / "cv.txt"
    cv.write_text("MD physician with 5 years clinical experience. Languages: Dari, Pashto, English. HMIS and BPHS reporting.")
    text = extract_resume_text(str(cv))
    assert "5 years" in text
    evidence = parse_cv_evidence({"personal": {}}, str(cv))
    assert "md_degree" in evidence
    assert "clinical_experience_years" in evidence
    assert "language_dari" in evidence


def test_deduplicate_jobs_by_reference_and_url():
    a = Job("1", "Medical Officer", "NGO", "Kabul", "https://x/jobs/1", "https://x/apply/1", "test", metadata={"reference_number": "REF-1"})
    b = Job("2", "Medical Officer", "NGO", "Kabul", "https://x/jobs/duplicate", "https://x/apply/2", "test", metadata={"reference_number": "REF-1"})
    c = Job("3", "Medical Officer", "NGO", "Kabul", "https://x/jobs/3?utm=1", "https://x/jobs/3", "test")
    d = Job("4", "Medical Officer", "NGO", "Kabul", "https://x/jobs/3", "https://x/jobs/3", "test")
    unique = deduplicate_jobs([a, b, c, d])
    assert [j.id for j in unique] == ["1", "3"]


def test_tailored_documents_do_not_claim_missing_license():
    job = {
        "id": "j1",
        "title": "Medical Officer",
        "company": "NGO",
        "location": "Kabul",
        "url": "https://example.org/job",
        "apply_url": "https://example.org/apply",
        "description": "Medical Officer. MD and valid medical license required. Closing date: 30 September 2026.",
        "metadata": {},
    }
    profile = {
        "personal": {"first_name": "A", "last_name": "Doctor", "email": "a@example.org", "location": "Kabul"},
        "medical_education": [{"degree": "MD", "institution": "Kabul Medical University"}],
        "clinical_experience": {"years": 3},
        "languages": [{"name": "Dari"}],
        "preferences": {"locations": ["Kabul"]},
    }
    report = match_job_against_profile(job, profile).to_dict()
    docs = generate_tailored_documents(job, profile, report)
    assert "professional license" not in docs["cover_letter"].lower()
    assert any("License" in warning or "license" in warning for warning in docs["review_warnings"])


def test_application_state_transitions_require_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "apps.db")
    job = Job("job-state", "Medical Officer", "NGO", "Kabul", "https://x/job", "https://x/apply", "test")
    tracker.log_discovered(job)
    ok, msg = tracker.transition_application_state("job-state", "opened")
    assert ok, msg
    ok, msg = tracker.transition_application_state("job-state", "submitted", explicit_confirmation=False)
    assert not ok
    assert "confirmation" in msg.lower()
    ok, msg = tracker.transition_application_state("job-state", "submitted", explicit_confirmation=True)
    assert ok, msg
    assert tracker.get_job_by_id("job-state")["status"] == "submitted"


def test_low_priority_job_can_still_be_prepared_and_opened_for_review(tmp_path, monkeypatch):
    import utils.tracker as tracker
    from utils.discovery import Job

    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "applications.db")
    job = Job(
        id="low_priority_review_job",
        title="Clinic Manager",
        company="Health NGO",
        location="Kabul",
        url="https://example.org/job",
        apply_url="https://example.org/apply",
        platform="test",
        description="",
    )
    tracker.log_discovered(job)
    tracker.log_medical_match(job.id, {"priority": "Low priority", "explanation": "Not enough years", "facts": {}})
    assert tracker.get_job_by_id(job.id)["status"] == "not_eligible"
    tracker.update_tailored_resume(job.id, {"tailored_cv_text": "draft", "cover_letter": "letter"})
    assert tracker.get_job_by_id(job.id)["status"] == "prepared"
    ok, message = tracker.transition_application_state(job.id, "opened")
    assert ok, message
    ok, message = tracker.transition_application_state(job.id, "submitted", explicit_confirmation=False)
    assert not ok
    assert "Explicit user confirmation" in message


def test_tailored_cv_is_application_ready_and_keeps_warnings_separate():
    job = {
        "id": "j-review-ready",
        "title": "Medical Officer",
        "company": "Health NGO",
        "location": "Kabul",
        "url": "https://example.org/job",
        "apply_url": "https://example.org/apply",
        "description": "Medical Officer. MD and valid medical license required. Closing date: 30 September 2026.",
        "metadata": {},
    }
    profile = {
        "personal": {"first_name": "A", "last_name": "Doctor", "email": "a@example.org", "location": "Kabul"},
        "medical_education": [{"degree": "MD", "institution": "Kabul Medical University"}],
        "clinical_experience": {"years": 3},
        "work_history": [{"title": "Medical Officer", "organization": "Clinic", "start": "2024-01", "end": "2024-12", "bullets": ["Provided clinical care."]}],
        "languages": [{"name": "Dari"}],
        "preferences": {"locations": ["Kabul"]},
    }
    report = match_job_against_profile(job, profile).to_dict()
    docs = generate_tailored_documents(job, profile, report)
    cv_lower = docs["tailored_cv_text"].lower()
    cover_lower = docs["cover_letter"].lower()
    assert "tailored cv draft" not in cv_lower
    assert "review notes" not in cv_lower
    assert "needs verification" not in cv_lower
    assert "i have not included" not in cover_lower
    assert any("license" in warning.lower() for warning in docs["review_warnings"])
