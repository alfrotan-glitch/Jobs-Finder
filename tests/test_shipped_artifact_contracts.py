"""Shipped-artifact contracts:

1. profile.yaml.example must never silently create verified credentials.
2. Dashboard terminology for NEEDS_VERIFICATION must not claim eligibility.
3. The Python version contract (README / launcher / CI) must be consistent
   and must not accept Python 3.13.
"""
import re
from pathlib import Path

import yaml


def test_profile_example_has_no_verified_true_data_fields():
    """Every literal ``verified: true`` in the shipped example file must be
    inside an explanatory comment (prose/sample), never a live YAML value --
    copying the file to profile.yaml must never produce verified credentials.
    """
    text = Path("profile.yaml.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "verified: true" not in stripped, f"live verified:true found: {line!r}"


def test_profile_example_parses_with_no_verified_claims():
    """Parse the example as real YAML (as a user would after `cp` it to
    profile.yaml) and assert nothing is pre-verified."""
    data = yaml.safe_load(Path("profile.yaml.example").read_text(encoding="utf-8"))

    assert all(flag is False for flag in data["personal"]["verification"].values())
    assert data["personal"]["first_name"] == ""
    assert data["personal"]["last_name"] == ""
    assert data["personal"]["email"] == ""
    assert data["medical_education"] == []
    assert data["license_registration"]["verified"] is False
    assert data["license_registration"]["status"] == "Needs verification"
    assert data["medical_exit_exam"]["verified"] is False
    assert data["medical_exit_exam"]["status"] == "Needs verification"
    assert data["skills"]["medical"] == []
    assert data["languages"] == []


def test_profile_example_has_no_fake_candidate_identity():
    text = Path("profile.yaml.example").read_text(encoding="utf-8")
    for token in ["Jane", "Doe", "applicant@example.org", "+93 00 000 0000", "Example Clinic"]:
        assert token not in text


def test_profile_example_has_no_acbar_scan_budget_keys():
    """Copying the shipped example must not configure ACBAR scan budgets."""
    text = Path("profile.yaml.example").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    acbar = ((data.get("job_sources") or {}).get("acbar") or {})

    assert "max_pages" not in text
    assert "detail_limit" not in text
    assert "max_pages" not in acbar
    assert "detail_limit" not in acbar


def test_dashboard_needs_verification_label_is_not_an_eligibility_claim():
    text = Path("dashboard/static/app.js").read_text(encoding="utf-8")
    assert "ELIGIBLE — VERIFY FIRST" not in text
    assert "ELIGIBLE - VERIFY FIRST" not in text

    match = re.search(r'if \(readiness === "NEEDS_VERIFICATION"\) return "([^"]+)"', text)
    assert match, "NEEDS_VERIFICATION label mapping not found in dashboard/static/app.js"
    label = match.group(1)
    assert label == "REQUIRES VERIFICATION"
    assert "ELIGIBLE" not in label.upper()


def test_python_version_contract_is_consistent_across_docs_and_ci():
    readme = Path("README.md").read_text(encoding="utf-8")
    ci = Path(".github/workflows/tests.yml").read_text(encoding="utf-8")
    launcher = Path("run_jobs_finder.bat").read_text(encoding="utf-8")

    assert "Python 3.11 and 3.12" in readme
    assert '"3.11", "3.12"' in ci or "'3.11', '3.12'" in ci
    assert "3.13" not in ci

    # The launcher must not mention 3.13 as a supported/bootstrap version.
    assert "3.13" not in launcher
    # Bootstrap probing must only accept 3.11 <= version < 3.13.
    assert launcher.count("(3, 11) <= sys.version_info[:2] < (3, 13)") >= 1
    assert "< (3, 14)" not in launcher
