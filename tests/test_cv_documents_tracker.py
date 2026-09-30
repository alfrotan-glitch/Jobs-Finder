from pathlib import Path

from utils.discovery import Job, deduplicate_jobs
from utils.documents import generate_application_package, generate_tailored_documents
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


def test_tailored_cv_core_competencies_dedupe_nested_acronyms():
    job = {
        "id": "j-dedupe",
        "title": "Quality Officer",
        "company": "Health NGO",
        "location": "Kabul",
        "url": "https://example.org/job",
        "apply_url": "https://example.org/apply",
        "description": "MD required. BPHS EPHS IMAM HMIS required. Apply at https://example.org/apply. Deadline: 2026-10-10.",
        "metadata": {},
    }
    profile = {
        "personal": {"first_name": "A", "last_name": "Doctor"},
        "medical_education": [{"degree": "MD"}],
        "skills": {"public_health": ["BPHS/EPHS & IMAM/CMAM Program Knowledge", "BPHS", "EPHS", "IMAM", "HMIS"]},
        "languages": [{"name": "Dari"}],
    }
    report = match_job_against_profile(job, profile).to_dict()
    docs = generate_tailored_documents(job, profile, report)
    core_line = next(line for line in docs["tailored_cv_text"].splitlines() if line.startswith("- "))
    assert "BPHS/EPHS & IMAM/CMAM Program Knowledge, BPHS" not in core_line
    assert "BPHS/EPHS & IMAM/CMAM Program Knowledge, EPHS" not in core_line


def test_email_application_package_includes_complete_draft_and_checklists():
    job = {
        "id": "email-ready",
        "title": "TSFP Project Supervisor",
        "company": "HealthNet TPO",
        "location": "Kunar",
        "url": "https://www.acbar.org/en/jobs/details/145882/tsfp-project-supervisor",
        "apply_url": "mailto:recruitment.kabul@hntpo.org",
        "description": "Send CV and application letter to recruitment.kabul@hntpo.org. Mention the position in the subject line. Deadline: 2026-10-10.",
        "metadata": {
            "source_url": "https://www.acbar.org/en/jobs/details/145882/tsfp-project-supervisor",
            "required_documents": ["Tailored CV", "Tailored cover letter", "HealthNet TPO application form"],
            "special_instructions": ["Mention the position in the email subject line"],
        },
    }
    profile = {
        "personal": {"first_name": "Allah Yar", "last_name": "Frotan", "email": "alfrotan@example.org", "phone": "+93 700 000 000", "location": "Kabul"},
        "medical_education": [{"degree": "MD", "institution": "Kabul Medical Science University"}],
        "license_registration": {"verified": True, "status": "Verified — holds valid medical professional registration/license", "number": ""},
        "languages": [{"name": "Dari"}, {"name": "English"}],
    }
    match_report = {
        "facts": {
            "source_url": job["url"],
            "application_email": "recruitment.kabul@hntpo.org",
            "application_subject": "TSFP Project Supervisor",
            "application_subject_required": True,
            "closing_date": "2026-10-10",
        },
        "requirement_matches": [],
    }
    docs = {"suggested_subject": "TSFP Project Supervisor"}
    package = generate_application_package(
        job,
        profile,
        match_report,
        docs,
        generated_paths={"tailored_cv": "cv.txt", "cover_letter": "cover.txt"},
    )
    assert package["package_status"] == "READY_TO_SEND"
    assert package["route_type"] == "email"
    assert package["email_draft"]["to"] == "recruitment.kabul@hntpo.org"
    assert package["email_draft"]["subject"] == "TSFP Project Supervisor"
    assert "Dear Hiring Committee" in package["email_draft"]["body"]
    assert "cv.txt" in package["email_draft"]["attachments"]
    assert "cover.txt" in package["email_draft"]["attachments"]
    assert package["source_url"] == job["url"]
    assert package["deadline"] == "2026-10-10"
    assert "license number:" not in package["text"].lower()


def test_online_application_package_includes_form_url_fields_and_no_submission():
    job = {
        "id": "form-ready",
        "title": "Medical Officer",
        "company": "FMIC",
        "location": "Kabul",
        "url": "https://www.acbar.org/en/jobs/details/145774/medical-officer",
        "apply_url": "https://docs.google.com/forms/d/example/edit",
        "description": "Apply through the online form. Validated copies of academic certificates/diplomas will be requested only if selected. Deadline: 2026-10-05.",
        "metadata": {
            "source_url": "https://www.acbar.org/en/jobs/details/145774/medical-officer",
            "required_documents": ["Resume/CV with specific qualification and experience dates", "Academic certificates/diplomas only if selected/requested"],
            "form_fields": ["Full name", "Phone", "Email", "Work history with dates", "CV upload"],
        },
    }
    profile = {
        "personal": {"first_name": "Allah Yar", "last_name": "Frotan", "email": "alfrotan@example.org", "phone": "+93 700 000 000", "location": "Kabul"},
        "medical_education": [{"degree": "MD"}],
        "license_registration": {"verified": True, "status": "Verified — holds valid medical professional registration/license", "number": ""},
    }
    match_report = {"facts": {"source_url": job["url"], "application_url": job["apply_url"], "closing_date": "2026-10-05"}, "requirement_matches": []}
    package = generate_application_package(job, profile, match_report, {"suggested_subject": "Medical Officer"})
    assert package["package_status"] == "READY_TO_SUBMIT"
    assert package["route_type"] == "online_form"
    assert package["online_application"]["url"] == "https://docs.google.com/forms/d/example/viewform"
    assert package["application_route"] == "https://docs.google.com/forms/d/example/viewform"
    assert any("/edit URL" in item for item in package["special_instructions"])
    assert "CV upload" in package["online_application"]["form_fields_checklist"]
    assert package["email_draft"] is None
    assert package["no_submission_performed"] is True
    assert any("CAPTCHA" in item for item in package["user_required_actions"])
    assert "license number:" not in package["text"].lower()


def test_email_application_package_blocks_send_when_required_external_form_missing():
    job = {
        "id": "email-blocked",
        "title": "Quality Officer",
        "company": "RI",
        "location": "Nimruz",
        "url": "https://example.org/job",
        "apply_url": "mailto:vacancies@example.org",
        "description": "Send RI application form with CV and three references. Subject line: REF-1.",
        "metadata": {
            "required_documents": ["RI application form", "CV", "Three references"],
            "form_fields": ["Father’s name", "Date of birth", "Tazkera number", "Three references"],
            "blocking_user_inputs": ["Completed employer application form", "Three approved reference contacts"],
        },
    }
    profile = {"personal": {"first_name": "Allah Yar", "last_name": "Frotan"}}
    report = {"facts": {"application_email": "vacancies@example.org", "application_subject": "REF-1", "application_subject_required": True}}
    package = generate_application_package(job, profile, report, {"suggested_subject": "REF-1"})
    assert package["package_status"] == "NEEDS_USER_INPUT"
    assert "Completed employer application form" in package["missing_items"]
    assert "Father’s name" in package["form_fields_checklist"]
    assert "Three references" in package["text"]
    assert any("Three approved reference contacts" in action for action in package["user_required_actions"])
