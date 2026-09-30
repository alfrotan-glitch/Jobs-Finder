from datetime import date

from utils.medical_requirements import extract_requirements_from_text, is_valid_application_url, parse_closing_date


def test_extract_medical_requirements_and_application_facts():
    text = """
    Vacancy No: MOPH-HEALTH-2026-09
    Position: Medical Officer, Kabul field team.
    Requirements: MD or MBBS degree, valid medical license/registration, minimum 3 years of clinical experience.
    Experience with Afghanistan BPHS, HMIS, IMNCI, nutrition and reporting is required.
    English, Dari and Pashto are required. Afghan nationals only. Female applicants only.
    Closing date: 30 September 2026.
    Apply by email to jobs@example.org. Subject line: Medical Officer - MOPH-HEALTH-2026-09
    """
    result = extract_requirements_from_text(text, title="Medical Officer", location="Kabul", today=date(2026, 9, 29))
    keys = {req.key for req in result.requirements}

    assert "md_degree" in keys
    assert "license_registration" in keys
    assert "clinical_experience_years" in keys
    assert "bphs" in keys
    assert "hmis" in keys
    assert "imnci" in keys
    assert "nutrition" in keys
    assert "reporting" in keys
    assert "language_english" in keys
    assert "language_dari" in keys
    assert "language_pashto" in keys
    assert result.facts["reference_number"] == "MOPH-HEALTH-2026-09"
    assert result.facts["application_email"] == "jobs@example.org"
    assert result.facts["application_subject"] == "Medical Officer - MOPH-HEALTH-2026-09"
    assert result.facts["closing_date"] == "2026-09-30"
    assert result.facts["gender_requirement"] == "female"
    assert result.facts["nationality_requirement"] == "Afghan"


def test_closing_date_parsing_formats():
    today = date(2026, 9, 29)
    assert parse_closing_date("Deadline: 2026-10-01", today=today) == "2026-10-01"
    assert parse_closing_date("Closing date: 01/10/2026", today=today) == "2026-10-01"
    assert parse_closing_date("Apply by: October 1, 2026", today=today) == "2026-10-01"


def test_invalid_application_url_detection():
    assert is_valid_application_url("https://example.org/apply")
    assert not is_valid_application_url("not a url")
    assert not is_valid_application_url("")


def test_acbar_application_form_url_is_prioritized_over_source_fallback():
    text = """
    Submission Guideline: Application Form: https://forms.gle/U3dJcBHhJamUZ5yE9
    Deadline: 2026-10-08
    """
    result = extract_requirements_from_text(
        text,
        title="Technical Supervisor",
        location="Takhar",
        source_url="https://www.acbar.org/en/jobs/details/145872/technical-supervisor",
        application_url="https://www.acbar.org/en/jobs/details/145872/technical-supervisor",
        today=date(2026, 9, 30),
    )
    assert result.facts["application_url"] == "https://forms.gle/U3dJcBHhJamUZ5yE9"
    assert result.facts["closing_date"] == "2026-10-08"


def test_year_range_uses_lower_bound_not_upper_bound():
    text = "Minimum 3-5 years of progressively responsible experience in health program management."
    result = extract_requirements_from_text(text, title="Technical Assistant", today=date(2026, 9, 30))
    year_reqs = {req.key: req.value for req in result.requirements if req.key.endswith("_experience_years")}
    assert year_reqs["management_experience_years"] == 3


def test_gender_preference_vs_hard_requirement_detection():
    preferred = extract_requirements_from_text(
        "The female candidate is point plus.", title="Quality Officer", today=date(2026, 9, 30)
    )
    assert preferred.facts["gender_requirement"] == "female_encouraged"

    hard = extract_requirements_from_text(
        "Specialist of oby/gyn, Female MD, Midwife; the shortlisted candidates must be female.",
        title="Clinical Mentor",
        today=date(2026, 9, 30),
    )
    assert hard.facts["gender_requirement"] == "female"
    assert "specialist_obgyn" in {req.key for req in hard.requirements}


def test_dari_digits_and_year_word_for_health_management_experience():
    text = "تجربه کاری حد اقل ۵ سال مرتبط و در بخش مدیریت برنامه های صحی"
    result = extract_requirements_from_text(text, title="آمرکلینیک های ثابت", today=date(2026, 9, 30))
    year_reqs = {req.key: req.value for req in result.requirements if req.key.endswith("_experience_years")}
    assert year_reqs["management_experience_years"] == 5


def test_extracts_nursing_pediatric_and_pharmacy_specific_credentials():
    nurse = extract_requirements_from_text(
        "Job Requirements: Nursing/Midwifery certificate is required. 2+ years of relevant work experience.",
        title="Nurse Nutrition",
        today=date(2026, 9, 30),
    )
    assert "nursing_midwifery_certificate" in {req.key for req in nurse.requirements}

    pediatric = extract_requirements_from_text(
        "Job Requirements: MD with Specialty Degree (Pediatrics). At least three years of relevant experience.",
        title="Pediatrics Specialist",
        today=date(2026, 9, 30),
    )
    assert "pediatric_specialist" in {req.key for req in pediatric.requirements}

    pharmacy = extract_requirements_from_text(
        "Job Requirements: Bachelor's degree in pharmacy from a recognized university. At least 3 years of relevant experience for pharmacists.",
        title="Pharmacy Officer",
        today=date(2026, 9, 30),
    )
    reqs = {req.key: req for req in pharmacy.requirements}
    assert "pharmacy_degree" in reqs
    assert reqs["pharmacy_experience_years"].value == 3


def test_reference_extraction_ignores_clinical_or_prose_slash_phrases():
    assert extract_requirements_from_text(
        "Work in OPD/IPD/emergency departments. Mention the job title in the email subject.",
        title="Pediatrics Specialist",
        today=date(2026, 9, 30),
    ).facts["reference_number"] is None
    assert extract_requirements_from_text(
        "RMNCAH/SRH/PSS services and absent/sick/long-stay tracing are described.",
        title="Pharmacy Officer",
        today=date(2026, 9, 30),
    ).facts["reference_number"] is None
    assert extract_requirements_from_text(
        "Mention the announced position vacancy number in the email subject like RI-NIM-SAFE-2026-13.",
        title="Quality Officer",
        today=date(2026, 9, 30),
    ).facts["reference_number"] == "RI-NIM-SAFE-2026-13"


def test_pharmacy_alternative_years_uses_lower_applicable_track():
    result = extract_requirements_from_text(
        "Job Requirements: Bachelor's degree in pharmacy. At least 3 years of relevant experience for pharmacists or 5 years of relevant experience for pharmacy technicians.",
        title="Pharmacy Officer",
        today=date(2026, 9, 30),
    )
    year_reqs = {req.key: req.value for req in result.requirements if req.key.endswith("_experience_years")}
    assert year_reqs["pharmacy_experience_years"] == 3
