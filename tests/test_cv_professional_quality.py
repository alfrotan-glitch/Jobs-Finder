"""Professional CV quality contract for the real canonical profile.

These tests protect the *product output*, not just the Python functions. They
generate real TXT/DOCX/PDF artifacts from the shipped canonical profile and
assert the guarantees that make the CV usable for a real medical / health /
nutrition application:

* the Master CV is comprehensive (profile, grouped competencies, complete role
  descriptions, education, registration, exit exam, certifications, languages,
  a reference line) and long enough to be a serious CV;
* every verified responsibility, certificate, and language survives into the
  rendered TXT, DOCX and PDF;
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


def _pdf_text(path: str | Path) -> str:
    with pdfplumber.open(str(path)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _pdf_pages(path: str | Path) -> int:
    with pdfplumber.open(str(path)) as pdf:
        return len(pdf.pages)


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
    for item in model["experience"]:
        assert len(item["bullets"]) >= 4, item["role"]
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
        for responsibility in entry["responsibilities"]:
            assert responsibility in text, responsibility
    # The professional profile must not be a thin one-liner.
    assert len(text.split("PROFESSIONAL SUMMARY", 1)[1].split("\n\n", 1)[0].split()) >= 90
    assert len(text.split()) >= 800


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
            for responsibility in entry["responsibilities"]:
                assert " ".join(responsibility.split()) in flat, responsibility
        for certificate in profile["certificates"]:
            assert certificate["name"] in flat, certificate["name"]

    # Page count is content-driven: a comprehensive CV is at least two pages,
    # and the page numbers are visible in the footer of every page.
    pages = _pdf_pages(paths["pdf"])
    assert 2 <= pages <= 4, pages
    for number in range(1, pages + 1):
        assert f"Page {number}" in pdf_text

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
        assert len(docs["tailored_cv_text"].split()) >= 700
        for entry in profile["work_history"]:
            assert entry["title"] in text
            for responsibility in entry["responsibilities"]:
                assert responsibility in text, responsibility
        for certificate in profile["certificates"]:
            assert certificate["name"] in text
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
    assert "Acted as site Safeguarding and PSEA Focal Point" in cv


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
    """Role responsibilities must not introduce new factual entities.

    Responsibilities are the owner-confirmable professional description of a
    role. This test enforces that they stay SCOPE statements: no numeric claim
    (count, budget, percentage, duration), and no named entity (organisation,
    place, institution, or programme) that the *rest* of the verified profile
    does not already record. Descriptive duty vocabulary is allowed; new facts
    are not.

    Entities are read from every profile section except the per-role
    responsibility/bullet text itself -- otherwise the check would validate a
    claim against the claim.
    """
    profile = _profile()
    # Vocabulary available to responsibilities: everything verified elsewhere in
    # the profile (identity, education, work titles/employers/locations, skills,
    # certificates, languages, evidence dimensions) and nothing else.
    anchors: set[str] = set()

    def absorb(value) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"responsibilities", "bullets", "description", "duties", "achievements"}:
                    continue
                absorb(child)
        elif isinstance(value, list):
            for child in value:
                absorb(child)
        elif value not in (None, ""):
            anchors.update(re.findall(r"[a-z0-9]+", str(value).lower()))

    absorb(profile)

    # Professional scope vocabulary that is generic to the medical / health /
    # nutrition / humanitarian sector rather than a new factual claim, plus
    # ordinary function words and neutral verb/adverb forms.
    sector_vocabulary = {"clinical", "assessment", "diagnosis", "treatment", "patient", "patients", "care", "case",
        "protocol", "protocols", "national", "unit", "inpatient", "outpatient", "activity", "activities", "progress",
        "severe", "acute", "malnutrition", "therapeutic", "feeding", "coverage", "areas", "identification",
        "linkage", "adherence", "implementation", "delivery", "quality", "documentation", "records", "registers",
        "corrective", "actions", "providers", "staff", "work", "planning", "coaching", "training", "visits",
        "availability", "forecasting", "stock", "supply", "supplies", "logistics", "coordination", "meetings",
        "counterparts", "authority", "authorities", "facilities", "facility", "community", "communities",
        "representatives", "awareness", "channels", "compliance", "policy", "organizational", "prevention",
        "control", "measures", "outbreak", "response", "rapid", "reporting", "reports", "data", "situation",
        "provincial", "district", "districts", "paperwork", "expenditure", "payments", "procurement", "filing",
        "administrative", "operations", "colleagues", "external", "internal", "procedures", "responsible", "officer",
        "official", "information", "materials", "engagement", "sharing", "public", "relations", "communications",
        "structure", "structures", "aligned", "element", "site", "focal", "point", "role", "position", "scope",
        "partners", "sector", "sectors", "stakeholders", "actors", "teams", "programmes", "programs", "projects",
        "services", "responsibilities", "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "by", "for",
        "from", "with", "as", "into", "onto", "within", "across", "including", "during", "their", "its", "this",
        "that", "these", "those", "all", "both", "up", "through", "while", "such", "per", "line", "accordance",
        "alignment", "follow", "followup", "link", "sexual", "exploitation", "abuse", "protection", "child",
        "infection", "integrated", "based", "management", "system", "systems", "health", "nutrition", "infant",
        "young", "practices", "basic", "package", "essential", "hospital", "supported", "supporting", "led",
        "shared", "raised", "conducted",
    }

    for entry in profile["work_history"]:
        responsibilities = entry.get("responsibilities") or []
        assert responsibilities, entry["title"]
        assert entry["verified"] is True
        for line in responsibilities:
            assert "  " not in line, line
            numeric = re.sub(r"COVID-?19", "COVID", line, flags=re.IGNORECASE)
            assert not re.search(r"\d", numeric), line
            # Named entities: any capitalised word, or any organisation/place
            # noun, must already be recorded elsewhere in the verified profile.
            for index, token in enumerate(re.findall(r"[A-Za-z][A-Za-z&/'-]{2,}", line)):
                if index == 0:
                    continue
                if token[0].isupper():
                    lowered = [part for part in re.split(r"[^a-z0-9]+", token.lower()) if part]
                    known = all(part in anchors or part in sector_vocabulary for part in lowered)
                    assert known, (entry["title"], token, line, sorted(set(lowered) - anchors - sector_vocabulary))
            for noun in ["hospital", "university", "ministry", "institute", "company", "agency", "clinic",
                         "academy", "college", "school", "bank", "foundation", "village", "region", "city",
                         "district", "province", "directorate", "ngo", "ingo", "unicef", "unhcr", "iom"]:
                if re.search(rf"\b{noun}\b", line, flags=re.IGNORECASE):
                    assert noun in anchors, (entry["title"], noun, line)
            # Unsupported achievement/result wording must never be introduced by
            # a responsibility line.
            for claim in ["increased", "reduced", "improved", "exceeded", "achieved", "awarded",
                          "recognized", "recognised", "doubled", "tripled", "saved", "secured",
                          "won", "ranked", "accredited", "certified by", "promoted"]:
                assert not re.search(rf"\b{claim}\b", line, flags=re.IGNORECASE), (entry["title"], claim, line)


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
    for entry in work:
        for line in entry.get("responsibilities") or []:
            assert not re.search(r"(?<![\w-])\d+\s*(?:patients|beneficiaries|budget|USD|AFN|clinics)\b", line), line


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
