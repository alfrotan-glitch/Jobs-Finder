from datetime import date

from utils.medical_requirements import extract_requirements_from_text, is_valid_application_url, looks_medical, parse_closing_date


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


def test_healthcare_project_management_years_are_not_misclassified_as_clinical():
    text = "Medical degree (MD) and valid medical license. Minimum 3 years healthcare project management experience."
    result = extract_requirements_from_text(text, title="Technical Supervisor", today=date(2026, 9, 30))
    year_reqs = {req.key: req.value for req in result.requirements if req.key.endswith("_experience_years")}
    assert year_reqs["management_experience_years"] == 3
    assert "clinical_experience_years" not in year_reqs


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


def test_gender_requirement_title_overrides_contradictory_body_copy():
    result = extract_requirements_from_text(
        "The Female Medical Doctor is responsible for outpatient care. MD degree and completion of exit exam required.",
        title="Medical Doctor (Male)",
        today=date(2026, 9, 30),
    )
    assert result.facts["gender_requirement"] == "male"


def test_extracts_medical_council_exam_and_generic_specialist_requirements():
    exit_exam = extract_requirements_from_text(
        "داشتن دیپلوم طبابت و امتحان شورای طبی را سپری کرده باشد.",
        title="Medical Doctor/In-charge",
        today=date(2026, 9, 30),
    )
    assert "medical_exit_exam" in {req.key for req in exit_exam.requirements}

    specialist = extract_requirements_from_text(
        "Medical Doctor – Dermatology & Aesthetic Medicine requires skin health and dermatology expertise.",
        title="Medical Doctor – Dermatology & Aesthetic Medicine",
        today=date(2026, 9, 30),
    )
    assert "medical_specialist" in {req.key for req in specialist.requirements}

    cardiology = extract_requirements_from_text(
        "MD/MBBS with postgraduate specialty qualification in Cardiology; fellowship/certification in Interventional Cardiology.",
        title="Cardiology Specialist Doctor",
        today=date(2026, 9, 30),
    )
    assert "medical_specialist" in {req.key for req in cardiology.requirements}


def test_female_point_plus_is_preference_not_hard_requirement_without_is():
    result = extract_requirements_from_text(
        "The female candidate point plus.",
        title="Quality of Care Officer",
        today=date(2026, 9, 30),
    )
    assert result.facts["gender_requirement"] == "female_encouraged"
    req = [req for req in result.requirements if req.key == "gender_requirement"][0]
    assert req.criticality == "important"


def test_subject_title_instruction_becomes_deterministic_subject_but_missing_vacancy_number_blocks():
    title_only = extract_requirements_from_text(
        "Please mention the job title in the email subject line. Email / Application Form: jobs@example.org",
        title="Medical Officer",
        today=date(2026, 9, 30),
    )
    assert title_only.facts["application_subject"] == "Medical Officer"
    assert title_only.facts["application_subject_required"] is True

    missing_number = extract_requirements_from_text(
        "Indicating the job title and vacancy number of the position in the email subject line. Email / Application Form: jobs@example.org",
        title="TFU Nutrition Assistant",
        today=date(2026, 9, 30),
    )
    assert missing_number.facts["application_subject"] is None
    assert missing_number.facts["application_subject_required"] is True


def test_license_number_and_document_requirements_are_distinct_from_generic_license():
    generic = extract_requirements_from_text(
        "Job Requirements: MD with valid medical license/registration required.",
        title="Medical Doctor",
        today=date(2026, 9, 30),
    )
    generic_keys = {req.key for req in generic.requirements}
    assert "license_registration" in generic_keys
    assert "license_number" not in generic_keys
    assert "license_document" not in generic_keys

    numbered = extract_requirements_from_text(
        "Job Requirements: MD with valid medical registration. Candidates must enter their medical registration number in the application form.",
        title="Medical Doctor",
        today=date(2026, 9, 30),
    )
    numbered_keys = {req.key for req in numbered.requirements}
    assert "license_registration" in numbered_keys
    assert "license_number" in numbered_keys

    documented = extract_requirements_from_text(
        "Submission: Please attach a copy of your medical license certificate with the application.",
        title="Medical Doctor",
        today=date(2026, 9, 30),
    )
    assert "license_document" in {req.key for req in documented.requirements}


def test_dari_email_title_and_position_code_instruction_requires_subject():
    result = extract_requirements_from_text(
        "لطف نموده اسناد را به ایمیل ارسال نمایید. هنگام ارسال اسناد از طریق ایمیل، درج عنوان و کُد بست مربوطه الزامی است.",
        title="Technical Assistant",
        today=date(2026, 9, 30),
    )
    assert result.facts["application_subject_required"] is True
    assert result.facts["application_subject"] is None


def test_english_position_code_instruction_requires_exact_subject():
    result = extract_requirements_from_text(
        "Application by email hr@example.org; indicating the job title and vacancy number/position code in the email subject line is mandatory, but the exact code was not exposed.",
        title="Technical Assistant",
        today=date(2026, 9, 30),
    )
    assert result.facts["application_subject_required"] is True
    assert result.facts["application_subject"] is None


def test_international_unv_nationality_requirement_is_extracted():
    result = extract_requirements_from_text(
        "Nationality: Candidate must be a national of a country other than the country of assignment.",
        title="Medical Doctor",
        today=date(2026, 9, 30),
    )
    assert result.facts["nationality_requirement"] == "International"


def test_position_you_are_applying_for_instruction_uses_job_title_as_subject():
    result = extract_requirements_from_text(
        "Please ensure to mention the position you are applying for, in the subject line of your E-mail. Email: jobs@example.org",
        title="Medical Doctor (MD)",
        today=date(2026, 9, 30),
    )
    assert result.facts["application_subject_required"] is True
    assert result.facts["application_subject"] == "Medical Doctor (MD)"


def test_patient_registration_is_not_professional_license_requirement():
    result = extract_requirements_from_text(
        "Ensure proper registration of patients' information and maintain patient records.",
        title="Medical Doctor",
        today=date(2026, 9, 30),
    )
    assert "license_registration" not in {req.key for req in result.requirements}


def test_surgeon_roles_are_treated_as_medical_relevant():
    assert looks_medical("Surgeon required for hospital surgical ward")


def test_surgery_specialty_certificate_blocks_ready_until_verified():
    result = extract_requirements_from_text(
        "Job Requirements: graduate of recognized medical faculty and specialty certificate in general surgery.",
        title="Surgeon",
        today=date(2026, 9, 30),
    )
    assert "medical_specialist" in {req.key for req in result.requirements}


def test_nursing_vaccination_psychosocial_and_quality_requirements_are_extracted():
    nurse = extract_requirements_from_text(
        "Job Requirements: Bachelor's degree in Clinical Nursing and valid nursing license required.",
        title="Nurse",
        today=date(2026, 9, 30),
    )
    assert "nursing_midwifery_certificate" in {req.key for req in nurse.requirements}

    vaccinator = extract_requirements_from_text(
        "Job Requirements: Ministry vaccination certificate is required.",
        title="Vaccinator",
        today=date(2026, 9, 30),
    )
    assert "vaccination_certificate" in {req.key for req in vaccinator.requirements}

    counselor = extract_requirements_from_text(
        "Requirements: 3+ years as counsellor dealing with CP, GBV and PwSN; provide psychological support.",
        title="Mental Health Promoter",
        today=date(2026, 9, 30),
    )
    assert "psychosocial_counseling" in {req.key for req in counselor.requirements}

    quality = extract_requirements_from_text(
        "Knowledge of QA/QI, clinical/service audit, patient safety and quality improvement is required.",
        title="Quality of Care Officer",
        today=date(2026, 9, 30),
    )
    assert "quality_improvement" in {req.key for req in quality.requirements}


def test_relevant_public_health_education_requirement_is_extracted():
    result = extract_requirements_from_text(
        "Job Requirements: Relevant education in social sciences, public health, and community development.",
        title="Social Mobilizer",
        today=date(2026, 9, 30),
    )
    assert "health_public_education" in {req.key for req in result.requirements}
