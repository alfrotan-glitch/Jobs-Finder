from datetime import date

from utils.medical_matcher import MET, NEEDS_VERIFICATION, match_job_against_profile
from utils.profile import build_profile_evidence, infer_years_from_history
from utils.profile_builder import build_profile_from_cv_text


SOURCE_CV_EXCERPT = """
DR. ALLAH YAR FROTAN
Medical Doctor · Health & Nutrition Program Coordination
Kabul, Afghanistan · +93 000 000 000 · doctor@example.org
PROFESSIONAL PROFILE
Medical Doctor with over three years of combined field and supervisory experience across Daikundi Province's health, nutrition, and provincial governance sectors.
Proven track record supervising mobile health and nutrition teams delivering BPHS/EPHS and IMAM/CMAM services, maintaining HMIS/DHIS2 reporting and data quality, coordinating medical supply forecasting and logistics, safeguarding (PSEA and Child Protection Focal Point), and cross-sector communication during the COVID-19 emergency response.
Native Dari (Persian) speaker with fluent English and intermediate Pashto.
CORE COMPETENCIES
 * Provincial & Ministry of Public Health Stakeholder Coordination
 * Health & Nutrition Program Supervision
 * Team Supervision & Capacity Building
 * HMIS / DHIS2 Reporting & Data Quality
 * Emergency & Outbreak Response (COVID-19)
 * Safeguarding, PSEA & Child Protection
 * BPHS/EPHS & IMAM/CMAM Program Knowledge
PROFESSIONAL EXPERIENCE
TFU Medical Doctor & Safeguarding Focal Point
Action Against Hunger (ACF-International) · Sang-e-Takht TFU, Daikundi | May 2023 – Jul 2025
 * Maintained accurate HMIS records and served as Safeguarding Focal Point supporting PSEA and child protection.
 * Delivered clinical assessment, diagnosis, treatment, and follow-up care for children with SAM applying WHO, IMAM/CMAM, and national clinical protocols.
Health and Nutrition Supervisor
Action Against Hunger (ACF-International) · Gizab & Sang-e-Takht, Daikundi | Feb 2022 – Dec 2022
 * Supervised mobile health and nutrition teams delivering community-based BPHS/EPHS-related services.
Medical Doctor / COVID-19 Rapid Response Team Leader
Daikundi Provincial Public Health Directorate · Daikundi, Afghanistan | Oct 2020 – Dec 2020
 * Coordinated with Ministry of Public Health representatives, provincial health authorities, and partner organizations.
Public Relations & Communications Advisor
Daikundi Governor's Office · Daikundi, Afghanistan | Dec 2020 – Aug 2021
 * Supported communication and coordination between provincial government departments, NGOs, communities, and development partners.
Administrative and Finance Officer
Trend for a Better Tomorrow (TBT) – NGO · Afghanistan | May 2019 – Sep 2019
 * Supported administrative operations, procurement processes, financial documentation, and program logistics.
EDUCATION
Doctor of Medicine (MD), Curative Medicine
Kabul Medical Science University · 2013 – 2020
CERTIFICATIONS & TRAINING
 * Safeguarding & PSEA — ACF (2024)
 * Infection Prevention & Control (IPC) — ACF (2023)
 * HMIS Reporting & Health Data Management — ACF (2023)
 * IMAM, IMNCI, IYCF & Stock Management — ACF (2022)
LANGUAGES
Dari / Persian — Native | English — Fluent | Pashto — Intermediate
PROFESSIONAL REFERENCES
Available upon request
"""


def test_build_dr_frotan_profile_from_source_cv():
    profile = build_profile_from_cv_text(SOURCE_CV_EXCERPT, resume_path="cv.txt")
    assert profile["personal"]["first_name"] == "Allah Yar"
    assert profile["personal"]["last_name"] == "Frotan"
    assert len(profile["work_history"]) == 5
    assert profile["license_registration"]["verified"] is False
    assert "Needs verification" in profile["license_registration"]["status"]


def test_dr_frotan_evidence_and_conservative_experience_from_dates():
    profile = build_profile_from_cv_text(SOURCE_CV_EXCERPT, resume_path="cv.txt")
    evidence = build_profile_evidence(profile, resume_text=SOURCE_CV_EXCERPT, today=date(2026, 9, 29))
    assert evidence.has("md_degree")
    assert evidence.has("bphs")
    assert evidence.has("ephs")
    assert evidence.has("hmis")
    assert evidence.has("imam")
    assert evidence.has("safeguarding_psea")
    assert evidence.has("moph_coordination")
    assert evidence.has("language_dari")
    assert evidence.has("language_english")
    assert evidence.has("language_pashto")
    clinical_years = infer_years_from_history(profile, kind="clinical", today=date(2026, 9, 29))
    assert clinical_years >= 3.0
    assert clinical_years < 4.0


def test_dr_frotan_match_needs_license_verification_not_fabricated():
    profile = build_profile_from_cv_text(SOURCE_CV_EXCERPT, resume_path="cv.txt")
    job = {
        "id": "provincial-coordinator",
        "title": "Provincial Coordinator Health and Nutrition",
        "company": "Health NGO",
        "location": "Daikundi",
        "url": "https://example.org/job",
        "apply_url": "https://example.org/apply",
        "platform": "test",
        "description": """
        Provincial Coordinator role requires MD, valid medical registration, at least 3 years clinical experience,
        MoPH coordination, BPHS/EPHS, HMIS/DHIS2, IMAM/CMAM, safeguarding/PSEA, reporting, English, Dari and Pashto.
        Closing date: 30 September 2026.
        """,
        "metadata": {},
    }
    report = match_job_against_profile(job, profile, resume_text=SOURCE_CV_EXCERPT, today=date(2026, 9, 29)).to_dict()
    statuses = {item["key"]: item["status"] for item in report["requirement_matches"]}
    assert statuses["md_degree"] == MET
    assert statuses["clinical_experience_years"] == MET
    assert statuses["moph_coordination"] == MET
    assert statuses["hmis"] == MET
    assert statuses["imam"] == MET
    assert statuses["safeguarding_psea"] == MET
    assert statuses["license_registration"] == NEEDS_VERIFICATION
