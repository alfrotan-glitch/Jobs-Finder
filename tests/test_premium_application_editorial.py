"""Premium editorial acceptance: role-specific, truthful CVs and concise email."""
from __future__ import annotations

from copy import deepcopy

from utils.application_editorial import (
    concise_attested_highlights,
    factual_relevance_score,
    rank_attested_statements,
    target_verified_summary,
)
from utils.documents import _email_body, generate_tailored_documents
from utils.profile import load_canonical_profile


def test_job_title_controls_attested_evidence_order_without_dropping_facts():
    original = [
        "Delivered clinical assessments and treatment for patients.",
        "Coordinated field teams with provincial health authorities.",
        "Supported routine program reporting and stakeholder liaison.",
    ]
    coordinator = rank_attested_statements(original, "Provincial Coordinator")
    clinician = rank_attested_statements(original, "Medical Doctor")
    assert coordinator[0].startswith("Coordinated")
    assert clinician[0].startswith("Delivered")
    assert set(coordinator) == set(clinician) == set(original)
    assert len(coordinator) == len(original)
    assert factual_relevance_score("nutrition screening", "Nutrition Supervisor") > 0
    # A substring inside MALNUTRITION must not count as an exact match for
    # nutrition. It can still be matched by other clinical/nutrition signals.
    assert factual_relevance_score("malnutrition", "Nutrition Supervisor") == 0


def test_long_verified_summary_is_vacancy_specific_and_claim_preserving():
    summary = (
        "Medical Doctor with extensive verified field work in Afghanistan. "
        "Provided clinical consultations and inpatient medical care for patients. "
        "Coordinated provincial health stakeholders and supported reporting. "
        "Supervised mobile teams and monitored nutrition programming. "
        "Maintained confidentiality and safeguarding standards during response."
    )
    clinical = target_verified_summary(summary, "TFU Medical Doctor")
    coordination = target_verified_summary(summary, "Provincial Coordinator")
    assert clinical != coordination
    assert clinical.startswith("Medical Doctor with")
    assert coordination.startswith("Medical Doctor with")
    source_sentences = [piece.strip() for piece in summary.split(". ") if piece.strip()]
    for result in (clinical, coordination):
        assert result.count(".") == 3
        assert all(sentence.rstrip(".") in summary for sentence in result.split(". ") if sentence)
        assert "managed a budget" not in result
    assert target_verified_summary("Verified MD background.", "Medical Doctor") == "Verified MD background."
    assert source_sentences


def test_short_employer_email_is_not_a_second_cover_letter():
    profile = load_canonical_profile(required=True)
    highlights = [
        "Coordinated provincial authorities on public health programming.",
        "Supervised field-level health and nutrition teams.",
        "Maintained verified health and nutrition reporting.",
        "Contributed to field coordination and logistics.",
    ]
    original = deepcopy(profile)
    with_letter = _email_body(
        name="Sample Applicant", title="Provincial Coordinator",
        company="Example Health Organization", location="Daikundi",
        profile=profile, highlights=highlights, include_cover_letter=True,
        background_sentence="I have verified health and nutrition experience.",
    )
    cv_only = _email_body(
        name="Sample Applicant", title="Provincial Coordinator",
        company="Example Health Organization", location="Daikundi",
        profile=profile, highlights=highlights, include_cover_letter=False,
    )
    assert len(with_letter.split()) < 150
    assert len(cv_only.split()) < 160
    assert with_letter.count("\n- ") == 1
    assert cv_only.count("\n- ") == 2
    assert "my CV and cover letter" in with_letter
    assert "my CV and cover letter" not in cv_only
    assert "my CV" in cv_only
    assert "Sample Applicant" in with_letter
    assert "Example Health Organization" in with_letter
    assert profile == original


def test_long_evidence_is_not_cut_mid_claim_for_email():
    long_evidence = "Supervised " + "public health coordination " * 16 + "in Daikundi."
    assert concise_attested_highlights(
        [long_evidence, "Maintained accurate HMIS reporting."],
        has_cover_letter=True,
    ) == ["Maintained accurate HMIS reporting."]


def test_real_official_profile_produces_distinct_targeted_summaries_without_invention():
    profile = load_canonical_profile(required=True)
    before = deepcopy(profile)
    jobs = [
        {
            "title": "Provincial Coordinator",
            "company": "Illustrative NGO",
            "description": "Provincial coordination, stakeholder meetings, HMIS reporting, program oversight and supervision.",
        },
        {
            "title": "TFU Medical Doctor",
            "company": "Illustrative NGO",
            "description": "TFU clinical care, SAM treatment and inpatient management under IMAM protocols.",
        },
        {
            "title": "Health & Nutrition Supervisor",
            "company": "Illustrative NGO",
            "description": "Supervise field mobile teams and nutrition screening and reporting.",
        },
    ]
    outputs = [generate_tailored_documents(job, profile, {"facts": {}}) for job in jobs]
    summaries = [result["tailored_cv_model"]["profile"] for result in outputs]
    assert len(set(summaries)) >= 2
    source_summary = profile["professional_summary"]["text"]
    for summary in summaries:
        assert summary.startswith(source_summary.split(". ")[0])
        assert len(summary.split()) < len(source_summary.split())
        assert "managed 500 staff" not in summary
    for result in outputs:
        assert len(result["tailored_cv_model"]["experience"]) == 5
        assert sum(len(entry["bullets"]) for entry in result["tailored_cv_model"]["experience"]) == 24
        assert result["cover_letter"].count("In my documented role as") <= 2
        assert "Jobs-Finder" not in result["cover_letter"]
    assert profile == before
