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
        assert result.count(".") == summary.count(".")
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
        assert 12 <= len(summary.split()) < len(source_summary.split())
        assert "managed 500 staff" not in summary
    for result in outputs:
        assert len(result["tailored_cv_model"]["experience"]) == 5
        model = result["tailored_cv_model"]
        assert model["is_employer_curated"] is True
        assert model["full_verified_duty_count"] == 24
        assert 12 <= model["selected_duty_count"] <= 20
        assert sum(len(entry["bullets"]) for entry in model["experience"]) == model["selected_duty_count"]
        assert all(len(role["bullets"]) >= 1 for role in model["experience"])
        assert result["cover_letter"].count("In my documented role as") <= 2
        assert "Jobs-Finder" not in result["cover_letter"]
    assert profile == before


def test_medical_coordinator_highlights_real_supervision_without_reducing_roles_to_one_line():
    from utils.application_editorial import select_employer_facing_experience
    profile = load_canonical_profile(required=True)
    job = {
        "title": "Medical Coordinator",
        "description": "Coordinate health projects, supervise staff and field teams, "
                       "work with MoPH, oversee reporting, clinical quality and supplies.",
    }
    document = generate_tailored_documents(job, profile, {"facts": {}})
    exp = document["tailored_cv_model"]["experience"]
    assert len(exp) == 5
    assert [x["role"] for x in exp][:2] == [
        "TFU Medical Doctor & Safeguarding Focal Point", "Health & Nutrition Supervisor"
    ]
    assert len(exp[0]["bullets"]) >= 3
    assert len(exp[1]["bullets"]) >= 3
    assert 12 <= sum(len(x["bullets"]) for x in exp) <= 20
    assert all(len(role["bullets"]) >= 2 for role in exp)
    assert any("coordinat" in x.lower() or "supervis" in x.lower()
               for role in exp[:2] for x in role["bullets"])
    # The selected text is exact owner-provided evidence, never rewritten.
    for role in exp:
        source = next(row for row in profile["work_history"] if row["title"] == role["role"])
        approved = [row["text"] for row in source["responsibilities"] if row["verified"] is True]
        assert all(line.rstrip(".") in {x.rstrip(".") for x in approved} for line in role["bullets"])
    assert document["tailored_cv_model"]["full_verified_duty_count"] == 24
    assert select_employer_facing_experience([], "Medical Coordinator") == ([], 0)


def test_employer_cv_curates_competencies_while_master_retains_every_skill():
    from utils.documents import generate_master_cv

    profile = load_canonical_profile(required=True)
    job = {"title":"Medical Coordinator",
           "description":"Medical staff supervision, MoPH health services coordination, HMIS, quality."}
    tailored = generate_tailored_documents(job, profile, {"facts":{}})["tailored_cv_model"]
    master = generate_master_cv(profile)["master_cv_model"]
    shown = {item for group in tailored["expertise"] for item in group["items"]}
    comprehensive = {item for group in master["expertise"] for item in group["items"]}
    assert shown <= comprehensive
    assert len(shown) <= 12
    assert len(tailored["expertise"]) <= 5
    assert len(comprehensive) > len(shown)


def test_focused_cv_keeps_multiple_real_duties_in_each_supported_role():
    from copy import deepcopy

    from utils.application_editorial import select_employer_facing_experience

    profile = load_canonical_profile(required=True)
    job = {"title": "Medical Coordinator", "description": "Lead clinical services and field teams, coordinate with provincial authorities, oversee HMIS."}
    detailed_profile = deepcopy(profile)
    detailed_profile["document_preferences"]["cv_depth"] = "detailed"
    original = generate_tailored_documents(job, detailed_profile, {"facts": {}})["tailored_cv_model"]["experience"]
    focus, full_count = select_employer_facing_experience(
        original, job["title"], job["description"], detail="focused",
    )
    assert full_count == 24
    assert len(focus) == len(original) == 5
    assert 15 < sum(len(row["bullets"]) for row in focus) <= 20
    assert len(focus[0]["bullets"]) >= 4
    assert len(focus[1]["bullets"]) >= 4
    assert all(len(row["bullets"]) >= 2 for row in focus)
    source = deepcopy(profile)
    focused_profile = deepcopy(profile)
    focused_profile["document_preferences"]["cv_depth"] = "focused"
    tailored = generate_tailored_documents(job, focused_profile, {"facts": {}})
    assert tailored["tailored_cv_model"]["selected_duty_count"] == sum(len(row["bullets"]) for row in focus)
    assert profile == source


def test_professional_profile_preserves_owner_selected_full_depth_and_executive_visual():
    profile = load_canonical_profile(required=True)
    assert profile["document_preferences"]["cv_depth"] == "focused"
    assert profile["document_preferences"]["cv_style"] == "executive"
    for title in ("Medical Coordinator", "Provincial Coordinator", "TFU Medical Doctor"):
        docs = generate_tailored_documents(
            {"title":title, "company":"Example NGO", "description":"Health services supervision and coordination."},
            profile, {"facts":{}},
        )
        cv = docs["tailored_cv_model"]
        assert cv["cv_depth"] == "focused"
        assert cv["cv_style"] == "executive"
        assert cv["full_verified_duty_count"] == 24
        assert 12 <= cv["selected_duty_count"] <= 20
        assert len(cv["experience"]) == 5
        assert all(len(role["bullets"]) >= 2 for role in cv["experience"])
