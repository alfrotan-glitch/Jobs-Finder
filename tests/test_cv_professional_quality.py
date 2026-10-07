"""Professional CV quality contract for the real canonical profile.

These tests protect the *product output*, not just the Python functions. They
generate real TXT/DOCX/PDF artifacts from the shipped canonical profile and
assert the guarantees that make the CV usable for a real medical / health /
nutrition application:

* the Master CV is comprehensive (profile, grouped competencies, every verified
  role with its applicant-supported scope, education, registration, exit exam,
  certifications, languages, a reference line);
* every verified responsibility, certificate, and language survives into the
  rendered TXT, DOCX and PDF, while every *unverified* responsibility draft
  stays out of all of them;
* a duty becomes verified experience only on applicant evidence. A role title,
  a verified skill, a certificate, a sector norm, an employer, or a plausible
  inference must never let the system assert that the applicant did something
  the applicant never supplied;
* no private reference contact data, license number, or invented date reaches
  any artifact;
* the ACF roles keep their intentionally unpresise (blank) dates;
* tailoring only reorders/re-groups evidence, never mutates the canonical
  profile or the position-neutral Master CV.

Nothing here asserts a specific page count: content decides pagination. The
assertions are about completeness, readability, and factual integrity.
"""

from __future__ import annotations

import json
import re
import zipfile
from datetime import date
from pathlib import Path

import pdfplumber
import yaml

from tests.test_canonical_profile_architecture import SAMPLE_EMAIL, SAMPLE_NAME
from utils.documents import (
    build_expertise_groups,
    generate_master_cv,
    generate_tailored_documents,
    prepare_application_bundle,
    write_master_cv,
)
from utils.medical_matcher import match_job_against_profile
from utils.profile import build_profile_evidence, load_canonical_profile

TODAY = date(2026, 10, 1)

MASTER_SECTIONS = [
    "PROFESSIONAL SUMMARY",
    "CORE PROFESSIONAL COMPETENCIES",
    "PROFESSIONAL EXPERIENCE",
    "EDUCATION",
    "PROFESSIONAL REGISTRATION",
    "MEDICAL EXIT EXAMINATION",
    "PROFESSIONAL TRAINING & CERTIFICATIONS",
    "LANGUAGES",
    "REFERENCES",
]

EXPERTISE_GROUP_TITLES = [
    "Clinical & Medical Practice",
    "Health & Nutrition Programming",
    "Public Health Systems & Quality",
    "Programme Coordination & Field Operations",
    "Supervision & Capacity Building",
    "Safeguarding, Protection & Compliance",
    "Supply Chain, Logistics & Administration",
]

REAL_ORGANIZATIONS = [
    "ACF-International",
    "Daikundi Provincial Public Health Directorate",
    "Daikundi Governor’s Office",
    "Trend for a Better Tomorrow (TBT)",
]

FORBIDDEN_EMPLOYER_FACING_TOKENS = [
    "CONFIRM BEFORE SUBMISSION",  # every printed field is verified in this profile
    "Needs verification",
    "UNKNOWN",
    "TBD",
    "N/A",
    "Jobs-Finder",
    "package status",
    "readiness",
    "matching score",
]


def _profile() -> dict:
    return load_canonical_profile(required=True)


def _verified_responsibilities(entry: dict) -> list[str]:
    """Responsibility text carrying an explicit ``verified: true`` flag.

    Canonical shape: ``responsibilities`` holds ``{"text": ..., "verified": ...}``
    items. A bare string, a missing flag, or ``verified: false`` is draft
    material and must never be presented as applicant experience.
    """
    return [
        str(item["text"])
        for item in entry.get("responsibilities") or []
        if isinstance(item, dict) and item.get("verified") is True
    ]


def _pending_responsibilities(profile: dict) -> list[tuple[str, str]]:
    """``(role, text)`` for every draft held back from employer-facing documents."""
    pending: list[tuple[str, str]] = []
    for entry in profile.get("work_history") or []:
        for item in entry.get("needs_verification") or []:
            if isinstance(item, dict) and item.get("verified") is not True:
                pending.append((str(entry.get("title") or ""), str(item.get("text") or "")))
    return pending


def _applicant_supplied_facts(profile: dict) -> set[str]:
    """Tokens the applicant actually supplied as facts.

    Deliberately excludes every duty/description field (including the drafts in
    ``needs_verification``) AND the verified skills and certificates. Those are
    inventoried elsewhere in the profile; the audit finding was precisely that a
    skill or certificate must not be treated as evidence that a duty was
    performed. What remains is what the applicant supplied *about a role*: its
    title, employer and location, plus identity, education, licence status, exit
    exam, languages, and the applicant's own experience-area statements.
    """
    facts: set[str] = set()
    excluded = {
        "responsibilities",
        "bullets",
        "description",
        "duties",
        "achievements",
        "needs_verification",
        "skills",
        "certificates",
    }

    def absorb(value) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in excluded:
                    continue
                absorb(child)
        elif isinstance(value, list):
            for child in value:
                absorb(child)
        elif value not in (None, ""):
            facts.update(part for part in re.split(r"[^a-z0-9]+", str(value).lower()) if part)

    absorb({key: value for key, value in profile.items() if key != "work_history"})
    for entry in profile.get("work_history") or []:
        for key in ("title", "organization", "location", "start", "end"):
            absorb(entry.get(key))
    return facts


#: Duty-activity vocabulary that only applicant evidence can support. Every term
#: here was present in the system-authored drafts that this audit removed while
#: being absent from everything the applicant supplied, so it doubles as a
#: permanent regression guard: if any of these words reappears in a *verified*
#: responsibility without applicant evidence, the audit has been undone.
DUTY_ACTIVITY_TERMS: set[str] = {
    # Clinical activity
    "assessment", "assessments", "diagnosis", "diagnoses", "treatment", "treatments",
    "patient", "patients", "admitted", "admission", "inpatient", "outpatient", "ward",
    "progress", "triage", "screening", "prescribing", "surgery", "referral", "referrals",
    "case", "cases", "consultation", "procedures", "prescription",
    # Nutrition / programme delivery
    "imam", "cmam", "sam", "mam", "otp", "tfu", "ipc", "imnci", "iycf", "bphs", "ephs",
    "hmis", "dhis2", "moph", "identification", "linkage", "feeding", "therapeutic",
    "malnutrition", "protocol", "protocols", "registers", "visits", "coaching",
    "forecasting", "stock", "distribution", "adherence", "enrolment", "enrollment",
    # Quality / reporting / supply / protection activity
    "audit", "audits", "data", "records", "documentation", "reporting", "reports",
    "quality", "care", "review", "reviews", "forecast", "supplies", "logistics",
    "protection", "protective", "safeguarding", "psea", "awareness", "exploitation",
    "abuse", "complaints",
    # Action verbs that assert the applicant personally performed a duty
    "provided", "provide", "monitored", "monitoring", "conducted", "documented",
    "maintained", "prepared", "coordinated", "coordinating", "liaised", "supervised",
    "supervising", "advised", "acted", "collected", "reported", "participated",
    "reviewed", "built", "applied", "led", "took", "supported", "delivered",
    "implemented", "trained", "managed", "organised", "organized", "verified",
}


def _unanchored_duty_terms(line: str, applicant_facts: set[str]) -> set[str]:
    """Duty-activity terms in ``line`` that no applicant-supplied fact supports."""
    tokens = {part for part in re.split(r"[^a-z0-9]+", str(line).lower()) if part}
    return {token for token in tokens & DUTY_ACTIVITY_TERMS if token not in applicant_facts}


def _pdf_text(path: str | Path) -> str:
    with pdfplumber.open(str(path)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _pdf_pages(path: str | Path) -> int:
    with pdfplumber.open(str(path)) as pdf:
        return len(pdf.pages)


def _last_page_fill_ratio(path: str | Path) -> float:
    """How full the final page is (0..1), measured independently of the renderer.

    The footer is excluded so the page number cannot make an empty page look
    full. Measured from real PDF character positions, not from renderer state.
    """
    with pdfplumber.open(str(path)) as pdf:
        if len(pdf.pages) < 2:
            return 1.0
        page = pdf.pages[-1]
        bottom_limit = page.height - 45
        body = [char for char in page.chars if char.get("bottom", 0) < bottom_limit]
        if not body:
            return 0.0
        top = min(char["top"] for char in body)
        bottom = max(char["bottom"] for char in body)
        return max(0.0, min(1.0, (bottom - top) / max(bottom_limit - 40, 1)))


def _docx_xml(path: str | Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read("word/document.xml").decode("utf-8", errors="replace")


def _docx_text(path: str | Path) -> str:
    import html

    xml = _docx_xml(path)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def _medical_job() -> dict:
    return {
        "id": "cv-quality-medical",
        "title": "Medical Doctor (MD)",
        "company": "Afghanistan Health Organization",
        "location": "Kabul",
        "url": "https://jobs.example.org/cv-quality-medical",
        "apply_url": "recruitment@example.org",
        "description": (
            "Medical Doctor (MD) required. Valid medical registration, Medical Exit Exam, at least 3 years of "
            "clinical experience, patient assessment, diagnosis, treatment, infection prevention and control, "
            "clinical audit, and HMIS reporting. Apply to recruitment@example.org by 2026-12-31."
        ),
        "metadata": {
            "source_name": "ACBAR",
            "source_url": "https://jobs.example.org/source",
            "vacancy_url": "https://jobs.example.org/cv-quality-medical",
        },
    }


def _nutrition_job() -> dict:
    return {
        "id": "cv-quality-nutrition",
        "title": "Health & Nutrition Supervisor",
        "company": "Afghanistan Nutrition Organization",
        "location": "Daikundi",
        "url": "https://jobs.example.org/cv-quality-nutrition",
        "apply_url": "hr@example.org",
        "description": (
            "Health & Nutrition Supervisor. Doctor of Medicine (MD) accepted. IMAM/CMAM, SAM/MAM, TFU/OTP, IYCF, "
            "outreach supervision, HMIS/DHIS2 reporting, MoPH coordination, medical supply forecasting, field "
            "monitoring, and safeguarding/PSEA required. Apply to hr@example.org by 2026-12-31."
        ),
        "metadata": {
            "source_name": "ACBAR",
            "source_url": "https://jobs.example.org/source",
            "vacancy_url": "https://jobs.example.org/cv-quality-nutrition",
        },
    }


def _safeguarding_job() -> dict:
    return {
        "id": "cv-quality-safeguarding",
        "title": "Safeguarding & PSEA Officer",
        "company": "Humanitarian Health Organization",
        "location": "Kabul",
        "url": "https://jobs.example.org/cv-quality-safeguarding",
        "apply_url": "jobs@example.org",
        "description": (
            "Safeguarding & PSEA Officer. Health or protection background accepted. Safeguarding, PSEA, child "
            "protection, awareness raising, reporting channels, and coordination with health programmes required. "
            "Apply to jobs@example.org by 2026-12-31."
        ),
        "metadata": {
            "source_name": "ACBAR",
            "source_url": "https://jobs.example.org/source",
            "vacancy_url": "https://jobs.example.org/cv-quality-safeguarding",
        },
    }


# ---------------------------------------------------------------------------
# Master CV: content completeness
# ---------------------------------------------------------------------------


def test_master_cv_model_is_comprehensive_for_the_real_profile():
    profile = _profile()
    model = generate_master_cv(profile)["master_cv_model"]

    # Identity and headline come from the verified canonical profile.
    assert model["name"] == "Dr. Allah Yar Frotan"
    assert model["headline"] == "Medical Doctor / Health & Nutrition Specialist"

    # A substantive professional profile, not a one-line summary.
    assert len(model["profile"].split()) >= 90

    # Complete professional skills architecture with every verified competency.
    evidence = build_profile_evidence(profile)
    verified_skills = [item["name"] for item in _verified_skill_items(profile)]
    grouped = [item for group in model["expertise"] for item in group["items"]]
    assert sorted(grouped) == sorted(verified_skills)
    assert [group["group"] for group in model["expertise"]][:2] == [
        "Clinical & Medical Practice",
        "Health & Nutrition Programming",
    ]

    # Every verified role, in canonical order, with a real description.
    assert len(model["experience"]) == len(profile["work_history"]) == 5
    assert [item["org"] for item in model["experience"]] == [
        "ACF-International",
        "ACF-International",
        "Daikundi Provincial Public Health Directorate",
        "Daikundi Governor’s Office",
        "Trend for a Better Tomorrow (TBT)",
    ]
    # Every role keeps an applicant-supported professional scope line. Nothing
    # more is claimed, because the applicant supplied no duties for any role.
    for item, entry in zip(model["experience"], profile["work_history"]):
        verified = _verified_responsibilities(entry)
        assert item["bullets"] == [b for b in verified], item["role"]
        assert len(item["bullets"]) >= 1, item["role"]
        assert all(len(bullet) >= 40 for bullet in item["bullets"]), item["role"]

    # Credentials, training, languages, and a private-reference placeholder.
    assert model["education"] == ["Doctor of Medicine (MD) — Curative Medicine — Kabul Medical Science University — 2013–2020"]
    assert model["registration"] == ["Valid medical professional registration/license"]
    assert model["exit_exam"] == ["Completed"]
    assert len(model["certifications"]) == 7
    assert model["languages"] == [("Dari/Persian", "Native"), ("English", "Fluent"), ("Pashto", "Intermediate")]
    assert model["references"]
    assert evidence.has_verified("md_degree")


def _verified_skill_items(profile: dict) -> list[dict]:
    items: list[dict] = []
    for values in (profile.get("skills") or {}).values():
        for item in values or []:
            if isinstance(item, dict) and item.get("verified") is True:
                items.append(item)
    return items


def test_master_cv_text_contains_every_verified_fact():
    profile = _profile()
    master = generate_master_cv(profile)
    text = master["master_cv_text"]

    for section in MASTER_SECTIONS:
        assert section in text, section
    for organization in REAL_ORGANIZATIONS:
        assert organization in text, organization
    assert "Doctor of Medicine (MD)" in text
    assert "Kabul Medical Science University" in text
    assert "2013–2020" in text
    assert "Valid medical professional registration/license" in text
    assert "Completed" in text  # Medical Exit Examination
    for certificate in profile["certificates"]:
        assert certificate["name"] in text, certificate["name"]
    for language in profile["languages"]:
        assert language["name"] in text
        assert language["level"] in text
    for entry in profile["work_history"]:
        assert entry["title"] in text
        for responsibility in _verified_responsibilities(entry):
            assert responsibility in text, responsibility
    # Every verified competency and experience area reaches the document.
    for skill in [item["name"] for item in _verified_skill_items(profile)]:
        assert skill in text, skill
    for area in ("health and nutrition service delivery", "humanitarian health programming", "team supervision and capacity building"):
        assert area in text, area
    # No held-back draft may appear in the document.
    for _role, draft in _pending_responsibilities(profile):
        assert draft not in text, draft
    # The professional profile must not be a thin one-liner, and the document
    # must stay a substantial CV even though only applicant-supported scope is
    # printed for each role.
    assert len(text.split("PROFESSIONAL SUMMARY", 1)[1].split("\n\n", 1)[0].split()) >= 90
    assert len(text.split()) >= 400


def test_master_cv_never_prints_unverified_or_private_facts():
    profile = _profile()
    master = generate_master_cv(profile)
    text = master["master_cv_text"]
    registration = profile["license_registration"]

    for token in FORBIDDEN_EMPLOYER_FACING_TOKENS:
        assert token.lower() not in text.lower(), token
    # No medical registration number/date/document path may be printed, and no
    # reference contact data may be released in a default CV.
    assert "Registration number" not in text
    assert "Issue date" not in text
    assert "Expiry" not in text
    assert "license_registration" not in text
    assert registration["number"] == ""
    assert registration["document_path"] == ""
    assert not re.search(r"\b(?:license|registration)\s*(?:no\.?|number)\b", text, flags=re.IGNORECASE)
    # The two ACF roles keep deliberately unpresise (blank) dates.
    acf_lines = [line for line in text.splitlines() if line.startswith("ACF-International")]
    assert acf_lines and all("|" in line and len(line.split("|")) == 2 for line in acf_lines)


def test_master_cv_never_invents_dates_numbers_or_achievements():
    profile = _profile()
    text = generate_master_cv(profile)["master_cv_text"]

    # The only years in the CV are the verified education years, certificate
    # years, and the dated DPPHD/Governor's Office/TBT roles.
    verified_years = {"2013", "2020", "2022", "2023", "2024", "2019", "2021"}
    for year in set(re.findall(r"\b(?:19|20)\d{2}\b", text)):
        assert year in verified_years, year
    # The DPPHD and Governor's Office and TBT dated ranges are month-formatted
    # from the supplied values, so an unsupplied month is never invented.
    assert "Oct 2020 – Dec 2020" in text
    assert "Dec 2020 – Aug 2021" in text
    assert "May 2019 – Sep 2019" in text
    # The owner supplied "> 3" as a lower bound, so only the qualitative
    # phrasing may appear -- never an exact career total.
    assert re.search(r"\bmore than three years\b", text)
    assert not re.search(r"\b\d+(?:\.\d+)?\s*years\b", text)
    # No numeric achievements of any kind.
    # No numeric achievement claim: a count is only a fabrication when it is a
    # standalone number ("25 patients"), never part of a term like COVID-19.
    assert not re.search(r"(?<![\w-])\d+\s*(?:patients|beneficiaries|clinics|facilities|districts|staff|budget|people)\b", text, flags=re.IGNORECASE)
    assert not re.search(r"\d+\s*%", text)


# ---------------------------------------------------------------------------
# Real artifacts: TXT / DOCX / PDF
# ---------------------------------------------------------------------------


def test_real_master_cv_artifacts_render_complete_content(tmp_path):
    profile = _profile()
    master = write_master_cv(profile, out_dir=tmp_path)
    paths = master["generated_paths"]

    txt = Path(paths["txt"]).read_text(encoding="utf-8")
    docx_xml = _docx_xml(paths["docx"])
    docx_text = _docx_text(paths["docx"])
    pdf_text = _pdf_text(paths["pdf"])
    docx_flat = " ".join(docx_text.split())
    pdf_flat = " ".join(pdf_text.split())

    assert paths["docx"].endswith(".docx") and zipfile.is_zipfile(paths["docx"])
    assert Path(paths["pdf"]).read_bytes().startswith(b"%PDF")

    for rendered, flat in [(txt, " ".join(txt.split())), (docx_text, docx_flat), (pdf_text, pdf_flat)]:
        for section in MASTER_SECTIONS:
            assert section in rendered, (section, rendered[:120])
        for organization in REAL_ORGANIZATIONS:
            assert organization in flat, organization
        assert "Dr. Allah Yar Frotan" in flat
        assert "Medical Doctor / Health & Nutrition Specialist" in flat
        for entry in profile["work_history"]:
            for responsibility in _verified_responsibilities(entry):
                assert " ".join(responsibility.split()) in flat, responsibility
        for certificate in profile["certificates"]:
            assert certificate["name"] in flat, certificate["name"]
        # An unverified duty draft never reaches any employer-facing format.
        for _role, draft in _pending_responsibilities(profile):
            assert " ".join(draft.split()) not in flat, draft

    # Page count is content-driven: a comprehensive CV is at least two pages,
    # and the page numbers are visible in the footer of every page.
    pages = _pdf_pages(paths["pdf"])
    assert 2 <= pages <= 4, pages
    for number in range(1, pages + 1):
        assert f"Page {number}" in pdf_text
    # A multi-page CV must not end on a nearly empty page: the verified content
    # is laid out with a balanced vertical rhythm that keeps the last page
    # substantial. This never removes or adds content -- it guards the rhythm.
    assert _last_page_fill_ratio(paths["pdf"]) >= 0.45

    # DOCX pagination uses real Word fields, never a hard-coded page break.
    assert 'w:type="page"' not in docx_xml
    with zipfile.ZipFile(paths["docx"]) as archive:
        footer_parts = [name for name in archive.namelist() if name.startswith("word/footer")]
        assert footer_parts
        footer_xml = "".join(archive.read(name).decode("utf-8", errors="replace") for name in footer_parts)
    assert "PAGE" in footer_xml
    assert "Dr. Allah Yar Frotan" in footer_xml

    # No artifact leaks internal review vocabulary or private data.
    for flat in [docx_flat, pdf_flat]:
        for token in FORBIDDEN_EMPLOYER_FACING_TOKENS:
            assert token.lower() not in flat.lower(), token


def test_real_master_cv_pdf_has_no_giant_empty_trailing_page(tmp_path):
    master = write_master_cv(_profile(), out_dir=tmp_path)
    path = master["generated_paths"]["pdf"]
    with pdfplumber.open(path) as pdf:
        last = pdf.pages[-1]
        body = [char for char in last.chars if char.get("bottom", 0) < last.height - 45]
        assert body, "the final page must contain body text"
        span = max(char["bottom"] for char in body) - min(char["top"] for char in body)
        usable = last.height - 45 - 40
        # The final page of the shipped Master CV is substantially used.
        assert span / usable >= 0.4, span / usable


# ---------------------------------------------------------------------------
# Tailoring: downstream of the master CV, never mutating it
# ---------------------------------------------------------------------------


def test_tailored_cvs_are_substantive_and_keep_every_verified_fact(tmp_path):
    profile = _profile()
    before_fingerprint = json.dumps(profile, sort_keys=True, ensure_ascii=False)
    master_text_before = generate_master_cv(profile)["master_cv_text"]

    for job in [_medical_job(), _nutrition_job(), _safeguarding_job()]:
        report = match_job_against_profile(job, profile, today=TODAY).to_dict()
        docs = generate_tailored_documents(job, profile, report)
        model = docs["tailored_cv_model"]
        text = docs["tailored_cv_text"]

        assert len(model["experience"]) == 5  # every verified role stays
        assert len(docs["tailored_cv_text"].split()) >= 400
        for entry in profile["work_history"]:
            assert entry["title"] in text
            for responsibility in _verified_responsibilities(entry):
                assert responsibility in text, responsibility
        for certificate in profile["certificates"]:
            assert certificate["name"] in text
        # The verification gate holds identically for a tailored CV.
        for _role, draft in _pending_responsibilities(profile):
            assert draft not in text, draft
        # Tailored documents never mutate the canonical mapping.
        assert json.dumps(profile, sort_keys=True, ensure_ascii=False) == before_fingerprint

    # The Master CV is unchanged by tailoring and stays vacancy-neutral: no
    # vacancy title, employer, or target-role wording can appear in it.
    assert generate_master_cv(profile)["master_cv_text"] == master_text_before
    for token in ["Afghanistan Health Organization", "Afghanistan Nutrition Organization", "Humanitarian Health Organization", "recruitment@example.org", "jobs@example.org"]:
        assert token not in master_text_before, token


def test_tailoring_selects_and_reorders_evidence_rather_than_rewriting_it(tmp_path):
    profile = _profile()
    medical = generate_tailored_documents(
        _medical_job(), profile, match_job_against_profile(_medical_job(), profile, today=TODAY).to_dict()
    )
    nutrition = generate_tailored_documents(
        _nutrition_job(), profile, match_job_against_profile(_nutrition_job(), profile, today=TODAY).to_dict()
    )

    def group_order(model: dict) -> list[str]:
        return [group["group"] for group in model["expertise"]]

    assert group_order(medical["tailored_cv_model"]) != group_order(nutrition["tailored_cv_model"])
    assert group_order(nutrition["tailored_cv_model"])[0] == "Health & Nutrition Programming"
    assert group_order(medical["tailored_cv_model"])[0] in {"Clinical & Medical Practice", "Public Health Systems & Quality"}

    # Same evidence set in both: only the order/grouping changes.
    for key in ["education", "registration", "exit_exam", "certifications", "languages"]:
        assert medical["tailored_cv_model"][key] == nutrition["tailored_cv_model"][key]
    medical_bullets = sorted(b for entry in medical["tailored_cv_model"]["experience"] for b in entry["bullets"])
    nutrition_bullets = sorted(b for entry in nutrition["tailored_cv_model"]["experience"] for b in entry["bullets"])
    assert medical_bullets == nutrition_bullets


def test_safeguarding_vacancy_surfaces_verified_safeguarding_evidence():
    """Safeguarding tailoring emphasizes verified safeguarding evidence.

    The document layer is exercised directly because a pure safeguarding
    vacancy is deliberately classified NOT_ELIGIBLE by the matcher for a
    medical profile (no package may be produced for it). Tailoring itself must
    still lead with the verified safeguarding/PSEA/child-protection evidence.
    """
    profile = _profile()
    job = _safeguarding_job()
    report = match_job_against_profile(job, profile, today=TODAY).to_dict()
    docs = generate_tailored_documents(job, profile, report)
    cv = docs["tailored_cv_text"]
    summary = cv.split("PROFESSIONAL SUMMARY", 1)[1].split("\n\n", 1)[0]
    groups = [group["group"] for group in docs["tailored_cv_model"]["expertise"]]
    assert groups[0] == "Safeguarding, Protection & Compliance", groups

    assert "safeguarding" in summary.lower()
    assert "Safeguarding/PSEA" in cv
    assert "Child Protection" in cv
    assert "Safeguarding & PSEA — ACF — 2024" in cv
    # The verified scope line is what carries the safeguarding appointment: the
    # role title itself records the Focal Point appointment. The system-authored
    # duty clauses for that appointment are drafts and must stay out.
    assert "site appointment as Safeguarding Focal Point" in cv
    assert "Acted as site Safeguarding and PSEA Focal Point" not in cv


def test_tailored_cv_artifacts_render_and_stay_private(tmp_path):
    profile = _profile()
    job = _nutrition_job()
    report = match_job_against_profile(job, profile, today=TODAY).to_dict()
    bundle = prepare_application_bundle(job, profile, report, out_dir=tmp_path)
    cv_paths = bundle["generated_paths"]["tailored_cv"]

    txt = Path(cv_paths["txt"]).read_text(encoding="utf-8")
    docx_text = _docx_text(cv_paths["docx"])
    pdf_text = _pdf_text(cv_paths["pdf"])
    assert zipfile.is_zipfile(cv_paths["docx"])
    assert Path(cv_paths["pdf"]).read_bytes().startswith(b"%PDF")

    for rendered in [txt, docx_text, pdf_text]:
        flat = " ".join(rendered.split())
        assert "Dr. Allah Yar Frotan" in flat
        assert "REFERENCES" in rendered
        assert "Available on request for shortlisted applications." in flat
        for token in ["reference.person@example", SAMPLE_NAME, SAMPLE_EMAIL, "registration number", "license number"]:
            assert token.lower() not in flat.lower(), token

    assert 2 <= _pdf_pages(cv_paths["pdf"]) <= 4
    # Every section heading still exists in the rendered PDF (ATS-visible).
    pdf_flat = " ".join(pdf_text.split())
    for section in MASTER_SECTIONS:
        assert section in pdf_text, section
    assert "Health & Nutrition Programming" in pdf_flat


# ---------------------------------------------------------------------------
# Competency architecture
# ---------------------------------------------------------------------------


def test_expertise_groups_are_deterministic_and_complete():
    profile = _profile()
    skills = [item["name"] for item in _verified_skill_items(profile)]
    first = build_expertise_groups(skills)
    second = build_expertise_groups(skills)
    assert first == second
    assert [group["group"] for group in first] == EXPERTISE_GROUP_TITLES
    assert sorted(item for group in first for item in group["items"]) == sorted(skills)
    # No competency appears twice.
    flattened = [item for group in first for item in group["items"]]
    assert len(flattened) == len(set(flattened))
    # A vacancy key may reorder but never drop items.
    ranked = build_expertise_groups(skills, rank_key=lambda text: (0 if "imam" in text.lower() else 1, 0))
    assert sorted(item for group in ranked for item in group["items"]) == sorted(skills)


def test_canonical_profile_responsibilities_are_fact_anchored():
    """Verified responsibilities restate applicant-supplied facts only.

    Responsibilities are verification-gated: only an item carrying a literal
    ``verified: true`` is applicant experience. This test enforces the two
    release-blocking rules on the real profile:

    1. shape -- every role records applicant-supported scope, and every
       detailed duty is held in ``needs_verification`` instead;
    2. substance -- a verified line contains no numeric claim and no named
       entity (organisation, place, programme) that the applicant-supplied
       profile does not already record. Drafts are excluded from the anchor
       set, so a claim can never be validated against its own wording.
    """
    profile = _profile()
    applicant_facts = _applicant_supplied_facts(profile)
    # Entities the applicant supplied anywhere (used for the capitalised-token
    # check). Draft text is excluded here too.
    anchors = set(applicant_facts)

    for entry in profile["work_history"]:
        responsibilities = _verified_responsibilities(entry)
        assert responsibilities, entry["title"]
        assert entry["verified"] is True
        # The tracked profile records every duty in the verification-gated field
        # only. Free-form fields carry no per-item flag, so duty text parked
        # there would bypass the gate.
        for free_form in ("bullets", "duties", "achievements", "description"):
            assert not entry.get(free_form), (entry["title"], free_form, entry.get(free_form))
        for line in responsibilities:
            assert "  " not in line, line
            numeric = re.sub(r"COVID-?19", "COVID", line, flags=re.IGNORECASE)
            assert not re.search(r"\d", numeric), line
            for index, token in enumerate(re.findall(r"[A-Za-z][A-Za-z&/'-]{2,}", line)):
                if index == 0:
                    continue
                if token[0].isupper():
                    lowered = [part for part in re.split(r"[^a-z0-9]+", token.lower()) if part]
                    known = all(part in anchors for part in lowered)
                    assert known, (entry["title"], token, line, sorted(set(lowered) - anchors))
            for claim in ["increased", "reduced", "improved", "exceeded", "achieved", "awarded",
                          "recognized", "recognised", "doubled", "tripled", "saved", "secured",
                          "won", "ranked", "accredited", "certified by", "promoted"]:
                assert not re.search(rf"\b{claim}\b", line, flags=re.IGNORECASE), (entry["title"], claim, line)


def test_role_title_alone_cannot_verify_a_duty_clause():
    """The release-blocking audit finding, as a permanent regression guard.

    Every detailed duty in the five roles used to be system-authored from the
    verified role title, the verified skill inventory, and the verified
    certificates. Being a doctor does not supply "provided clinical assessment,
    diagnosis, and treatment"; holding an IPC certificate does not supply
    "applied infection prevention and control measures"; the ACF Safeguarding
    Focal Point title does not supply the safeguarding activities performed.

    Those clauses are now held in ``needs_verification``. This test fails if any
    of that duty vocabulary reappears in a verified responsibility without the
    applicant having supplied it.
    """
    profile = _profile()
    applicant_facts = _applicant_supplied_facts(profile)
    for entry in profile["work_history"]:
        for line in _verified_responsibilities(entry):
            unanchored = _unanchored_duty_terms(line, applicant_facts)
            assert not unanchored, (entry["title"], sorted(unanchored), line)


def test_duty_clause_guard_detects_a_reenabled_draft():
    """The guard above must bite: prove it fails on a reinstated draft.

    Without this, ``test_role_title_alone_cannot_verify_a_duty_clause`` could
    pass simply because its vocabulary never matches anything. Moving a real
    held-back draft into verified responsibilities must trip it.
    """
    import copy

    profile = copy.deepcopy(_profile())
    entry = profile["work_history"][0]
    draft = entry["needs_verification"][0]["text"]
    # Baseline: the guard is clean for the shipped profile.
    applicant_facts = _applicant_supplied_facts(profile)
    for line in _verified_responsibilities(entry):
        assert not _unanchored_duty_terms(line, applicant_facts)

    entry["responsibilities"].append({"text": draft, "verified": True})
    applicant_facts = _applicant_supplied_facts(profile)
    flagged = _unanchored_duty_terms(draft, applicant_facts)
    assert flagged, draft
    assert {"patients", "assessment", "diagnosis", "treatment"} <= flagged, sorted(flagged)


def test_unverified_responsibility_drafts_never_reach_a_document(tmp_path):
    """A draft is preserved and reported, never printed as verified experience."""
    profile = _profile()
    pending = _pending_responsibilities(profile)
    assert len(pending) == 28, len(pending)
    assert len({role for role, _ in pending}) == 5

    master = write_master_cv(profile, out_dir=tmp_path / "master")
    job = _medical_job()
    report = match_job_against_profile(job, profile, today=TODAY).to_dict()
    docs = generate_tailored_documents(job, profile, report)
    bundle = prepare_application_bundle(job, profile, report, out_dir=tmp_path / "tailored")

    surfaces = {
        "master": master["master_cv_text"],
        "tailored": docs["tailored_cv_text"],
        "cover_letter": docs["cover_letter"],
        "email": (docs.get("application_package", {}).get("email_draft") or {}).get("body", ""),
        "package_text": bundle["application_package"]["text"],
    }
    for name, text in surfaces.items():
        for _role, draft in pending:
            assert draft not in text, (name, draft)
            # Neither a distinctive fragment nor the wording of a draft.
            assert draft[:60] not in text, (name, draft[:60])

    # The owner is told, in plain terms, that the drafts are not published.
    for warnings in (master["review_warnings"], docs["review_warnings"]):
        joined = " ".join(warnings)
        assert "28 detailed responsibility draft(s)" in joined
        assert "NOT presented as verified experience" in joined


def test_responsibility_verification_gate_is_real(tmp_path):
    """The gate is enforced by the generator, not only asserted in profile.yaml."""
    import copy

    profile = copy.deepcopy(_profile())
    entry = profile["work_history"][0]
    draft = entry["needs_verification"][0]["text"]

    before = generate_master_cv(profile)["master_cv_text"]
    assert draft not in before

    # Owner confirms the line: it becomes verified content.
    entry["responsibilities"].append({"text": draft, "verified": True})
    after = generate_master_cv(profile)["master_cv_text"]
    assert draft in after

    # An explicit false is no better than a missing flag.
    entry["responsibilities"][-1]["verified"] = False
    assert draft not in generate_master_cv(profile)["master_cv_text"]

    # The shipped profile is untouched by this test's mutations.
    assert draft not in generate_master_cv(_profile())["master_cv_text"]


def test_tracked_profile_has_no_private_or_invented_precision_after_cv_work():
    """The canonical profile still contains no unsupported precision or PII."""
    raw = Path("profile.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    work = data["work_history"]
    assert len(work) == 5
    # ACF dates stay blank (never invented).
    assert work[0]["start"] == "" and work[0]["end"] == ""
    assert work[1]["start"] == "" and work[1]["end"] == ""
    # Every other role keeps exactly the supplied dates.
    assert [(item["start"], item["end"]) for item in work[2:]] == [
        ("2020-10", "2020-12"),
        ("2020-12", "2021-08"),
        ("2019-05", "2019-09"),
    ]
    assert data["license_registration"]["number"] == ""
    assert data["license_registration"]["issue_date"] == ""
    assert data["license_registration"]["expiry_date"] == ""
    assert data["license_registration"]["document_path"] == ""
    assert data["license_registration"]["authority"] == ""
    assert "professional_references" not in data
    assert "professional_references" not in raw
    assert data["personal"]["nationality"] == ""
    assert data["personal"]["gender"] == ""
    numeric = re.compile(r"(?<![\w-])\d+\s*(?:patients|beneficiaries|budget|USD|AFN|clinics)\b")
    for entry in work:
        # Neither verified scope nor the held-back drafts may carry invented
        # operational precision (counts, budgets, caseloads).
        for line in _verified_responsibilities(entry):
            assert not numeric.search(line), line
        for item in entry.get("needs_verification") or []:
            assert not numeric.search(str(item.get("text") or "")), item["text"]


def test_cover_letter_renders_signature_after_the_closing_paragraph(tmp_path):
    """A long verified letter must not place its signature above its own text.

    The cover letter is rendered as flowing content, so the closing paragraph,
    "Sincerely,", the name, and the contact lines always appear in that order in
    every format, no matter how long the verified evidence makes the letter.
    """
    profile = _profile()
    job = _nutrition_job()
    report = match_job_against_profile(job, profile, today=TODAY).to_dict()
    bundle = prepare_application_bundle(job, profile, report, out_dir=tmp_path)
    paths = bundle["generated_paths"]["cover_letter"]

    txt = Path(paths["txt"]).read_text(encoding="utf-8")
    docx_text = " ".join(_docx_text(paths["docx"]).split())
    pdf_text = " ".join(_pdf_text(paths["pdf"]).split())

    for flat in [docx_text, pdf_text]:
        closing = flat.index("Thank you for considering my application.")
        assert closing < flat.index("Sincerely,")
        # The signature name is the one that follows the closing paragraph, not
        # the letterhead at the top of the page.
        signature_name = flat.index("Dr. Allah Yar Frotan", closing)
        assert flat.index("Sincerely,") < signature_name < flat.index("Email: alfrotan@gmail.com")
        # The signature block is printed exactly once.
        assert flat.count("Sincerely,") == 1
        assert flat.count("Medical Doctor / Health & Nutrition Specialist") == 1

    # The canonical text keeps the same order and the letter still fits one page.
    assert txt.index("Sincerely,") < txt.rindex("Dr. Allah Yar Frotan")
    assert _pdf_pages(paths["pdf"]) == 1


#: The lead competency group each vacancy family must present first, derived
#: from the vacancy's own wording. This is the tailoring contract: the group
#: that names the vacancy's area leads, and every other group still follows.
LEAD_GROUP_MATRIX = [
    (
        (
            "Clinical Officer. Patient assessment, diagnosis, treatment, referral, clinical audit, "
            "infection prevention and control, and OPD services required."
        ),
        "Clinical & Medical Practice",
    ),
    (
        (
            "Medical Doctor (MD) required. Valid medical registration, Medical Exit Exam, three years clinical "
            "experience, patient assessment, diagnosis, treatment, infection prevention and control, clinical "
            "audit, and HMIS reporting required."
        ),
        "Clinical & Medical Practice",
    ),
    (
        "Nutrition Officer. SAM/MAM, CMAM, IYCF, nutrition screening and therapeutic feeding unit services required.",
        "Health & Nutrition Programming",
    ),
    (
        (
            "Health & Nutrition Supervisor. IMAM/CMAM, SAM/MAM, TFU/OTP, IYCF, outreach supervision, HMIS/DHIS2 "
            "reporting, MoPH coordination, medical supply forecasting, and field monitoring required."
        ),
        "Health & Nutrition Programming",
    ),
    (
        (
            "Health Programme Coordinator. Coordinate health programme implementation, supervise provincial "
            "teams, liaise with MoPH and government authorities, stakeholder engagement, monitoring, reporting, "
            "and field coordination required."
        ),
        "Programme Coordination & Field Operations",
    ),
    (
        "Medical Logistics Officer. Medical supply forecasting, stock management, and procurement required.",
        "Supply Chain, Logistics & Administration",
    ),
    (
        (
            "Safeguarding & PSEA Officer. Safeguarding, PSEA, child protection, awareness raising, reporting "
            "channels, and coordination with health programmes required."
        ),
        "Safeguarding, Protection & Compliance",
    ),
]


def test_each_vacancy_family_leads_with_its_own_competency_group():
    profile = _profile()
    verified = {item["name"] for item in _verified_skill_items(profile)}
    for index, (description, expected_lead) in enumerate(LEAD_GROUP_MATRIX):
        job = {
            "id": f"lead-group-{index}",
            "title": "Vacancy",
            "company": "Health Organization",
            "location": "Kabul",
            "url": f"https://jobs.example.org/lead-group-{index}",
            "apply_url": "hr@example.org",
            "description": f"{description} Apply to hr@example.org by 2026-12-31.",
            "metadata": {"closing_date": "2026-12-31"},
        }
        report = match_job_against_profile(job, profile, today=TODAY).to_dict()
        model = generate_tailored_documents(job, profile, report)["tailored_cv_model"]
        groups = model["expertise"]
        assert groups[0]["group"] == expected_lead, (description, [group["group"] for group in groups])
        # Emphasis changes; the evidence set never does.
        assert {item for group in groups for item in group["items"]} == verified
        assert len(model["experience"]) == len(profile["work_history"])


def test_common_vacancy_wording_maps_to_verified_competency_terms():
    """Employer wording must reach the verified competency it names.

    A vacancy that writes only the long form of an acronym still has to
    emphasize the verified competency, because the CV prints the verified
    acronym. Matching it is presentation; the evidence itself is unchanged.
    """
    profile = _profile()
    job = {
        "id": "long-form-wording",
        "title": "Infection Prevention and Control Officer",
        "company": "Health Organization",
        "location": "Kabul",
        "url": "https://jobs.example.org/long-form",
        "apply_url": "hr@example.org",
        "description": (
            "Infection prevention and control, patient safety, clinical audit, health data management, and "
            "capacity building for health staff required. Apply to hr@example.org by 2026-12-31."
        ),
        "metadata": {"closing_date": "2026-12-31"},
    }
    report = match_job_against_profile(job, profile, today=TODAY).to_dict()
    model = generate_tailored_documents(job, profile, report)["tailored_cv_model"]
    groups = [group["group"] for group in model["expertise"]]
    assert groups[0] == "Clinical & Medical Practice", groups
    assert "Infection Prevention and Control (IPC)" in " ".join(model["strengths"])
