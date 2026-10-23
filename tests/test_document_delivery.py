"""Document delivery: usable previews/downloads with strict local file boundaries.

The dashboard must expose *all* generated CV/letter formats safely. PDFs and
plain text open inline for review, while Word downloads remain editable.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard import server


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    document_root = tmp_path / "documents" / "applications"
    document_root.mkdir(parents=True)
    for ext, value in (
        ("pdf", b"%PDF-1.4\n"),
        ("txt", b"Verified experience only\n"),
        ("docx", b"word-binary"),
    ):
        (document_root / f"example.{ext}").write_bytes(value)
    return TestClient(server.app), document_root


@pytest.mark.parametrize(
    ("extension", "expected"),
    [
        ("pdf", "inline"),
        ("txt", "inline"),
        ("docx", "attachment"),
    ],
)
def test_generated_documents_have_usable_default_delivery(client, extension, expected):
    test_client, docs = client
    response = test_client.get("/api/generated-file", params={"path": str(docs / f"example.{extension}")})
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith(expected)
    assert response.headers["cache-control"] == "no-store, max-age=0, private"
    assert response.content == (docs / f"example.{extension}").read_bytes()


@pytest.mark.parametrize("extension", ["pdf", "txt", "docx"])
def test_explicit_download_displays_attachment_disposition(client, extension):
    test_client, docs = client
    response = test_client.get(
        "/api/generated-file",
        params={"path": str(docs / f"example.{extension}"), "download": "1"},
    )
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment")


def test_generated_document_delivery_rejects_escape_paths_and_unapproved_formats(client, tmp_path):
    test_client, docs = client
    secret = tmp_path / "secret.txt"
    secret.write_text("Not a generated document", encoding="utf-8")
    private = test_client.get("/api/generated-file", params={"path": str(secret)})
    assert private.status_code == 400
    assert "Only generated" in private.json()["detail"]

    json_file = docs / "application.json"
    json_file.write_text('{"secret":"no"}', encoding="utf-8")
    forbidden_type = test_client.get("/api/generated-file", params={"path": str(json_file)})
    assert forbidden_type.status_code == 400

    missing = test_client.get("/api/generated-file", params={"path": str(docs / "missing.pdf")})
    assert missing.status_code == 404


def test_symlinked_document_cannot_read_outside_local_documents(client, tmp_path):
    test_client, docs = client
    outside = tmp_path / "outside.txt"
    outside.write_text("private data", encoding="utf-8")
    alias = docs / "malicious.txt"
    try:
        alias.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is restricted on this platform.")
    response = test_client.get("/api/generated-file", params={"path": str(alias)})
    assert response.status_code == 400
    assert response.content != outside.read_bytes()


def test_document_dashboard_offers_every_format_and_review_notes():
    """Guard the public browser workflow without embedding any applicant facts."""
    from utils.paths import PROJECT_ROOT

    js = (PROJECT_ROOT / "dashboard" / "static" / "app.js").read_text(encoding="utf-8")
    assert "function documentBundleCard" in js
    assert "Preview PDF" in js and "Download PDF" in js
    assert "Download Word" in js and "View text" in js
    assert "applicationReviewNotes" in js
    assert "paths.application_data_checklist" in js
