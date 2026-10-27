"""Employer artifacts must not leak internal review instructions or unverified PII."""

from __future__ import annotations

import pdfplumber
import pytest
from docx import Document

from tests.test_document_evidence_gate import _docs, _mixed_profile
from utils.document_design import render_professional_document_artifacts
from utils.documents import _write_text_docx_pdf, generate_application_package


def test_unverified_identity_is_omitted_but_application_remains_blocked(tmp_path):
    profile = _mixed_profile()
    profile["personal"]["verification"] = {}
    docs, report = _docs(profile)
    cv = docs["tailored_cv_text"]
    assert "CONFIRM BEFORE SUBMISSION" not in cv
    assert "Needs verification" not in cv
    assert "jane.real@clinic-example.af" not in cv
    assert "+93 70 123 4567" not in cv
    assert "Email:" not in cv
    assert "Phone:" not in cv

    package = generate_application_package(
        {"title": "Medical Doctor", "company": "Example Clinic"},
        profile, report, docs,
    )
    assert package["package_status"] == "NEEDS_USER_INPUT"
    assert any("Identity/contact details reviewed and confirmed" in m
               for m in package["missing_items"])

    artifacts = render_professional_document_artifacts(
        cv, tmp_path / "draft_cv", document_type="cv",
        canonical_cv_model=docs["tailored_cv_model"],
    )
    word = "\n".join(p.text for p in Document(artifacts["docx"]).paragraphs)
    with pdfplumber.open(artifacts["pdf"]) as pdf:
        pdf_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    for rendered in (word, pdf_text):
        assert "CONFIRM BEFORE SUBMISSION" not in rendered
        assert "Needs verification" not in rendered
        assert "jane.real@clinic-example.af" not in rendered
        assert "+93 70 123 4567" not in rendered


def test_unverified_medical_degree_never_inserts_review_instructions_into_cv():
    profile = {
        "personal": {"first_name": "Anonymous", "last_name": "Applicant", "verification": {}},
        "medical_education": [{"degree": "MD", "verified": False}],
        "work_history": [],
    }
    docs, _ = _docs(profile)
    cv = docs["tailored_cv_text"]
    assert "This CV is generated only" not in cv
    assert "Confirm the profile" not in cv
    assert "PROFESSIONAL SUMMARY" not in cv
    assert "CONFIRM BEFORE SUBMISSION" not in cv


def test_export_gate_rejects_internal_editing_text_without_creating_files(tmp_path):
    for phrase in ("CONFIRM BEFORE SUBMISSION", "To be completed", "Needs verification"):
        dest = tmp_path / "candidate_cv"
        with pytest.raises(ValueError, match="unfinished review field"):
            _write_text_docx_pdf(
                "Candidate Name\\nPROFESSIONAL SUMMARY\\n" + phrase,
                dest,
                document_type="cv",
            )
        assert list(tmp_path.iterdir()) == []
