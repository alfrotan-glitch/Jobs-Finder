"""The one authoritative recommendation authority for Jobs-Finder.

Every surface — the overall scan summary, the CLI list, the dashboard
Recommended view, and persisted scan activity — must present exactly the same
recommendation collection. They therefore all derive it here; none of them may
re-implement "what counts as recommended" independently.

A vacancy is recommendable for a profile only when BOTH hold:

1. Readiness is actionable review work: ``READY_TO_APPLY`` or
   ``NEEDS_VERIFICATION`` (a proven conflict / ``NOT_ELIGIBLE`` is never
   recommended).
2. The professional role family is *actually* compatible with an
   MD/public-health profile: the role analysis classified it as
   ``md_physician_role`` or ``health_public_health_compatible``.

Rule 2 is what keeps generic programme/operations roles out of the
recommendation list. Discovery may stay broad (a "Project Manager" vacancy on
a health project is retained and reviewable in the jobs list), but a role that
was kept only because it contains generic health/medical words
(``ambiguous_health_words``) or is not a medical/public-health role at all
must never be *recommended*.
"""

from __future__ import annotations

from typing import Any

from utils.medical_matcher import NEEDS_VERIFICATION_STATUS, READY_TO_APPLY
from utils.medical_requirements import analyze_professional_role

RECOMMENDABLE_READINESS = (READY_TO_APPLY, NEEDS_VERIFICATION_STATUS)
COMPATIBLE_ROLE_CLASSIFICATIONS = {"md_physician_role", "health_public_health_compatible"}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


# Tracker-style progress mapping (mirrors utils.tracker.readiness_to_status;
# kept local so this module stays import-safe for tracker itself).
_PROGRESS_BY_READINESS = {
    READY_TO_APPLY: "REVIEWED",
    NEEDS_VERIFICATION_STATUS: "NEEDS_VERIFICATION",
}


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(value)


def readiness_of(job: dict[str, Any], match: dict[str, Any] | None = None) -> str:
    """Read the matched readiness from the match report first, then the row."""
    match = match if isinstance(match, dict) else {}
    return str(match.get("readiness_status") or job.get("readiness") or "").strip()


def role_classification_for(job: dict[str, Any], match: dict[str, Any] | None = None) -> str:
    """The professional-role classification used by the recommendation gate.

    Prefers the analysis captured at match time (``match.facts.role_analysis``,
    or the enrichment snapshot under ``metadata.requirements.facts``) and
    analyses the vacancy text only when neither snapshot is present.
    """
    match = _dict_or_empty(match)
    facts = _dict_or_empty(match.get("facts"))
    role = facts.get("role_analysis")
    if isinstance(role, dict) and role.get("classification"):
        return str(role["classification"])
    metadata = _dict_or_empty(job.get("metadata"))
    requirements = _dict_or_empty(metadata.get("requirements"))
    req_facts = _dict_or_empty(requirements.get("facts"))
    role = req_facts.get("role_analysis")
    if isinstance(role, dict) and role.get("classification"):
        return str(role["classification"])
    return str(analyze_professional_role(str(job.get("title") or ""), str(job.get("description") or "")).get("classification") or "")


def is_recommendable(job: dict[str, Any], match: dict[str, Any] | None = None) -> bool:
    """The one recommendation gate (see module docstring)."""
    if readiness_of(job, match) not in RECOMMENDABLE_READINESS:
        return False
    return role_classification_for(job, match) in COMPATIBLE_ROLE_CLASSIFICATIONS


def recommendation_rank(entry: dict[str, Any]) -> tuple[int, str, str]:
    """The one recommendation ordering: ready first, then by real deadline."""
    readiness = readiness_of(entry, entry.get("match"))
    bucket = 0 if readiness == READY_TO_APPLY else 1
    metadata = _dict_or_empty(entry.get("metadata"))
    closing = str(metadata.get("closing_date") or "9999-12-31")
    return (bucket, closing, str(entry.get("id") or ""))


def build_recommendation_entry(job: Any, match: dict[str, Any]) -> dict[str, Any]:
    """One display-ready recommendation entry.

    The shape mirrors tracker rows (``utils.tracker._to_dict``) so the CLI and
    dashboard render scan recommendations and stored jobs identically. The full
    match report is embedded exactly as produced by the matcher — the same
    report that is persisted to the vacancy row — never a recomputation.
    """
    data = _as_dict(job)
    match = _dict_or_empty(match)
    metadata = _dict_or_empty(data.get("metadata"))
    readiness = readiness_of(data, match)
    return {
        "id": str(data.get("id") or ""),
        "title": str(data.get("title") or "Untitled vacancy"),
        "company": str(data.get("company") or "Unknown employer"),
        "location": str(data.get("location") or ""),
        "source": str(metadata.get("source_name") or metadata.get("source") or data.get("platform") or ""),
        "platform": str(data.get("platform") or ""),
        "url": str(data.get("vacancy_url") or data.get("url") or metadata.get("vacancy_url") or ""),
        "apply_url": data.get("apply_url") or metadata.get("apply_url") or "",
        "apply_email": str(data.get("apply_email") or metadata.get("apply_email") or metadata.get("application_email") or ""),
        "application_method": str(data.get("application_method") or metadata.get("application_method") or "UNAVAILABLE"),
        "description": str(data.get("description") or ""),
        "status": _PROGRESS_BY_READINESS.get(readiness, "REVIEWED"),
        "readiness": readiness,
        "package_status": "NOT_CREATED",
        "metadata": metadata,
        "match": match,
        "role_classification": role_classification_for(data, match),
    }


def iter_match_pairs(items: list[Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Normalize match inputs into ``(job, match)`` pairs.

    Producers must supply both halves of every outcome — the recommendation
    collection and the summary counters are derived from the same pairs, which
    is what makes the accounting invariant structural instead of asserted.
    Accepted forms: ``(job, match)`` tuples/lists or ``{"job": ..., "match": ...}``
    mappings. Bare status dicts are rejected on purpose.
    """
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for item in items:
        if isinstance(item, dict) and "job" in item and "match" in item:
            job, match = item["job"], item["match"]
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            job, match = item
        else:
            raise ValueError(
                "record_match_results requires (job, match) pairs so the summary "
                "count and the printed recommendation list can never disagree."
            )
        pairs.append((_as_dict(job), _as_dict(match)))
    return pairs


def collect_scan_recommendations(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[dict[str, Any]]:
    """The authoritative per-scan recommendation collection (ordered)."""
    entries = [build_recommendation_entry(job, match) for job, match in pairs if is_recommendable(job, match)]
    entries.sort(key=recommendation_rank)
    return entries


def evaluate_scan_jobs(scan: Any, profile: dict[str, Any], resume_text: str = "") -> Any:
    """Match everything the scan retained, persist outcomes, and record them.

    This is the single orchestration used identically by the CLI and the
    dashboard: every retained job is stored, deterministically matched, the
    match is persisted, and the scan's authoritative recommendation collection
    is derived from the same (job, match) pairs.
    """
    from utils.medical_matcher import (
        match_job_against_profile,  # local import: no import cycle
    )
    from utils.tracker import log_discovered_and_medical_match

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for job in scan.jobs:
        job_data = _as_dict(job)
        report = match_job_against_profile(job_data, profile, resume_text=resume_text).to_dict()
        pairs.append((job_data, report))
        # Discovery and its match now share one BEGIN IMMEDIATE/COMMIT pair.
        # This is still sequential per scan, but removes the cross-connection
        # race window when a dashboard and CLI touch the same WAL database.
        log_discovered_and_medical_match(job, report)
    scan.record_match_results(pairs)
    return scan
