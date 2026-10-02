"""The canonical evidence/verification contract.

Covers tri-state yes/no parsing, work-history years requiring per-entry
verification, skills/certificates never auto-verifying from plain presence,
and placeholder values never being treated as evidence.
"""

from datetime import date

from utils.profile import (
    ProfileEvidence,
    build_profile_evidence,
    infer_years_from_history,
    is_unresolved_value,
    is_verified_flag,
    parse_tristate,
)


def test_evidence_add_never_uses_truthiness_for_verification():
    """ProfileEvidence.add() must only treat a literal boolean True as
    verified -- "true"/"false"/1/"yes"/non-empty strings are all truthy in
    Python but must NEVER produce verified evidence.
    """
    for sneaky_value in ["true", "false", "yes", "no", 1, 0, "1", "0", "True", [True], {"ok": True}]:
        evidence = ProfileEvidence()
        evidence.add("some_key", "some_value", "test.source", "quote", verified=sneaky_value)
        assert not evidence.has_verified("some_key"), f"verified={sneaky_value!r} must not mark evidence verified"

    evidence = ProfileEvidence()
    evidence.add("some_key", "some_value", "test.source", "quote", verified=True)
    assert evidence.has_verified("some_key")


def test_evidence_add_verified_upgrade_requires_literal_true_not_truthy():
    """A later 'upgrade' add() call must also only upgrade on literal True."""
    evidence = ProfileEvidence()
    evidence.add("skill", "First Aid", "profile.skills", "First Aid", verified=False)
    evidence.add("skill", "First Aid", "profile.skills", "First Aid", verified="true")
    assert not evidence.has_verified("skill")
    evidence.add("skill", "First Aid", "profile.skills", "First Aid", verified=True)
    assert evidence.has_verified("skill")


def test_parse_tristate_never_coerces_placeholders_to_true():
    for placeholder in ["Needs verification", "Unknown", "Unconfirmed", "Pending", "", None, "maybe"]:
        assert parse_tristate(placeholder) is None


def test_parse_tristate_resolves_only_recognised_yes_no_tokens():
    assert parse_tristate("Yes") is True
    assert parse_tristate("yes") is True
    assert parse_tristate(True) is True
    assert parse_tristate("No") is False
    assert parse_tristate(False) is False


def test_is_verified_flag_only_true_for_literal_boolean_true():
    assert is_verified_flag(True) is True
    assert is_verified_flag("true") is False
    assert is_verified_flag("True") is False
    assert is_verified_flag(1) is False
    assert is_verified_flag(None) is False
    assert is_verified_flag("Needs verification") is False


def test_is_unresolved_value_catches_common_placeholders_without_truthiness():
    for placeholder in ["Needs verification", "Unknown", "unconfirmed", "Pending", "TBD", "N/A", "", None]:
        assert is_unresolved_value(placeholder) is True
    assert is_unresolved_value(False) is False
    assert is_unresolved_value(0) is False
    assert is_unresolved_value("Kabul") is False


def test_relocation_and_deployment_placeholders_never_become_evidence():
    profile = {
        "preferences": {
            "willing_to_relocate": "Needs verification",
            "field_deployment": "Unknown",
        }
    }
    evidence = build_profile_evidence(profile)
    assert not evidence.has("willing_to_relocate")
    assert not evidence.has("field_deployment")


def test_relocation_and_deployment_resolve_when_explicitly_answered():
    profile = {
        "preferences": {
            "willing_to_relocate": "Yes",
            "field_deployment": "No",
        }
    }
    evidence = build_profile_evidence(profile)
    assert evidence.has_verified("willing_to_relocate")
    assert evidence.verified_values("willing_to_relocate") == [True]
    assert evidence.has_verified("field_deployment")
    assert evidence.verified_values("field_deployment") == [False]


def test_work_history_years_require_explicit_per_entry_verification():
    profile = {
        "work_history": [
            {"title": "Medical Doctor", "start": "2020-01", "end": "2024-01", "description": "Clinical patient care"},
        ]
    }
    # Dates exist but the entry was never confirmed -- must not count.
    assert infer_years_from_history(profile, today=date(2026, 1, 1)) is None


def test_work_history_years_count_only_verified_entries():
    profile = {
        "work_history": [
            {"title": "Medical Doctor", "start": "2020-01", "end": "2024-01", "description": "Clinical patient care", "verified": True},
            {"title": "Medical Doctor", "start": "2024-01", "end": "2025-01", "description": "Clinical patient care", "verified": False},
        ]
    }
    years = infer_years_from_history(profile, today=date(2026, 1, 1))
    assert years is not None
    assert 3.9 <= years <= 4.1  # Only the verified 2020-2024 interval counts.


def test_plain_skill_strings_are_recorded_unverified():
    profile = {"skills": {"medical": ["Clinical care"]}}
    evidence = build_profile_evidence(profile)
    assert evidence.has("skills")
    assert not evidence.has_verified("skills")


def test_skill_dict_item_verifies_only_with_explicit_flag():
    profile = {"skills": [{"name": "Advanced Cardiac Life Support", "verified": True}, {"name": "Basic First Aid"}]}
    evidence = build_profile_evidence(profile)
    verified_names = evidence.verified_values("skills")
    assert "Advanced Cardiac Life Support" in verified_names
    assert "Basic First Aid" not in verified_names


def test_structured_education_evidence_never_leaks_internal_verified_flag_text():
    profile = {"medical_education": [{"degree": "MD", "institution": "Needs verification", "verified": True}]}
    evidence = build_profile_evidence(profile)
    quotes = evidence.evidence_text("md_degree")
    assert quotes
    for quote in quotes:
        assert "False" not in quote
        assert "True" not in quote
        assert "Needs verification" not in quote


def test_personal_identity_fields_require_explicit_personal_verification():
    """CV-derived identity/contact data (name, email, phone) must not become
    verified evidence just because it is present and non-placeholder --
    profile_builder.py extracts these directly from CV text with no verified
    flags, so they must stay unverified until the owner explicitly confirms
    each field (or the whole personal block).
    """
    profile = {
        "personal": {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane.doe@example.org",
            "phone": "+93700000000",
            "gender": "female",
            "nationality": "Afghan",
            "location": "Kabul",
        }
    }
    evidence = build_profile_evidence(profile)
    for key in ["first_name", "last_name", "email", "phone", "gender", "nationality", "location"]:
        assert evidence.has(key), f"{key} should still be recorded as (unverified) evidence"
        assert not evidence.has_verified(key), f"{key} must not be verified without an explicit confirmation"


def test_personal_identity_fields_verify_individually():
    profile = {
        "personal": {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane.doe@example.org",
            "gender": "female",
            "nationality": "Afghan",
            "location": "Kabul",
            "verification": {"gender": True, "email": True},
        }
    }
    evidence = build_profile_evidence(profile)
    assert evidence.has_verified("gender")
    assert evidence.has_verified("email")
    assert not evidence.has_verified("nationality")
    assert not evidence.has_verified("location")


def test_personal_identity_fields_verify_once_the_personal_block_is_confirmed():
    profile = {
        "personal": {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane.doe@example.org",
            "gender": "female",
            "nationality": "Afghan",
            "verified": True,
        }
    }
    evidence = build_profile_evidence(profile)
    for key in ["first_name", "last_name", "email", "gender", "nationality"]:
        assert evidence.has_verified(key)


def test_personal_verified_false_does_not_verify():
    profile = {"personal": {"gender": "male", "verified": False}}
    evidence = build_profile_evidence(profile)
    assert not evidence.has_verified("gender")
    profile2 = {"personal": {"gender": "male", "verified": "true"}}
    evidence2 = build_profile_evidence(profile2)
    assert not evidence2.has_verified("gender")
