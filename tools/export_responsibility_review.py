"""Export the responsibility drafts still held in ``profile.yaml`` for owner review.

This is a **read-only review tool**. It never writes ``profile.yaml``, never
moves a line into ``responsibilities``, and never sets a verification flag. Its
only output is a human-readable decision list (``docs/held_responsibility_review.md``
by default) plus a numbered table on stdout.

What changed after the evidence-recovery audit
----------------------------------------------
The first version of this tool listed 28 drafts that no applicant evidence was
thought to cover, against a normalized profile that had lost the applicant's
own CV material. The recovery audit rebuilt those responsibilities from the
applicant-supplied CV (``docs/evidence_recovery_audit.md``, section 6), so the tool now lists
only the drafts that remain genuinely unsupported -- and it reads them, and
their status, straight out of the canonical record instead of a hardcoded table.

For every held draft it shows:

* the draft wording, byte-for-byte as it stands in ``profile.yaml``;
* why it is still held (the canonical ``basis``/``status`` fields);
* which portion of it, if any, was restored into a verified responsibility
  (the canonical ``restored_portion`` field);
* the applicant-supported responsibilities already recorded for the role;
* the *adjacent* verified evidence (skills, certificates, experience
  dimensions) the draft's vocabulary touches -- with the standing rule that a
  competency or a certificate never establishes that a duty was performed;
* the wording that no supplied fact and no verified item anchors;
* whether the draft could be confirmed **verbatim** -- measured with the same
  guard the release suite uses (``tests/test_cv_professional_quality.py``);
* the recommended action (CONFIRM / EDIT / DISCARD) and its reason.

The recommended action is advisory and derived from the canonical record: a
claim the audit marked NOT_SUPPORTED is recommended for DISCARD, and the
unsupported remainder of a partly-supported draft is recommended for EDIT
(only if the owner personally did it, in the owner's own words).

Usage::

    python tools/export_responsibility_review.py                  # print + refresh the document
    python tools/export_responsibility_review.py --stdout-only    # print only (writes nothing)
    python tools/export_responsibility_review.py --check          # fail if the document is stale
    python tools/export_responsibility_review.py --verify-wording "candidate line"

Requires ``pyyaml`` and the test dependencies (the guard vocabulary lives in the
release suite so the review list and the release agree by construction).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = PROJECT_ROOT / "profile.yaml"
REVIEW_DOC_PATH = PROJECT_ROOT / "docs" / "held_responsibility_review.md"

#: The frozen 28-item review prepared before the evidence-recovery audit. It is
#: a historical record of what was held and why; it is never regenerated.
ARCHIVE_DIR = PROJECT_ROOT / "docs" / "archive"
HISTORICAL_REVIEW_PATH = ARCHIVE_DIR / "responsibility_review_28_items_pre_recovery.md"

ACTIONS = ("CONFIRM", "DISCARD", "EDIT")

#: Achievement verbs the release suite forbids in a verified responsibility line.
ACHIEVEMENT_CLAIMS = (
    "increased", "reduced", "improved", "exceeded", "achieved", "awarded", "recognized",
    "recognised", "doubled", "tripled", "saved", "secured", "won", "ranked", "accredited",
    "certified by", "promoted",
)

#: Words that carry no claim on their own. They are excluded from the
#: "not anchored" column so it lists only content words.
FUNCTION_WORDS = {
    "a", "across", "all", "also", "an", "and", "any", "are", "as", "at", "be", "been",
    "between", "both", "by", "day", "each", "etc", "for", "from", "how", "in", "including",
    "into", "is", "it", "its", "no", "not", "of", "on", "only", "or", "out", "over", "own",
    "part", "same", "so", "such", "than", "that", "the", "their", "then", "there", "these",
    "this", "those", "through", "to", "up", "was", "were", "when", "where", "which", "while",
    "who", "whom", "why", "with", "within",
}

#: Overlap words too generic to be evidence of anything. An "adjacent evidence"
#: row whose only shared words are in this set is dropped from the review list so
#: the column shows real domain overlap (e.g. "MoPH", "IPC") rather than words
#: like "support" that every competency inventory contains.
GENERIC_OVERLAP_WORDS = {
    "activity", "activities", "field", "management", "planning", "review", "service",
    "services", "support", "training",
}


class ReviewError(RuntimeError):
    """The review list cannot be produced from the current canonical record."""


def _guard_helpers():
    """Import the release suite's own guard vocabulary and helpers.

    The review list is graded by the shipped guard, not by a copy of it, so the
    review and the release can never disagree about what is paste-eligible.
    """
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from tests.test_cv_professional_quality import (
        _applicant_supplied_facts,
        _unanchored_duty_terms,
    )

    return _applicant_supplied_facts, _unanchored_duty_terms


def _tokens(text: Any) -> set[str]:
    return {part for part in re.split(r"[^a-z0-9]+", str(text).lower()) if part}


def _read_profile() -> tuple[dict[str, Any], str]:
    import yaml

    raw = PROFILE_PATH.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        profile = yaml.safe_load(raw.decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise ReviewError(f"profile.yaml is not readable YAML: {exc}") from exc
    if not isinstance(profile, dict) or not profile.get("work_history"):
        raise ReviewError("profile.yaml has no work_history")
    return profile, digest


def _verified_inventory(profile: dict[str, Any]) -> list[tuple[str, set[str]]]:
    """Verified skills, certificates and experience dimensions, as (label, tokens)."""
    inventory: list[tuple[str, set[str]]] = []
    for items in (profile.get("skills") or {}).values():
        for item in items or []:
            if isinstance(item, dict) and item.get("verified") is True and item.get("name"):
                inventory.append((f"skill: {item['name']}", _tokens(item["name"])))
    for item in profile.get("certificates") or []:
        if isinstance(item, dict) and item.get("verified") is True and item.get("name"):
            inventory.append((f"certificate: {item['name']}", _tokens(item["name"])))
    for key, value in (profile.get("experience_evidence") or {}).items():
        if isinstance(value, dict) and value.get("verified") is True and value.get("status"):
            inventory.append((f"experience area: {key}", _tokens(value["status"]) | _tokens(key)))
    return inventory


def evidence_status(basis: str) -> str:
    """The canonical evidence status recorded on a held draft."""
    if "NOT_SUPPORTED" in basis:
        return "NOT_SUPPORTED"
    if "PARTIALLY_SUPPORTED" in basis:
        return "PARTIALLY_SUPPORTED"
    return "UNCLASSIFIED"


def _recommendation(item: dict[str, Any]) -> tuple[str, str]:
    """Advisory action derived from the canonical record, not from a side table."""
    basis = str(item.get("basis") or "")
    restored = str(item.get("restored_portion") or "")
    if "NOT_SUPPORTED" in basis:
        return (
            "DISCARD",
            (
                "No applicant-supplied evidence anywhere in the record covers this claim. It is a system "
                "inference about how the job is typically performed; recommend rejecting it unless you "
                "personally did exactly this."
            ),
        )
    if "PARTIALLY_SUPPORTED" in basis:
        reason = (
            "Only part of this draft is applicant evidence, and that part is already restored as a "
            "verified responsibility"
        )
        reason += f" ({restored})." if restored else "."
        reason += (
            " The wording above is the unsupported remainder: keep it only if you personally did it, "
            "and author the wording yourself."
        )
        return "EDIT", reason
    return (
        "EDIT",
        (
            "The canonical record does not mark this draft as supported. Keep it only if you personally "
            "did it, and author the wording yourself."
        ),
    )


def collect_review_items(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Every held draft, with the factual context and the advisory action."""
    supplied_facts, unanchored_duty_terms = _guard_helpers()
    facts = supplied_facts(profile)
    inventory = _verified_inventory(profile)

    items: list[dict[str, Any]] = []
    number = 0
    for role_index, entry in enumerate(profile.get("work_history") or []):
        if not isinstance(entry, dict):
            continue
        verified_responsibilities = [
            {"text": item["text"], "basis": item.get("basis", "")}
            for item in entry.get("responsibilities") or []
            if isinstance(item, dict) and item.get("verified") is True and item.get("text")
        ]
        for held in entry.get("needs_verification") or []:
            if not isinstance(held, dict):
                continue
            draft = str(held.get("text") or "")
            if not draft:
                continue
            number += 1
            draft_tokens = _tokens(draft)

            adjacent: list[dict[str, Any]] = []
            for label, inventory_tokens in inventory:
                shared = sorted((draft_tokens & inventory_tokens) - facts)
                if shared and not set(shared) <= GENERIC_OVERLAP_WORDS:
                    adjacent.append({"label": label, "shared": shared})
            adjacent.sort(key=lambda entry: (-len(entry["shared"]), entry["label"]))

            anchored = {token for item in adjacent for token in item["shared"]}
            unanchored = sorted(
                token
                for token in draft_tokens - facts
                if token not in anchored and token not in FUNCTION_WORDS and not token.isdigit()
            )

            duty_flags = sorted(unanchored_duty_terms(draft, facts))
            entity_flags = _unrecognised_entities(draft, facts)
            digits = bool(re.search(r"\d", re.sub(r"COVID-?19", "COVID", draft, flags=re.IGNORECASE)))
            achievement_flags = [
                claim for claim in ACHIEVEMENT_CLAIMS if re.search(rf"\b{claim}\b", draft, flags=re.IGNORECASE)
            ]
            blockers: list[str] = []
            if duty_flags:
                blockers.append("unsupported duty terms: " + ", ".join(duty_flags))
            if entity_flags:
                blockers.append("unnamed entities: " + ", ".join(entity_flags))
            if digits:
                blockers.append("numeric precision")
            if achievement_flags:
                blockers.append("achievement claims: " + ", ".join(achievement_flags))

            action, reason = _recommendation(held)
            status = evidence_status(str(held.get("basis") or ""))
            items.append(
                {
                    "number": number,
                    "role_index": role_index,
                    "title": str(entry.get("title") or ""),
                    "organization": str(entry.get("organization") or ""),
                    "location": str(entry.get("location") or ""),
                    "dates": _supplied_dates(entry),
                    "draft": draft,
                    "status": str(held.get("status") or ""),
                    "basis": str(held.get("basis") or ""),
                    "restored_portion": str(held.get("restored_portion") or ""),
                    "verified_responsibilities": verified_responsibilities,
                    "adjacent": adjacent,
                    "unanchored": unanchored,
                    "blockers": blockers,
                    "paste_eligible": not blockers,
                    "evidence_status": status,
                    "action": action,
                    "reason": reason,
                }
            )
    return items


def _unrecognised_entities(draft: str, facts: set[str]) -> list[str]:
    """Capitalised tokens whose words are not applicant-supplied (release guard)."""
    flagged: list[str] = []
    for index, token in enumerate(re.findall(r"[A-Za-z][A-Za-z&/'-]{2,}", draft)):
        if index == 0:
            continue
        if token[0].isupper():
            parts = [part for part in re.split(r"[^a-z0-9]+", token.lower()) if part]
            if not all(part in facts for part in parts):
                flagged.append(token)
    return sorted(set(flagged))


def _display_path(path: Path) -> str:
    """Path for messages: repository-relative when it is inside the repository."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _supplied_dates(entry: dict[str, Any]) -> str:
    start = str(entry.get("start") or "")
    end = str(entry.get("end") or "")
    if start and end:
        return f"{start} to {end}"
    if start or end:
        return start or end
    return "not supplied (kept blank)"


def _role_heading(items: list[dict[str, Any]]) -> str:
    first = items[0]
    parts = [first["title"]]
    if first["organization"]:
        parts.append(first["organization"])
    if first["location"]:
        parts.append(first["location"])
    return " | ".join(parts)


def render_markdown(profile: dict[str, Any], digest: str, items: list[dict[str, Any]]) -> str:
    counts = {action: sum(1 for item in items if item["action"] == action) for action in ACTIONS}
    paste_eligible = [item["number"] for item in items if item["paste_eligible"]]
    roles = len({item["role_index"] for item in items})
    restored = sum(1 for item in items if item["restored_portion"])
    verified_total = sum(
        len([r for r in entry.get("responsibilities") or [] if isinstance(r, dict) and r.get("verified") is True])
        for entry in profile.get("work_history") or []
        if isinstance(entry, dict)
    )

    lines: list[str] = []
    add = lines.append
    add("# Held responsibility review — drafts still awaiting owner confirmation")
    add("")
    add("<!-- Generated by tools/export_responsibility_review.py. Do not edit by hand. -->")
    add("")
    add(
        "Read-only owner review list. Nothing here has been applied: every line below is still held in "
        "`needs_verification` with `verified: false`, and generating this document does not modify "
        "`profile.yaml`."
    )
    add("")
    add(f"* Source record: `profile.yaml` — sha256 `{digest}`")
    add(f"* Held drafts: **{len(items)}** across **{roles}** roles")
    add(f"* Verified responsibilities already in force: **{verified_total}**")
    add(
        f"* Held drafts whose supported portion is already restored: **{restored}** "
        "(their unsupported remainder is what remains below)"
    )
    add(
        "* Recommended actions: "
        + ", ".join(f"**{action} {counts[action]}**" for action in ACTIONS)
        + " (advisory; the owner decides)"
    )
    add(
        "* Clean under the release guard's vocabulary check (not evidence): "
        + (f"**{len(paste_eligible)}**" if paste_eligible else "**none**")
        + "."
    )
    add(
        "* Every draft below is still marked unsupported by the canonical record: the guard checks "
        "vocabulary (no unnumbered duty term, no unnamed entity), not whether the applicant supplied "
        "the claim. Evidence status is what decides the recommendation."
    )
    add("")
    add(

            "This is the single authoritative review list. The superseded pre-recovery 28-item review "
            "is archived, byte-for-byte, as "
            "`docs/archive/responsibility_review_28_items_pre_recovery.md` -- it records the state "
            "before the applicant's own CV evidence was recovered, so it is history, not a second "
            "list to action. The restoration itself is recorded in `docs/evidence_recovery_audit.md`, "
            "section 6."

    )
    add("")
    add("## How to read this list")
    add("")
    add(
        "`responsibilities` is verification-gated: only `{text: ..., verified: true}` is applicant "
        "experience, and `needs_verification` is excluded from every generated document (Master CV, "
        "tailored CV, cover letter, package text and email). A role title, a skill, a certificate, or "
        "the sector's normal practice is **not** evidence that a duty was performed — that is why these "
        "lines are still held after the applicant's own CV evidence was fully recovered."
    )
    add("")
    add("| Action | Meaning |")
    add("| --- | --- |")
    add(
        "| **CONFIRM** | The draft asserts nothing beyond the role you already record. Confirming it "
        "needs nothing more than your own attestation. The wording must still be yours: no draft here "
        "is paste-eligible. |"
    )
    add(
        "| **EDIT** | Part of the draft is already applicant evidence (and already restored as a "
        "verified responsibility); the wording above is the remainder. Keep it only if you personally "
        "did it, and author the wording yourself. |"
    )
    add(
        "| **DISCARD** | The draft's claim is named by no supplied fact and no verified item anywhere in "
        "the record. Recommend rejecting it unless you personally did exactly that. |"
    )
    add("")
    add("## Held drafts")
    add("")
    add("| # | Role | Draft wording (verbatim) | Evidence status | Recommended action |")
    add("| --- | --- | --- | --- | --- |")
    for item in items:
        draft = item["draft"].replace("|", "\\|")
        add(
            f"| {item['number']} | {item['title']} | {draft} | {item['evidence_status']} | "
            f"{item['action']} |"
        )
    add("")
    add("## Item detail")
    add("")

    current_role = None
    for item in items:
        if item["role_index"] != current_role:
            current_role = item["role_index"]
            role_items = [entry for entry in items if entry["role_index"] == current_role]
            add(f"### Role {current_role + 1} — {_role_heading(role_items)}")
            add("")
            add(f"* Supplied dates: {role_items[0]['dates']}")
            add(
                "* Applicant-supported responsibilities already in force: "
                f"{len(role_items[0]['verified_responsibilities'])}"
            )
            add("")
        add(
            f"#### {item['number']}. {item['title']} — evidence status: **{item['evidence_status']}** "
            f"— recommended action: **{item['action']}**"
        )
        add("")
        add(f"* **Draft wording (verbatim):** {item['draft']}")
        add(
            "* **Why it is still held:** "
            + (f"`{item['status']}`" if item["status"] else "held back from documents")
            + (f" — {item['basis']}" if item["basis"] else "")
        )
        if item["restored_portion"]:
            add(f"* **Already restored from this draft:** {item['restored_portion']}")
        add("* **Applicant-supported responsibilities already in force for this role:**")
        for responsibility in item["verified_responsibilities"]:
            add(f"  * {responsibility['text']}")
        if item["adjacent"]:
            add(
                "* **Adjacent verified evidence (does NOT by itself establish that this duty was performed):**"
            )
            for adjacent in item["adjacent"]:
                add(f"  * {adjacent['label']} — shares: {', '.join(adjacent['shared'])}")
        else:
            add(
                "* **Adjacent verified evidence:** none — no verified skill, certificate or experience "
                "area shares this draft's vocabulary."
            )
        add(
            "* **Not anchored in your record:** "
            + (", ".join(item["unanchored"]) if item["unanchored"] else "none — only role facts and generic wording")
        )
        if item["paste_eligible"]:
            add(
                "* **Release guard:** clean on vocabulary — but that is not evidence, and the canonical "
                "record still marks this claim unsupported. Confirming it needs your own attestation."
            )
        else:
            add("* **Release guard:** **would reject this line** — " + "; ".join(item["blockers"]))
        add(f"* **Recommended action:** **{item['action']}** — {item['reason']}")
        add("* **Owner decision:** ☐ CONFIRM   ☐ EDIT   ☐ DISCARD   Notes: ____________________")
        add("")

    add("## What happens next (not performed by this tool)")
    add("")
    add(
        "1. Decide each line: CONFIRM (it is your experience), EDIT (keep the substance in your own "
        "words), or DISCARD (reject the inference)."
    )
    add(
        "2. `profile.yaml` changes only when you make them. A confirmed line becomes applicant experience "
        "only when you move `{text: <your wording>, verified: true}` into that role's `responsibilities`; "
        "discarded lines can be deleted from `needs_verification` in the same edit."
    )
    add(
        "3. Check any candidate wording before you record it: "
        "`python tools/export_responsibility_review.py --verify-wording \"your wording\"` (read-only)."
    )
    add("4. Re-run the suite: `python -m pytest -q`.")
    add("")
    add(
        "_This list is a presentation of the canonical record. It does not modify `profile.yaml`, it does "
        "not merge or release anything, and it does not apply a decision on your behalf._"
    )
    add("")
    return "\n".join(lines)


def render_stdout_table(items: list[dict[str, Any]]) -> str:
    lines = [
        "Held responsibility review — drafts awaiting owner confirmation (read-only; no decision applied)",
        "",
    ]
    for item in items:
        lines.append(
            f"[{item['number']:>2}] {item['title']} — {item['evidence_status']} — {item['action']}"
        )
        lines.append(f"     draft: {item['draft']}")
        lines.append(f"     held:  {item['basis'] or item['status']}")
        if item["restored_portion"]:
            lines.append(f"     already restored: {item['restored_portion']}")
        anchors = "; ".join(a["label"] for a in item["adjacent"]) or "none"
        lines.append(f"     adjacent verified evidence (cannot establish the duty): {anchors}")
        lines.append(
            "     not anchored: " + (", ".join(item["unanchored"]) if item["unanchored"] else "none")
        )
        lines.append(
            "     release guard: " + ("clean on vocabulary" if item["paste_eligible"] else "would reject this line")
        )
        lines.append(f"     action: {item['action']} — {item['reason']}")
        lines.append("")
    counts = {action: sum(1 for item in items if item["action"] == action) for action in ACTIONS}
    lines.append(
        "Summary: "
        + ", ".join(f"{action}={counts[action]}" for action in ACTIONS)
        + f", guard-clean={sum(1 for item in items if item['paste_eligible'])}"
    )
    return "\n".join(lines)


def verify_wording(text: str, profile: dict[str, Any]) -> list[str]:
    """Grade a candidate responsibility line with the release guard (read-only)."""
    supplied_facts, unanchored_duty_terms = _guard_helpers()
    facts = supplied_facts(profile)
    findings: list[str] = []
    duty = sorted(unanchored_duty_terms(text, facts))
    if duty:
        findings.append("unsupported duty terms: " + ", ".join(duty))
    entities = _unrecognised_entities(text, facts)
    if entities:
        findings.append("unnamed entities: " + ", ".join(entities))
    if re.search(r"\d", re.sub(r"COVID-?19", "COVID", text, flags=re.IGNORECASE)):
        findings.append("numeric precision")
    achievement = [
        claim for claim in ACHIEVEMENT_CLAIMS if re.search(rf"\b{claim}\b", text, flags=re.IGNORECASE)
    ]
    if achievement:
        findings.append("achievement claims: " + ", ".join(achievement))
    if "  " in text:
        findings.append("double space")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stdout-only", action="store_true", help="print the table and write nothing")
    parser.add_argument("--check", action="store_true", help="exit non-zero if the document is stale")
    parser.add_argument("--verify-wording", metavar="TEXT", help="grade a candidate line (read-only)")
    args = parser.parse_args(argv)

    profile, digest = _read_profile()

    if args.verify_wording:
        findings = verify_wording(args.verify_wording, profile)
        if findings:
            print("NOT acceptable as a verified responsibility line yet:")
            for finding in findings:
                print(f"  - {finding}")
            print(
                "\nThe release guard requires a line that introduces no duty vocabulary and no named "
                "entity beyond what the applicant supplied. Reword it from your own record."
            )
            return 1
        print(
            "Clean under the release guard: no unsupported duty terms, unnamed entities, numeric "
            "precision, or achievement claims. `python -m pytest -q` remains the final gate."
        )
        return 0

    items = collect_review_items(profile)
    if not items:
        raise ReviewError(
            "no held responsibility drafts remain in profile.yaml; there is nothing to review"
        )
    if not HISTORICAL_REVIEW_PATH.exists():
        raise ReviewError(
            f"the frozen pre-recovery review is missing: {_display_path(HISTORICAL_REVIEW_PATH)}"
        )

    rendered = render_markdown(profile, digest, items)
    print(render_stdout_table(items))

    if args.stdout_only:
        return 0

    if args.check:
        if not REVIEW_DOC_PATH.exists():
            print(f"MISSING: {_display_path(REVIEW_DOC_PATH)}")
            return 1
        if REVIEW_DOC_PATH.read_text(encoding="utf-8") != rendered:
            print(f"STALE: {_display_path(REVIEW_DOC_PATH)} differs from the canonical record")
            return 1
        print(f"IN SYNC: {_display_path(REVIEW_DOC_PATH)}")
        return 0

    REVIEW_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_DOC_PATH.write_text(rendered, encoding="utf-8")
    if hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest() != digest:
        raise ReviewError("profile.yaml changed while the review list was being generated")
    print(f"WROTE: {_display_path(REVIEW_DOC_PATH)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
