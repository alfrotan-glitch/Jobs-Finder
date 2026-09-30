"""
Tailored application documents.

AI can optionally improve phrasing, but deterministic review-first generation is
the default and fallback.  Nothing in this module should invent facts that are
not present in the user's profile/CV evidence.
"""

from __future__ import annotations

from typing import Any

from utils.documents import generate_tailored_documents
from utils.medical_matcher import match_job_against_profile


def tailor_resume(job_description: str, base_resume_text: str, profile: dict, brain=None, job: dict | None = None) -> dict:
    """
    Generate tailored CV and cover-letter content for a job posting.

    Returns legacy keys (`tailored_summary`, `tailored_bullets`,
    `tailored_cover_letter`) plus the newer review-first document keys.
    """
    job_data: dict[str, Any] = job or {
        "id": "ad-hoc",
        "title": "Medical role",
        "company": "organization",
        "location": "",
        "description": job_description,
        "url": "",
        "apply_url": "",
        "metadata": {},
    }
    if not job_data.get("description"):
        job_data["description"] = job_description

    report = match_job_against_profile(job_data, profile, resume_text=base_resume_text).to_dict()
    docs = generate_tailored_documents(job_data, profile, report, resume_text=base_resume_text)

    # Compatibility with the old dashboard/API.
    docs["tailored_summary"] = _summary_from_documents(docs)
    docs["tailored_bullets"] = docs.get("matched_requirements_used", [])[:6]
    docs["emphasis_areas"] = docs.get("matched_requirements_used", [])
    docs["keywords_to_include"] = docs.get("matched_requirements_used", [])
    docs["deemphasize"] = []
    docs["tailored_cover_letter"] = docs.get("cover_letter", "")
    docs["match_report"] = report

    # Optional AI refinement is intentionally conservative and non-blocking.
    if brain is not None and profile.get("ai", {}).get("enable_document_refinement", False):
        try:
            prompt = _ai_refinement_prompt(docs, profile, job_description)
            refined = brain.ask_json(prompt, timeout=120, component="resume_tailoring")
            if _refinement_is_safe(refined, docs):
                docs.update({k: v for k, v in refined.items() if k in {"tailored_summary", "tailored_bullets", "tailored_cover_letter", "cover_letter"}})
                if refined.get("cover_letter"):
                    docs["tailored_cover_letter"] = refined["cover_letter"]
        except Exception as exc:
            docs["ai_refinement_error"] = str(exc)

    return docs


def _summary_from_documents(docs: dict[str, Any]) -> str:
    cv = docs.get("tailored_cv_text", "")
    for line in cv.splitlines():
        if line and not line.startswith("-") and "tailored CV draft" in line:
            return line
    return "Tailored draft generated from verified profile/CV evidence."


def _ai_refinement_prompt(docs: dict[str, Any], profile: dict, job_description: str) -> str:
    return f"""Improve only the wording of these application drafts. Do not add any new facts, numbers, skills, locations, licenses, languages, achievements, or experience. If a fact is not already in the draft, do not include it.

CURRENT DRAFTS:
{docs}

JOB POSTING EXCERPT:
{job_description[:3000]}

Return JSON with optional keys: tailored_summary, tailored_bullets, cover_letter.
"""


def _refinement_is_safe(refined: Any, original_docs: dict[str, Any]) -> bool:
    if not isinstance(refined, dict):
        return False
    # Extremely conservative: AI output must not remove review warnings.
    warnings = original_docs.get("review_warnings", [])
    cover = str(refined.get("cover_letter") or refined.get("tailored_cover_letter") or "")
    for warning in warnings:
        label = warning.split("—", 1)[0].replace("Verify:", "").replace("Potential gap:", "").strip()
        if label and label.lower() in cover.lower():
            return False
    return True
