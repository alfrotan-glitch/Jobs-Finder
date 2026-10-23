"""Browser-facing hardening regressions for the local dashboard.

The dashboard handles private applicant information and can change local state,
so its browser boundary must stay deliberately small: no cacheable profile
responses, no framing, no cross-origin state-changing browser requests, and no
unbounded CV upload buffering.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from dashboard import server
from utils import profile as profile_repository
from utils import tracker


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_repository, "CANONICAL_PROFILE_PATH", tmp_path / "profile.yaml")
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    return TestClient(server.app)


def test_dashboard_sets_private_browser_security_headers(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0, private"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "access-control-allow-origin" not in response.headers


def test_dashboard_does_not_expose_interactive_api_documentation(client):
    """The local app has no public API contract that requires Swagger UI."""
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_cross_origin_state_change_is_rejected_before_running_a_scan(client):
    response = client.post("/api/find", headers={"Origin": "https://untrusted.example"})

    assert response.status_code == 403
    assert "Cross-origin" in response.json()["detail"]


def test_same_origin_and_non_browser_posts_keep_existing_endpoint_behavior(client):
    same_origin = client.post("/api/find", headers={"Origin": "http://testserver"})
    no_origin = client.post("/api/find")

    # No canonical profile is present in this fixture.  Both requests reach the
    # endpoint and therefore fail for the existing, truthful reason rather than
    # being rejected as cross-origin requests.
    assert same_origin.status_code == 400
    assert no_origin.status_code == 400


def test_cv_preview_rejects_oversized_upload_without_parsing_or_persisting(client, monkeypatch):
    monkeypatch.setattr(server, "MAX_CV_UPLOAD_BYTES", 16)

    def must_not_parse(_: str):
        raise AssertionError("oversized upload must not be parsed")

    monkeypatch.setattr(server, "build_profile_from_cv_file", must_not_parse)
    response = client.post(
        "/api/import-cv",
        files={"file": ("cv.txt", io.BytesIO(b"x" * 17), "text/plain")},
    )

    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()
    assert not profile_repository.canonical_profile_path().exists()


def test_cv_preview_accepts_a_bounded_text_upload(client, monkeypatch):
    monkeypatch.setattr(server, "MAX_CV_UPLOAD_BYTES", 64)
    response = client.post(
        "/api/import-cv",
        files={"file": ("cv.txt", io.BytesIO(b"Amina Example\nEmail: amina@example.org\n"), "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["persisted"] is False
    assert not profile_repository.canonical_profile_path().exists()



def test_untrusted_host_cannot_read_private_dashboard_data(client):
    """A malicious DNS-rebinding domain must not reach local applicant APIs."""
    for hostname in ("attacker.example", "localhost.attacker.example", "127.0.0.1.attacker.example"):
        response = client.get("/api/profile/details", headers={"Host": hostname})
        assert response.status_code == 400
        assert "Untrusted Host" in response.json()["detail"]
        assert response.headers["cache-control"] == "no-store, max-age=0, private"


def test_trusted_host_supports_loopback_addresses_and_ipv6(client):
    for hostname in ("localhost:8080", "127.0.0.1:8080", "[::1]:8080"):
        response = client.get("/api/health", headers={"Host": hostname})
        assert response.status_code == 200


def test_malformed_host_headers_are_rejected(client):
    for hostname in ("localhost:invalid", "localhost@attacker.example", "localhost/path", "localhost:0"):
        response = client.get("/api/health", headers={"Host": hostname})
        assert response.status_code == 400


def test_confirm_endpoint_rejects_non_object_json_without_mutating_profile(client):
    """Malformed confirmation bodies should never raise 500 or alter evidence."""
    canonical = profile_repository.canonical_profile_path()
    canonical.write_text("personal:\n  first_name: Jane\n", encoding="utf-8")
    original = canonical.read_bytes()
    for payload in ([], ["personal:first_name"], "personal:first_name", 42, None):
        response = client.post("/api/profile/confirm", json=payload)
        assert response.status_code == 400
        assert canonical.read_bytes() == original


def test_duplicate_scan_request_is_rejected_without_starting_discovery(client, monkeypatch):
    """Do not run two overlapping dashboard scans against one saved latest scan."""
    import asyncio

    def should_not_run():
        raise AssertionError("discovery must not run while the scan lock is held")

    monkeypatch.setattr(server, "run_discovery_scan", should_not_run)

    async def during_scan():
        async with server._SCAN_LOCK:
            return client.post("/api/find")

    response = asyncio.run(during_scan())
    assert response.status_code == 409
    assert "already running" in response.json()["detail"]
