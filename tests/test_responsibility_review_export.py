"""Owner review workflow for the responsibility drafts still held in profile.yaml.

These tests protect the *review output* the way the release suite protects the
generated documents:

* the review list presents every held draft verbatim — nothing paraphrased,
  strengthened, or invented;
* it never applies a decision: after preparing it, ``profile.yaml`` still holds
  every draft in ``needs_verification`` with ``verified: false``;
* producing it is strictly read-only: the canonical record is byte-identical
  before and after;
* the shipped document ``docs/held_responsibility_review.md`` is in sync with
  the canonical record, so the list cannot silently drift out of date;
* the archived pre-recovery 28-item review is frozen:
  the restoration rebuilt responsibilities from applicant evidence but never
  rewrote that historical record.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from tests.test_cv_professional_quality import (
    _applicant_supplied_facts,
    _verified_responsibilities,
)
from tools import export_responsibility_review as review

PROFILE_PATH = Path("profile.yaml")
REVIEW_DOC_PATH = Path("docs/held_responsibility_review.md")
HISTORICAL_REVIEW_PATH = Path("docs/archive/responsibility_review_28_items_pre_recovery.md")


def _profile() -> dict:
    return yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))


def _held_drafts(profile: dict) -> list[tuple[str, str]]:
    drafts: list[tuple[str, str]] = []
    for entry in profile["work_history"]:
        for item in entry.get("needs_verification") or []:
            drafts.append((str(entry["title"]), str(item["text"])))
    return drafts


def test_review_export_is_read_only_for_the_canonical_profile(tmp_path, monkeypatch):
    """Preparing the review list must not touch profile.yaml or apply a decision."""
    before = PROFILE_PATH.read_bytes()
    before_hash = review.canonical_profile_digest()

    target = tmp_path / "held_responsibility_review.md"
    monkeypatch.setattr(review, "REVIEW_DOC_PATH", target)
    assert review.main([]) == 0

    assert PROFILE_PATH.read_bytes() == before
    assert review.canonical_profile_digest() == before_hash
    assert target.exists()
    assert target.read_text(encoding="utf-8") == REVIEW_DOC_PATH.read_text(encoding="utf-8")

    # `--stdout-only` and `--verify-wording` write nothing at all.
    sentinel = tmp_path / "untouched.md"
    monkeypatch.setattr(review, "REVIEW_DOC_PATH", sentinel)
    assert review.main(["--stdout-only"]) == 0
    assert review.main(["--verify-wording", "supervised mobile health and nutrition teams"]) == 0
    assert not sentinel.exists()


def test_review_lists_every_held_draft_verbatim():
    profile = _profile()
    items = review.collect_review_items(profile)
    drafts = _held_drafts(profile)

    assert len(items) == len(drafts)
    assert len(items) == 24, len(items)
    assert len({item["role_index"] for item in items}) == 5
    assert [item["number"] for item in items] == list(range(1, len(items) + 1))

    for item, (role, draft) in zip(items, drafts):
        assert item["title"] == role
        assert item["draft"] == draft, item["number"]
        assert draft.startswith(item["draft"][:60])
        assert item["reason"]
        assert item["action"] in review.ACTIONS
        assert item["basis"], item["number"]  # why it is held is always recorded
        assert item["evidence_status"] in {"NOT_SUPPORTED", "PARTIALLY_SUPPORTED", "UNCLASSIFIED"}


def test_review_reports_the_canonical_basis_and_anchors_for_every_item():
    profile = _profile()
    items = review.collect_review_items(profile)

    for item in items:
        # The applicant-supported responsibilities already in force are presented.
        assert item["verified_responsibilities"], item["number"]
        role_scope = set(_verified_responsibilities(profile["work_history"][item["role_index"]]))
        for responsibility in item["verified_responsibilities"]:
            assert responsibility["text"] in role_scope
        # The held reason is the canonical field, not prose authored for the review.
        held = profile["work_history"][item["role_index"]]["needs_verification"]
        assert item["status"] == "NEEDS_VERIFICATION"
        assert item["basis"] in {entry["basis"] for entry in held}
        # Every adjacent evidence label is a real verified item in the profile.
        verified_labels = {label for label, _tokens in review._verified_inventory(profile)}
        for adjacent in item["adjacent"]:
            assert adjacent["label"] in verified_labels
            assert adjacent["shared"]
        # Unanchored words never include the applicant's own supplied tokens.
        facts = _applicant_supplied_facts(profile)
        assert not (set(item["unanchored"]) & facts), (item["number"], sorted(set(item["unanchored"]) & facts))


def test_every_held_draft_is_still_excluded_from_the_canonical_evidence():
    """A held draft is never promoted to an applicant fact or a verified line."""
    profile = _profile()
    facts = _applicant_supplied_facts(profile)
    _supplied, unanchored_duty_terms = review._guard_helpers()

    for item in review.collect_review_items(profile):
        assert item["evidence_status"] != "UNCLASSIFIED", item["number"]
        # Either the guard rejects the vocabulary, or the canonical record still
        # marks the claim unsupported -- never plain "supported".
        assert item["blockers"] or item["evidence_status"] in {"NOT_SUPPORTED", "PARTIALLY_SUPPORTED"}
        assert unanchored_duty_terms(item["draft"], facts) or item["unanchored"], item["number"]

    text = REVIEW_DOC_PATH.read_text(encoding="utf-8")
    assert "Held responsibility review" in text
    assert "| **CONFIRM** |" in text
    assert "| **EDIT** |" in text
    assert "| **DISCARD** |" in text
    assert "the guard checks " in text


def test_no_decision_has_been_applied_to_the_canonical_profile():
    """Preparing a review list is not a decision: the gate is untouched."""
    raw = PROFILE_PATH.read_text(encoding="utf-8")
    profile = yaml.safe_load(raw)

    assert "needs_verification:" in raw
    for entry in profile["work_history"]:
        assert entry["verified"] is True
        held = entry.get("needs_verification") or []
        assert held, entry["title"]
        for item in held:
            assert item["verified"] is False
            assert item["status"] == "NEEDS_VERIFICATION"
        assert _verified_responsibilities(entry), entry["title"]

    assert len(_held_drafts(profile)) == 24
    # The review workflow never writes the record, so the hash still matches the
    # one the shipped document was generated from.
    digest = review.canonical_profile_digest()
    assert digest in REVIEW_DOC_PATH.read_text(encoding="utf-8")


def test_committed_review_document_is_in_sync_with_the_canonical_record():
    profile = _profile()
    items = review.collect_review_items(profile)
    digest = review.canonical_profile_digest()
    assert REVIEW_DOC_PATH.read_text(encoding="utf-8") == review.render_markdown(profile, digest, items)


def test_pre_recovery_28_item_review_is_preserved_unchanged():
    """The approved 28-item review is a frozen record, not a live view."""
    text = HISTORICAL_REVIEW_PATH.read_text(encoding="utf-8")

    assert text.count("| 28 |") == 1
    assert text.count("#### ") == 28
    assert "Responsibility review — 28 held duty drafts" in text
    # It still documents the state it was prepared from, including its digest.
    assert "7228c4a296deffbe846af35bf72504c35c1f10c31b14c62c368e74f1d1bd5f4d" in text
    # Its 28 drafts are the ones the restoration started from.
    assert "7228c4a2" in text


def test_review_document_lists_every_draft_and_carries_no_contact_pii():
    profile = _profile()
    text = REVIEW_DOC_PATH.read_text(encoding="utf-8")

    for _role, draft in _held_drafts(profile):
        assert draft in text
    assert str(profile["personal"]["email"]) not in text
    assert str(profile["personal"]["phone"]) not in text
    assert "private_reference" not in text
