"""Profile showcase and applicant-facing letter coherence regressions.

Presentation cannot invent or expose unverified employer-facing claims; the
dashboard and Master CV should describe the same verified career.
"""

from __future__ import annotations

from copy import deepcopy

from dashboard.server import _profile_details
from utils.documents import generate_master_cv, generate_tailored_documents
from utils.profile import load_canonical_profile


def test_profile_uses_real_verified_master_cv_summary_when_no_override():
    profile = load_canonical_profile(required=True)
    showcase = _profile_details(profile)
    master = generate_master_cv(profile)
    assert showcase["professional_summary"] == master["master_cv_model"]["profile"]
    assert "Medical Doctor" in showcase["professional_summary"]
    assert "No professional summary available" not in showcase["professional_summary"]


def test_unverified_owner_summary_never_enters_profile_showcase():
    profile = load_canonical_profile(required=True)
    baseline = _profile_details(profile)["professional_summary"]
    draft = deepcopy(profile)
    draft["professional_summary"] = {
        "text": "UNVERIFIED PRIVATE DRAFT: claimed responsibility for everything",
        "verified": False,
    }
    assert _profile_details(draft)["professional_summary"] != draft["professional_summary"]["text"]
    assert "Medical Doctor" in _profile_details(draft)["professional_summary"]
    assert "UNVERIFIED PRIVATE DRAFT" not in _profile_details(draft)["professional_summary"]


def test_verified_owner_cv_summary_is_not_copied_in_third_person_to_cover_letter():
    profile = load_canonical_profile(required=True)
    tailored_profile = deepcopy(profile)
    tailored_profile["professional_summary"] = {
        "text": "A medical professional with a distinguished verified background.",
        "verified": True,
    }
    job = {
        "id": "demo-role",
        "title": "Medical Doctor",
        "company": "Example NGO",
        "location": "Kabul",
        "description": "Clinical care and health reporting",
        "metadata": {},
    }
    package = generate_tailored_documents(job, tailored_profile, {"facts": {}})
    assert package["tailored_cv_model"]["profile"] == tailored_profile["professional_summary"]["text"]
    letter = package["cover_letter"]
    assert tailored_profile["professional_summary"]["text"] not in letter
    assert "I am a Medical Doctor" in letter
    assert "Relevant verified qualifications and professional strengths" in letter
