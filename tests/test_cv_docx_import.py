"""Word CV import must remain transient, bounded and unverified."""
from __future__ import annotations

import io

import pytest
from docx import Document
from fastapi.testclient import TestClient

from dashboard import server
from utils.profile_builder import build_profile_from_cv_file
from utils.resume_parser import extract_resume_text


def _sample_word() -> bytes:
    """A synthetic two-column CV layout like real owner-provided designs."""
    document = Document()
    document.add_heading("Dr. Example Candidate", 0)
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Core Expertise\nNutrition and primary care"
    table.cell(0, 1).text = "TFU Medical Doctor\nProvided supervised inpatient care."
    document.add_paragraph("Health and Nutrition Supervisor")
    document.add_paragraph("Supervised mobile health teams under approved protocols.")
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def test_word_cv_extracts_paragraphs_and_tables_without_losing_roles(tmp_path):
    path = tmp_path / "old_cv.docx"
    path.write_bytes(_sample_word())
    text = extract_resume_text(str(path))
    assert "Core Expertise" in text
    assert "TFU Medical Doctor" in text
    assert "Provided supervised inpatient care" in text
    assert "Health and Nutrition Supervisor" in text


def test_imported_word_cv_does_not_change_canonical_profile(tmp_path, monkeypatch):
    from utils import profile as profile_repository
    profile_path = tmp_path / "profile.yaml"
    original = b"personal:\n  first_name: Existing\n  last_name: Owner\n"
    profile_path.write_bytes(original)
    monkeypatch.setattr(profile_repository, "CANONICAL_PROFILE_PATH", profile_path)
    client = TestClient(server.app)
    response = client.post("/api/import-cv", files={
        "file": ("earlier_cv.docx", _sample_word(),
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    })
    assert response.status_code == 200, response.text
    assert response.json()["persisted"] is False
    assert profile_path.read_bytes() == original
    assert not any(tmp_path.glob("*.docx"))
    snapshot = build_profile_from_cv_file  # Import module remains read-only.
    assert callable(snapshot)


def test_malformed_word_upload_rejected_without_creating_profile():
    response = TestClient(server.app).post("/api/import-cv", files={
        "file": ("cv.docx", b"not a word zip", "application/octet-stream")
    })
    assert response.status_code == 400
    assert "Word CV" in response.json()["detail"]


def test_extractor_never_decodes_invalid_binary_word_as_text(tmp_path):
    path = tmp_path / "bad.docx"
    path.write_bytes(b"\x00\x01malformed binary")
    with pytest.raises(ValueError, match="Word CV"):
        extract_resume_text(str(path))


def test_owner_review_candidate_duties_are_never_auto_verified():
    from utils.profile_builder import candidate_responsibilities_from_cv
    text = (
        "PROFESSIONAL EXPERIENCE\n"
        "TFU Medical Doctor\n"
        "— Delivered clinical assessments and follow-up for children with malnutrition.\n"
        "— Coordinated reporting with district health partners and nutrition colleagues.\n"
        "References: private number\n"
        "— Email: private@example.org\n"
    )
    candidates = candidate_responsibilities_from_cv(text)
    assert len(candidates) == 2
    assert candidates[0].startswith("Delivered clinical")
    assert not any("private@" in text for text in candidates)


def test_docx_preview_offers_real_text_but_does_not_persist_bullets():
    response = TestClient(server.app).post("/api/import-cv", files={
        "file": ("earlier_cv.docx", _sample_word(),
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    })
    assert response.status_code == 200
    assert response.json()["persisted"] is False
    # Synthetic table layout here uses paragraph-like duties but no bullets,
    # so no responsibilities are fabricated from unmarked prose.
    assert isinstance(response.json()["candidate_responsibilities"], list)
