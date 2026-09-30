#!/usr/bin/env python3
"""Ingest live verified vacancy pages into the existing Jobs-Finder workflow.

The normal in-repo network discovery was run first and failed in this sandbox at
TLS handshake for all active HTTPS sources. This runner does not add a new
architecture: it feeds live page evidence (official/source URLs retained) into
existing Job -> watcher -> matcher -> document package code paths.
"""
from __future__ import annotations

import asyncio
import json
import runpy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from utils.discovery import Job
from utils.job_watcher import (
    READY_TO_APPLY,
    NEEDS_VERIFICATION,
    NOT_ELIGIBLE,
    get_actionable_opportunities,
    get_watcher_jobs,
    prepare_application_for_watcher_job,
    run_job_watch_scan,
)
from utils.profile_builder import build_profile_from_cv_text
from utils.source_registry import active_sources_for_discovery, load_source_registry, validate_source_registry
from utils import tracker

RUN_DATE = date(2026, 9, 30)
OUT_DIR = Path("documents/live_market_test_2026-09-30")
REPORT_JSON = Path("docs/live_market_run_2026-09-30.json")
REPORT_MD = Path("docs/live_market_run_2026-09-30.md")
SOURCE_RUN_JSON = Path("docs/live_market_test_2026-09-30.json")


def build_profile() -> tuple[dict[str, Any], str]:
    cv_text = runpy.run_path("tests/test_dr_frotan_profile.py")["SOURCE_CV_EXCERPT"]
    profile = build_profile_from_cv_text(cv_text, resume_path="live_profile_cv_excerpt.txt")
    profile.setdefault("source_registry", {})
    profile["source_registry"].update({"enabled": True, "path": "docs/source_registry.json", "disabled_source_ids": [], "enabled_source_ids": []})
    profile.setdefault("watcher", {})
    profile["watcher"].update({"enabled": True, "scan_interval_hours": 6, "deadline_alert_days": [7, 3, 1], "auto_prepare_ready_to_apply": False, "application_out_dir": str(OUT_DIR)})
    profile.setdefault("notifications", {})
    profile["notifications"].update({"new_jobs": True, "needs_verification": True, "deadline_alerts": True, "updates": True, "closed": True, "source_failures": True})
    profile.setdefault("preferences", {})
    profile["preferences"].update({
        "roles": ["Medical Officer", "Medical Doctor", "Physician", "Health Officer", "Nutrition Officer", "Public Health", "Health and Nutrition", "Clinical", "HMIS", "BPHS", "EPHS", "IMAM", "IMNCI"],
        "locations": ["Afghanistan", "Kabul", "Daikundi", "Nangarhar", "Kunar", "Takhar", "Zabul", "Baghlan", "Kandahar", "Nimruz", "Herat", "Mazar-i-Sharif"],
        "preferred_locations": ["Kabul", "Daikundi"],
        "willing_to_relocate": True,
        "field_deployment": True,
    })
    profile.setdefault("search", {})
    profile["search"]["generic_job_boards_enabled"] = False
    return profile, cv_text


def live_job(
    job_id: str,
    title: str,
    company: str,
    location: str,
    source_url: str,
    apply_url: str,
    source: str,
    description: str,
    closing: str = "",
    *,
    reliability: str = "medium",
    reference: str = "",
    application_email: str = "",
    special_instructions: list[str] | None = None,
    provenance_note: str = "Live page verified by Arena fetch_page on 2026-09-30",
) -> Job:
    metadata = {
        "source": source,
        "source_url": source_url,
        "original_vacancy_url": source_url,
        "source_urls": [source_url] + ([apply_url] if apply_url and apply_url.startswith("http") and apply_url != source_url else []),
        "source_reliability": reliability,
        "source_provenance": [{"source": source, "url": source_url, "reliability": reliability, "note": provenance_note}],
        "closing_date": closing,
        "reference_number": reference,
    }
    if application_email:
        metadata["application_email"] = application_email
    if special_instructions:
        metadata["special_instructions"] = special_instructions
    return Job(
        id=job_id,
        title=title,
        company=company,
        location=location,
        url=source_url,
        apply_url=apply_url,
        platform=source,
        description=description.strip() + (f"\nClosing date: {closing}." if closing else ""),
        metadata=metadata,
    )


def live_verified_jobs() -> list[Job]:
    jobs = [
        live_job(
            "fmic-medical-officer-2026-571",
            "Medical Officer",
            "French Medical Institute for Mothers and Children (FMIC)",
            "Kabul, Afghanistan",
            "https://www.fmic.org.af/WorkWithUs/vacancies/Pages/Medical-Officer-2026.aspx",
            "https://docs.google.com/forms/d/1doS8XyeEEV_aQ7FUW5tnrBSPTJtgHgk1UHm4mjReYQM/edit",
            "fmic",
            "Vacancy Number FMIC/HR/571. Number of positions 2. Medical Officer delivers patient consultations, assessment, diagnosis, treatment, documentation, emergency response, SafeCare standards, infection control, patient safety, quality improvement, on-call rotations and multidisciplinary care. Requirements: Medical Degree from a recognized university, Registered with Afghan Medical Council (AMC), 1-2 years clinical experience in a hospital setting, understanding of SafeCare standards, clinical protocols, infection control, patient safety, Pashto Dari English, MS Office. Application through Google Form; make sure to press submit at the end; certificates only if selected.",
            "2026-10-05",
            reliability="high",
            reference="FMIC/HR/571",
        ),
        live_job(
            "acbar-cha-medical-doctor-nawbahar-shahjoy-145911",
            "Medical Doctor (Nawbahar BHC Fixed & Shahjoy DH Backup)",
            "Coordination of Humanitarian Assistance (CHA)",
            "Zabul, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145911/medical-doctor-nawbahar-bhc-fixed-shahjoy-dh-backup",
            "https://cha-net.org/jobs/application-form/medical-doctor-nawbahar-chc-fixed-shahjoy-dh-backup-6abc918cf1bd390013be91d0",
            "acbar",
            "Medical Doctor role in CHA health facility. Duties include triage, patient history and examination, rational prescriptions, clinic coordination, disease data, staff management/supervision, BPHS services, IMCI, maternal and emergency services, ANC/PNC, family planning counselling, monthly reports, clinic meetings. Requirements: graduated from recognized medical university; at least one year experience in management of health and nutrition at clinics/HFs; good understanding of BPHS and EPHS projects; good knowledge of MoPH policies; workload management; teamwork. Application via CHA online form.",
            "2026-10-07",
            application_email="",
        ),
        live_job(
            "acbar-hntpo-medical-doctor-md-145902",
            "Medical Doctor (MD)",
            "HealthNet TPO",
            "Nangarhar, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145902/medical-doctor-md",
            "mailto:recruitment.kabul@hntpo.org",
            "acbar",
            "Medical Doctor provides female OPD services, reproductive health, ANC, PNC, family planning, vaccination support, HMIS reporting, RMNCH and female OPD reports, community health services, MoPH policies, prescriptions, patient records and team management. Requirements: graduated from registered and recognized medical faculty, passed exit exam, 3 years relevant work experience in similar health facilities after graduation or specialization, community health services and MoPH/HMIS knowledge, team management, English and local languages. Send CV and application letter to recruitment.kabul@hntpo.org, fill HealthNet TPO application form at http://www.acbar.org/applicationform, mention position in email subject.",
            "2026-10-10",
            application_email="recruitment.kabul@hntpo.org",
            special_instructions=[
                "Download/fill the HealthNet TPO/ACBAR application form at http://www.acbar.org/applicationform before emailing.",
                "Email CV, application letter, and completed organization application form to recruitment.kabul@hntpo.org; use the exact advertised position as the subject.",
            ],
        ),
        live_job(
            "acbar-bdn-technical-supervisor-145872",
            "Technical Supervisor",
            "Bakhter Development Network - BDN",
            "Takhar, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145872/technical-supervisor",
            "https://forms.gle/U3dJcBHhJamUZ5yE9",
            "acbar",
            "Technical Supervisor oversees technical implementation of healthcare activities under PHC project, primary healthcare services, patient referral systems, medicines and medical supplies, quality standards, regulatory compliance, technical guidance, supportive supervision, mentorship, assessments, audits, reports and coordination with local healthcare providers and government authorities. Requirements: Medical degree (MD) and valid medical license to practice in Afghanistan, minimum 3 years healthcare project management, strong knowledge of primary healthcare principles and practices, communication, software/data management tools, written/spoken English. Apply through approved application form.",
            "2026-10-08",
        ),
        live_job(
            "acbar-hntpo-tsfp-project-supervisor-145882",
            "TSFP Project Supervisor",
            "HealthNet TPO",
            "Kunar, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145882/tsfp-project-supervisor",
            "mailto:recruitment.kabul@hntpo.org",
            "acbar",
            "TSFP Project Supervisor has overall responsibility of TSFP project management and provincial control, implementation planning, facility-level implementation, nutrition meetings, staff capacity building, stock and supply chain, medical and non-medical item supply, supportive supervision, monitoring with PHD/country office/stakeholders, national nutrition database, weekly/monthly/quarterly reports. Requirements: graduated from recognized Medical Faculty university (MD), at least 3-5 years experience in public health management specially in TSFP/nutrition, fluent English and local languages, MS Office/internet/data entry. Send CV and application letter to recruitment.kabul@hntpo.org; fill application form at http://www.acbar.org/applicationform and mention position in subject.",
            "2026-10-10",
            application_email="recruitment.kabul@hntpo.org",
            special_instructions=[
                "Download/fill the HealthNet TPO/ACBAR application form at http://www.acbar.org/applicationform before emailing.",
                "Email CV, application letter, and completed organization application form to recruitment.kabul@hntpo.org; use the exact advertised position as the subject.",
            ],
        ),
        live_job(
            "acbar-ri-quality-care-capacity-building-145861",
            "Quality of Care and Capacity Building Officer",
            "Relief International (RI)",
            "Nimruz, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145861/quality-of-care-and-capacity-building-officer",
            "mailto:vacancies.afghanistan@ri.org",
            "acbar",
            "Quality of Care and Capacity Building Officer supports and improves quality, safety, effectiveness and standardization of RI-supported BPHS/EPHS health services. Leads quality-of-care assessments, supportive supervision, quality improvement, audits, training needs assessments, coaching, mentoring, BPHS/EPHS compliance, maternal/newborn health, child health, immunization, nutrition, communicable diseases, mental health/MHPSS, IPC, pharmacy, laboratory, referral systems, HMIS, patient safety. Requirements: Bachelor's degree in Medicine (MD), MD+ specialization or MD+MPH; female candidate is point plus; minimum 3-5 years health sector experience; BPHS/EPHS desirable; NGO/INGO/MoPH/PPHD preferred; knowledge of QA/QI, PIP, clinical/service audit, IPC, patient safety, HMIS, facility assessment. Submit RI application letter, CV and three references; subject should include RI-NIM-SAFE-2026-13; download RI application form.",
            "2026-10-04",
            reference="RI-NIM-SAFE-2026-13",
            application_email="vacancies.afghanistan@ri.org",
        ),
        live_job(
            "akhs-surgeon-125",
            "Surgeon",
            "Aga Khan Health Services Afghanistan (AKHS-A)",
            "Kabul PHT, Afghanistan",
            "https://akhs.odoo.com/jobs/detail/surgeon-125",
            "https://akhs.odoo.com/jobs/detail/surgeon-125",
            "akhs",
            "Surgeon at Kabul PHT. Gender Male. Education Specialist Surgeon. Experience 1 year+. Job description includes general abdominal and pelvic surgery, obstetric/gynecological and minor surgeries, consultations, patient records, pre-operation examinations, consent, infection prevention, post-operative care, trainings, protocols, clinic monitoring. Requirements: graduate of recognized medical faculty and specialty certificate in general surgery; independent general surgery procedure experience; at least 1-2 years general surgery work experience; Afghan nationality; Dari and Pashto. Apply through AKHS/Odoo link; hard copy possible at regional office.",
            "2026-10-10",
            reliability="high",
        ),
        live_job(
            "acbar-akf-pediatrician-145914",
            "Pediatrician (Child Specialist)",
            "Aga Khan Foundation",
            "Baghlan, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145914/pediatrician-child-specialist-re-announced-re-announced",
            "mailto:Jobs.Afghanistan@akdn.org",
            "acbar",
            "Pediatrician conducts ward rounds, OPD services, emergency care, minor surgical procedures, counselling, pediatric TFU/neonatal services, clinical audits, staff training, pediatric care practices, clinical governance and quality assurance. Requirements: Medical Doctor (MD) with specialization in Pediatrics (Child Specialist), minimum 4 years relevant experience in EPHS/BPHS hospital settings, Microsoft Office, pediatric diagnosis and treatment, national health guidelines, emergency/critical pediatric cases, Dari and Pashto, English advantage. Female candidates encouraged. Submit CV and cover letter to AKDN email; quote Vacancy Number as email subject; no supporting documents required at this stage.",
            "2026-10-06",
            application_email="Jobs.Afghanistan@akdn.org",
        ),
        live_job(
            "acbar-cha-medical-doctor-female-145910",
            "Medical Doctor (Female)",
            "Coordination of Humanitarian Assistance (CHA)",
            "Zabul, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145910/medical-doctor-female-re-announced",
            "https://www.cha-net.org/jobs/application-form/medical-doctor-female-6a8d12c955c9840013a09b5e",
            "acbar",
            "Female Medical Doctor. Duties: triage, patient history and examination, rational prescription, clinic coordination, disease prevalence data, monthly activity reports, clinic meetings. Requirements: graduated from recognized medical university, at least 1 year experience in management of health and nutrition at clinics/HFs, good BPHS and EPHS understanding, MoPH policies, teamwork. Application through CHA link.",
            "2026-10-08",
        ),
        live_job(
            "unicef-polio-information-management-consultant-595890",
            "Information Management Consultant, Polio Section (Internationals Only)",
            "UNICEF Afghanistan",
            "Kabul / remote with travel, Afghanistan",
            "https://jobs.unicef.org/en-us/job/595890/internationals-only-information-management-consultant-polio-section-afghanistan-6-months-remote-with-trip",
            "https://secure.dc7.pageuppeople.com/apply/671/gateway/default.aspx?c=apply&lJobID=595890&lJobSourceTypeID=796&sLanguage=en-us",
            "unicef",
            "INTERNATIONALS ONLY Information Management Consultant, Polio Section. Categories Health. Supports Afghanistan Polio Management Information System (APMIS), SBC/VCCM/polio extender monitoring data integration, IM support to M&E team and field offices, AI-assisted digitization. Requirements: Master's in Information Management, Data Science, IT, Computer Science, Public Health Informatics or related; at least 5 years progressive information/data management including 2 years UN/large-scale public health program; immunization data systems; English; Dari/Pashto asset; technical proposal required.",
            "2026-10-04",
            reliability="high",
            reference="595890",
        ),
        live_job(
            "iom-supply-chain-assistant-afghanistan-2026",
            "Supply Chain Assistant",
            "IOM",
            "Herat, Mazar-i-Sharif, Jalalabad, Kandahar, Afghanistan",
            "https://fa-evlj-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs?location=Afghanistan",
            "https://fa-evlj-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs?location=Afghanistan",
            "iom_recruit",
            "Supply Chain Assistant, IOM Afghanistan. Locations Herat and 3 more. Apply before 10/04/2026. Contract type Special Short Term Graded, General Service G-4. This is a logistics/supply chain vacancy and is included to verify non-health noise exclusion.",
            "2026-10-04",
            reliability="high",
        ),
        live_job(
            "nrc-humanitarian-access-safety-manager-afghanistan-2026",
            "Humanitarian Access & Safety Manager Afghanistan",
            "Norwegian Refugee Council (NRC)",
            "Kabul, Afghanistan",
            "https://ekum.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2019/jobs?location=Afghanistan",
            "https://ekum.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2019/jobs?location=Afghanistan",
            "nrc_careers",
            "Humanitarian Access & Safety Manager Afghanistan. NRC Oracle listing shows one open job in Afghanistan/Kabul, category Health, Safety and Security, senior manager, posting date 09/16/2026. Included to verify non-medical safety/security noise exclusion.",
            "",
            reliability="high",
        ),
        live_job(
            "acbar-bdn-pharmacy-officer-145871",
            "Pharmacy Officer",
            "Bakhter Development Network - BDN",
            "Baghlan, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145871/pharmacy-officer",
            "https://forms.gle/tQxYPMvhEp1iGJSNA",
            "acbar",
            "Pharmacy Officer coordinates pharmaceutical activities under PHC project, medicine supply, storage, distribution, quantification, stock management, BPHS medicine requests and pharmacy reporting. Requirements: Bachelor's degree in pharmacy; at least 3 years relevant experience for pharmacists or 5 years for pharmacy technicians; English/local languages; computer skills. Apply through BDN form.",
            "2026-10-08",
        ),
        live_job(
            "acbar-union-aid-nurse-145912",
            "Nurse",
            "Union Aid",
            "Kabul, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145912/nurse",
            "mailto:hr@unionaid.org",
            "acbar",
            "Nurse/pharmacy duties in Union Aid health facility. Requirements: graduated from nursing, three years BPHS experience, holder of exit exam, trainings in HMIS, RUD, MDS, IP. Submission: write job title/vacancy number in subject; email hr@unionaid.org.",
            "2026-10-10",
            application_email="hr@unionaid.org",
        ),
        live_job(
            "acbar-intersos-nurse-nutrition-145868",
            "Nurse Nutrition",
            "INTERSOS",
            "Kandahar, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145868/nurse-nutrition",
            "https://forms.gle/pCApoG8vVrZNbsmU8",
            "acbar",
            "Nurse Nutrition provides nursing and nutritional care to children admitted to TFU for SAM, national nutrition protocols, infection prevention, patient records, counselling, reports. Requirements: Nursing/Midwifery certificate required; 2+ years relevant experience; CMAM advantage; Pashto and Dari required; English preferable; emergency response health experience preferred; local residents priority. Apply through Google Form.",
            "2026-10-12",
        ),
        live_job(
            "acbar-intersos-mental-health-promoter-145905",
            "Mental Health Promoter",
            "INTERSOS",
            "Zabul, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145905/mental-health-promoter",
            "https://forms.gle/fj7j87vu4Y9aFwVv7",
            "acbar",
            "Mental Health Promoter provides psychological support for CP, GBV survivors and people with specific needs, case management, PSS activities, individual counselling, reports, support groups, psychological first aid training. Requirements: 3+ years as counsellor dealing with CP, GBV and/or PwSN; English, Pashto and Dari; computer literacy; GBV survivor experience preferred; NGO experience preferred. Apply through Google Form.",
            "2026-10-13",
        ),
        live_job(
            "acbar-etook-production-pharmacist-145907",
            "Production Pharmacist",
            "Etook Pharma Drugs Production Company",
            "Herat, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145907/production-pharmacist",
            "mailto:info@etookpharma.af",
            "acbar",
            "Production Pharmacist supervises pharmaceutical manufacturing, formulations, SOPs, BMRs, GMP, QA/QC, product quality, manufacturing records, validation, equipment and personnel training. Requirements: B.Pharm / Pharm.D or equivalent degree in Pharmacy; pharmaceutical manufacturing/formulation experience; GMP; 4 years diploma in pharmacy; work experience with pharmaceutical companies. Apply by email info@etookpharma.af.",
            "2026-10-20",
            application_email="info@etookpharma.af",
        ),
        live_job(
            "acbar-arcs-vaccinator-kandahar-145878",
            "Vaccinator (Kandahar)",
            "Afghan Red Crescent Society (ARCS)",
            "Kandahar, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145878/oaksynatorkndhar",
            "mailto:hr@arcs.af",
            "acbar",
            "Vaccinator works on EPI vaccination, cold chain, vaccine cards, OPV for under-five children, counselling families and community on vaccines. Requirements: at least grade 12 graduate; nursing certificate preferred; one year vaccination experience; Ministry vaccination certificate. Submit educational documents/CV/work experience/Tazkira PDF by email; title and position code required.",
            "2026-10-06",
            application_email="hr@arcs.af",
        ),
        live_job(
            "acbar-arcs-cardiology-specialist-145857",
            "Cardiology Specialist Doctor",
            "Afghan Red Crescent Society (ARCS)",
            "Kabul, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145857/d-zh-dakhly-mtkhss-akr",
            "mailto:hr@arcs.af",
            "acbar",
            "Specialist cardiology clinical care across OPD, Emergency, Cardiac ICU, Cath Lab and inpatient ward; echocardiography, catheter-based CHD interventions, multidisciplinary case planning, on-call cardiology/cath-lab coverage, protocols, training, quality improvement. Requirements: MD/MBBS with postgraduate specialty qualification in Cardiology; fellowship/certification in Interventional Cardiology or Pediatric Interventional Cardiology; TTE/TEE competence; AMC registration/valid license; 2-3 years post-specialty clinical cardiology and 1-2 years supervised interventional practice; procedural log. Apply by email hr@arcs.af with documents PDF; title and position code required.",
            "2026-10-05",
            application_email="hr@arcs.af",
        ),
        live_job(
            "acbar-fmic-pharmacist-145856",
            "Pharmacist",
            "French Medical Institute for Mothers and Children (FMIC)",
            "Kabul, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145856/pharmacist",
            "https://docs.google.com/forms/d/1n12pNszI1pfzXxJdBngFkVt9XieP5E0YDBVl3Lv9sQ4/edit",
            "acbar",
            "FMIC Pharmacist reviews prescriptions, advises dosage, stores medicines, monitors lab reports and drug interactions, dispenses inpatient/outpatient medications, gives medication information, maintains pharmacy records and inventory, supervises pharmacy technician. Requirements: B.Sc. in Pharmacy or Pharm D from recognized university/institute; 2-3 years related experience; hospital pharmacy; pharmacology/pharmaceutical knowledge; local languages and English preferable. Apply through Google Form.",
            "2026-10-12",
        ),
        live_job(
            "acbar-bdn-physician-medical-doctor-145806",
            "Physician/Medical Doctor",
            "Bakhter Development Network - BDN",
            "Badakhshan, Baghlan, Kunduz and other Afghanistan provinces",
            "https://www.acbar.org/en/jobs/details/145806/physicianmedical-doctor",
            "https://forms.gle/rcWXTSUaXt8vwfFY8",
            "acbar",
            "Medical doctor delivers diagnosis, treatment, prescriptions, BPHS curative services, primary health care, health education, emergency care, ward supervision, registers, referrals, community coordination and infection prevention. Requirements: Medical degree MD and valid medical license to practice in Afghanistan; at least 2 years proven experience as medical doctor preferably in rural or underserved areas; strong clinical skills; local languages; Afghan healthcare regulations. Submission through Google Form; only one application for chosen position.",
            "2026-10-03",
        ),
        live_job(
            "acbar-pu-ami-medical-doctor-roster-145658",
            "Medical Doctor (Roster)",
            "PU-AMI",
            "Kunar, Nuristan and other Afghanistan provinces",
            "https://www.acbar.org/en/jobs/details/145658/medical-doctor-roster",
            "https://forms.cloud.microsoft/e/M3L9jqP6p1",
            "acbar",
            "Medical Doctor roster role providing OPD services, community awareness, referrals, reports, field/mobile health services, patient examination, prescriptions according to MoPH rules, health education, vaccination referral, supervision of vaccination, nursing, mother and child health and mental health services, monthly reporting, outbreak reporting and coordination. Requirements: graduated from recognized medical faculty and passed exit exam; good communication; Pashto/Dari; 2 years NGO experience asset; 2 years working experience in same position as Medical Doctor; resident preferable; familiar with BPHS and HMIS. Apply through Microsoft form and press submit; certificates requested only if called for interview.",
            "2026-09-30",
        ),
        live_job(
            "acbar-opha-medical-doctor-in-charge-145622",
            "Medical Doctor/In-charge",
            "Organization for People’s Health in Action (OPHA)",
            "Nuristan, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145622/daktr-maaalg-msyol-klynyk-medical-doctorin-charge",
            "https://ee.kobotoolbox.org/x/kRwQBlvq",
            "acbar",
            "Medical Doctor/In-charge manages HSC health and nutrition staff, supervises daily activities, ensures quality health services, HMIS registration/reporting, ANC/delivery/PNC, IMNCI under-five care, nutrition counselling, infectious disease diagnosis/treatment, mental health referral, essential medicines, quality assurance, monthly data analysis, mobile team leadership and coordination. Requirements: Afghan nationality; medical diploma from recognized university and passed Medical Council exam; at least 3 years work experience in curative medicine and clinic management; government/NGO health facility experience preferred; management, supervision and coordination ability; local candidates preferred. Apply through KoboToolbox link; accurately select district and health center.",
            "2026-09-30",
        ),
        live_job(
            "acbar-arsdo-medical-doctor-male-145698",
            "Medical Doctor (Male)",
            "Afghanistan Relief and Sustainable Development Organization (ARSDO)",
            "Kunar, Laghman, Nangarhar and other Afghanistan provinces",
            "https://www.acbar.org/en/jobs/details/145698/medical-doctor-male",
            "https://forms.gle/Jqfs2fhwhrrYfrEJ9",
            "acbar",
            "Medical Doctor provides outpatient and emergency health services, clinical examination, diagnosis, treatment plans, emergency referrals, health education, maternal and child health support, patient records, infection prevention, referral, MoPH/WHO guidelines, HMIS, staff meetings and capacity building. Requirements: MD degree from recognized university and completion of exit exam; at least 2 years professional clinical services experience; BPHS/EPHS advantage; Pashto, Dari and basic English; basic computer literacy. Title says Male; body text contains contradictory Female Medical Doctor wording. Apply through Google Form with CV and cover letter in PDF and Word format.",
            "2026-09-30",
        ),
        live_job(
            "acbar-arcs-technical-assistant-echo-145834",
            "Technical Assistant (Project Focal Point/ECHO)",
            "Afghan Red Crescent Society (ARCS)",
            "Kabul, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145834/technical-assistant-project-focal-pointecho",
            "mailto:hr@arcs.af",
            "acbar",
            "Technical Assistant provides technical oversight for Mobile Health Teams, Basic Health Centers and Sub-Health Centers, MoPH guideline implementation, technical guidelines/SOPs/protocols, work planning, supportive supervision, quality assurance, training needs assessment, technical training, reporting, coordination with MoPH/IFRC/UN/NGOs and project development. Requirements: Medical Doctor MD from recognized institution; completed medical exit exam; MPH or relevant postgraduate qualification preferred; minimum 3-5 years progressively responsible health program management; humanitarian/NGO/Red Cross/UN experience preferred; Mobile Health Teams or PHC projects highly desirable; English, Dari, Pashto, MS Office and HMIS/data analysis asset. Application by email hr@arcs.af; indicating the job title and vacancy number/position code in the email subject line is mandatory, but the exact code was not exposed in the fetched page; education/experience/Tazkira documents must be one PDF.",
            "2026-10-04",
            application_email="hr@arcs.af",
        ),
        live_job(
            "acbar-opha-hospital-director-145767",
            "Hospital Director",
            "Organization for People’s Health in Action (OPHA)",
            "Laghman, Afghanistan",
            "https://www.acbar.org/en/jobs/details/145767/hospital-director",
            "https://www.acbar.org/en/jobs/details/145767/hospital-director",
            "acbar",
            "Hospital Director is responsible for planning, organization, staffing, leadership and control of EPHS activities, work plans, training plans, monitoring, PPHD coordination, HER-AF2 compliance, data analysis, EPHS reporting, hospital services, infection prevention, supervision, hospital board meetings and BPHS/EPHS coordination. Requirements: Master's degree in public health or related field and 5 years managing health service delivery, or bachelor's degree in Medical and 10 years experience; at least 5 years managing health service delivery for MPH or 10 years for bachelor's degree; postgraduate hospital management preferred; strong hospital management, leadership, BPHS/EPHS, languages and computer skills.",
            "2026-10-08",
        ),
        live_job(
            "unjobs-ctg-medical-doctor-team-leader-herat-1790434848677",
            "Medical Doctor (MD) / Team Leader",
            "Committed To Good (CTG)",
            "Herat, Afghanistan",
            "https://unjobs.org/vacancies/1790434848677",
            "https://unjobs.org/vacancies/1790434848677",
            "unjobs",
            "CTG Medical Doctor/Team Leader supports migration health screening, reproductive maternal and child health, fixed/mobile health facilities, primary and emergency medical care, consultations, diagnosis, treatment, referrals, IPC, reporting, essential medicines, coordination with health authorities, disease surveillance, staff supervision and mentoring. Requirements: Bachelor's in medicine MD validated by Ministry of Higher Education; valid Afghanistan Medical Council registration number if graduated before 2019 or passed exit exam for 2019+; minimum 2 years medical doctor experience; 2 years Afghanistan experience; Dari, Pashto, English. Apply by 29-Sep-2026.",
            "2026-09-29",
        ),
        live_job(
            "unjobs-unama-medical-doctor-kunduz-1790200910231",
            "Medical Doctor",
            "UNAMA",
            "Kunduz, Afghanistan",
            "https://unjobs.org/vacancies/1790200910231",
            "https://unjobs.org/vacancies/1790200910231",
            "unjobs",
            "UNAMA Medical Doctor International UN Volunteer Specialist. Duties include UN clinic clinical care, assessment, diagnosis, treatment, trauma stabilization, medevac/casevac, occupational health, immunizations, infection prevention and control, emergency preparedness, medical logistics and reporting. Requirements: candidate must be national of country other than country of assignment; 5 years progressively responsible physician clinical experience in emergency/inpatient/intensive/high-acuity services; English fluent; bachelor's in General Medicine/Emergency/Occupational/Internal Medicine; BLS/ACLS/PHTLS or trauma certifications; valid license to practice medicine in home country.",
            "",
        ),
        live_job(
            "unjobs-who-surgical-oncology-consultant-1789567491811",
            "Surgical Oncology Consultant",
            "World Health Organization (WHO)",
            "Kabul, Afghanistan",
            "https://unjobs.org/vacancies/1789567491811",
            "https://unjobs.org/vacancies/1789567491811",
            "unjobs",
            "WHO Surgical Oncology Consultant strengthens cancer surgical oncology services, assesses oncology services, trains surgical teams, develops protocols, multidisciplinary surgical oncology, national cancer control planning and perioperative care. Requirements: Master's Degree or above in Surgical Oncology; 5 to 10 years clinical surgical oncology experience in similar low resource settings with international experience mandatory; training healthcare professionals; multidisciplinary teams; policy development and stakeholder engagement; expert English. Assignment Kabul from 01/10/2026 to 31/01/2027.",
            "",
            reliability="medium",
        ),
        live_job(
            "unjobs-mdm-medical-coordinator-kabul-1788985054143",
            "Medical Coordinator",
            "Médecins du Monde (MdM)",
            "Kabul, Afghanistan",
            "https://unjobs.org/vacancies/1788985054143",
            "https://unjobs.org/vacancies/1788985054143",
            "unjobs",
            "Medical Coordinator defines, drives and monitors mission medical strategy, ensures quality and effectiveness of health, nutrition, MHPSS and SRHR activities, leads medical teams, analyses medical data, designs projects/proposals, represents MdM with authorities and coordination mechanisms, and adapts programmes to emergencies. Requirements emphasize strategic medical leadership, SRHR/public health programme quality, team leadership, stakeholder negotiation and humanitarian context. Posting says apply soon and may be taken down after 30 applications; CV and cover letter required. No exact closing date exposed by UNJobs.",
            "",
            reliability="medium",
        ),
        live_job(
            "unama-medical-doctor-mazar-1790258574072",
            "Medical Doctor",
            "UNAMA",
            "Mazar-i-Sharif, Afghanistan",
            "https://unjobs.org/vacancies/1790258574072",
            "https://unjobs.org/vacancies/1790258574072",
            "unjobs",
            "UNAMA Medical Doctor. International UN Volunteer Specialist. Duties include UN clinic full-time clinical care, diagnosis/treatment, emergency/trauma stabilization, medevac/casevac, occupational health, immunizations, infection prevention and control, training, medical logistics, reports. Requirements: candidate must be national of country other than country of assignment; 5 years relevant experience; English fluent; bachelor's in General Medicine/Emergency/Occupational/Internal Medicine; at least five years progressively responsible physician experience in emergency/inpatient/intensive/high-acuity services; BLS/ACLS/PHTLS or trauma certifications; valid license to practice medicine in home country. UNJobs says recruiting organization has not specified a closing date and job remains listed until removed.",
            "",
        ),
        live_job(
            "unama-medical-doctor-gardez-1790251373811",
            "Medical Doctor",
            "UNAMA",
            "Gardez, Afghanistan",
            "https://unjobs.org/vacancies/1790251373811",
            "https://unjobs.org/vacancies/1790251373811",
            "unjobs",
            "UNAMA Medical Doctor. International UN Volunteer Specialist. Duties include UN clinic full-time clinical care, diagnosis/treatment, emergency/trauma stabilization, medevac/casevac, occupational health, immunizations, infection prevention and control, training, medical logistics, reports. Requirements: candidate must be national of country other than country of assignment; 5 years relevant experience; English fluent; bachelor's in General Medicine/Emergency/Occupational/Internal Medicine; at least five years progressively responsible physician experience in emergency/inpatient/intensive/high-acuity services; BLS/ACLS/PHTLS or trauma certifications; valid license to practice medicine in home country. UNJobs says recruiting organization has not specified a closing date and job remains listed until removed.",
            "",
        ),
        live_job(
            "unama-nurse-kabul-national-1790589742575",
            "Nurse",
            "UNAMA",
            "Kabul, Afghanistan",
            "https://unjobs.org/vacancies/1790589742575",
            "https://unjobs.org/vacancies/1790589742575",
            "unjobs",
            "UNAMA National UN Volunteer Nurse. Requirements: national/legal resident/refugee in country of assignment, bachelor's degree in clinical/emergency/intensive care nursing or IPC, registered nurse, valid nursing license, five years clinical nursing in emergency/inpatient/intensive/high-acuity, BLS and ACLS required, IPC and Microsoft applications. UNJobs says no closing date specified/listed until removed.",
            "",
        ),
        live_job(
            "unama-lab-technologist-kabul-1790200910375",
            "Laboratory Technologist",
            "UNAMA",
            "Kabul, Afghanistan",
            "https://unjobs.org/vacancies/1790200910375",
            "https://unjobs.org/vacancies/1790200910375",
            "unjobs",
            "UNAMA Laboratory Technologist. Requirements: candidate must be national of country other than country of assignment; 5 years relevant experience; English; bachelor's degree in Medical Laboratory Technology/Sciences/Transfusion Medicine/Lab Safety/LQMS; at least five years lab tech experience; valid laboratory technologist license; procurement, inventory and transfusion medicine. UNJobs says no closing date specified/listed until removed.",
            "",
        ),
    ]
    return jobs


def safe_summary(row: dict[str, Any]) -> dict[str, Any]:
    match = row.get("last_matching_result") or {}
    return {
        "id": row.get("canonical_id") or row.get("id"),
        "title": row.get("title"),
        "company": row.get("organization") or row.get("company"),
        "location": row.get("location"),
        "closing_date": row.get("closing_date"),
        "readiness_status": row.get("readiness_status"),
        "operational_priority": row.get("operational_priority"),
        "application_route": row.get("application_route") or row.get("apply_url"),
        "source_urls": row.get("source_urls") or [],
        "match_counts": match.get("counts", {}) if isinstance(match, dict) else {},
        "priority_reasons": row.get("priority_reasons") or [],
    }


def package_summary(prepared: dict[str, Any]) -> dict[str, Any]:
    package = prepared.get("application_package") or {}
    return {
        "job_id": prepared.get("job_id"),
        "ok": prepared.get("ok"),
        "readiness_status": prepared.get("readiness_status"),
        "route_type": package.get("route_type"),
        "package_status": package.get("package_status"),
        "application_route": package.get("application_route"),
        "deadline": package.get("deadline"),
        "no_submission_performed": prepared.get("no_submission_performed"),
        "paths": prepared.get("generated_paths") or {},
        "missing_items": package.get("missing_items") or [],
        "review_warnings": package.get("review_warnings") or [],
    }


async def main() -> None:
    profile, cv_text = build_profile()
    records = load_source_registry(profile=profile)
    registry_errors = validate_source_registry(records)
    active_sources = active_sources_for_discovery(profile, records)
    source_run = json.loads(SOURCE_RUN_JSON.read_text(encoding="utf-8")) if SOURCE_RUN_JSON.exists() else {}

    async def discovery(_profile: dict[str, Any]) -> dict[str, Any]:
        jobs = live_verified_jobs()
        return {
            "jobs": jobs,
            "sources_attempted": [source["id"] for source in active_sources],
            "sources_successful": sorted({job.platform for job in jobs}),
            "source_errors": [{"source": "python_https_live_discovery", "error": "existing in-repo httpx/curl discovery hit TLS/SSL EOF in this sandbox; live page evidence was retrieved by Arena fetch_page and fed into existing pipeline"}],
        }

    scan = await run_job_watch_scan(
        profile,
        discovery_func=discovery,
        now=datetime(2026, 9, 30, 12, 30, tzinfo=timezone.utc),
        today=RUN_DATE,
        resume_text=cv_text,
        scan_id="2026-09-30_live_verified_pages",
    )

    all_rows = get_watcher_jobs(active_only=False, limit=1000)
    active_open = [row for row in all_rows if row.get("current_status") == "ACTIVE"]
    # Focus user-facing counts on medical/health/actionable rows. LOW non-health noise is counted separately.
    relevant = [row for row in active_open if row.get("operational_priority") != "LOW" or row.get("readiness_status") == NOT_ELIGIBLE]
    ready = [row for row in relevant if row.get("readiness_status") == READY_TO_APPLY and row.get("operational_priority") != "LOW"]
    needs = [row for row in relevant if row.get("readiness_status") == NEEDS_VERIFICATION]
    not_eligible = [row for row in relevant if row.get("readiness_status") == NOT_ELIGIBLE]
    low_noise = [row for row in active_open if row.get("operational_priority") == "LOW" and row.get("readiness_status") != NOT_ELIGIBLE]
    actionable = get_actionable_opportunities(limit=50)

    prepared = []
    for row in sorted(ready, key=lambda r: (r.get("closing_date") or "9999-99-99", r.get("title") or "")):
        prepared.append(package_summary(prepare_application_for_watcher_job(row["canonical_id"], profile, resume_text=cv_text, out_dir=str(OUT_DIR))))

    submission_violations = []
    for pkg in prepared:
        job = tracker.get_job_by_id(pkg.get("job_id"))
        if job and (job.get("submitted_at") or job.get("status") in {"submitted", "applied"}):
            submission_violations.append({"job_id": pkg.get("job_id"), "status": job.get("status"), "submitted_at": job.get("submitted_at")})

    evidence = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "market_date_used": RUN_DATE.isoformat(),
        "normal_live_source_run": source_run,
        "source_registry": {
            "records": len(records),
            "active_sources_count": len(active_sources),
            "active_sources": [{"id": s.get("id"), "status": s.get("reliability_status"), "method": s.get("discovery_method"), "url": s.get("official_jobs_url")} for s in active_sources],
            "validation_errors": registry_errors,
        },
        "scan_summary": scan,
        "counts": {
            "normal_system_jobs_discovered_before_tls_fallback": (source_run.get("counts") or {}).get("jobs_discovered_raw"),
            "live_verified_jobs_ingested": len(live_verified_jobs()),
            "jobs_after_deduplication": scan.get("deduplicated_count"),
            "open_relevant_jobs": len(relevant),
            "ready_to_apply": len(ready),
            "needs_verification": len(needs),
            "not_eligible": len(not_eligible),
            "low_priority_noise_excluded": len(low_noise),
            "packages_prepared": len([pkg for pkg in prepared if pkg.get("ok")]),
        },
        "ready_to_apply": [safe_summary(row) for row in ready],
        "needs_verification": [safe_summary(row) for row in needs],
        "not_eligible": [safe_summary(row) for row in not_eligible],
        "low_priority_noise_excluded": [safe_summary(row) for row in low_noise],
        "best_actionable_by_deadline": [safe_summary(row) for row in actionable[:20]],
        "packages_prepared": prepared,
        "submission_violations": submission_violations,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Live Afghan Job Market Run — 2026-09-30",
        "",
        f"Run at: {evidence['run_at']}",
        f"Active registry sources checked: {len(active_sources)}",
        f"Registry validation errors: {len(registry_errors)}",
        "",
        "## Counts",
    ]
    for k, v in evidence["counts"].items():
        lines.append(f"- {k}: {v}")
    for heading, key in [("READY_TO_APPLY", "ready_to_apply"), ("NEEDS_VERIFICATION", "needs_verification"), ("NOT_ELIGIBLE", "not_eligible")]:
        lines.extend(["", f"## {heading}", ""])
        rows = evidence[key]
        if not rows:
            lines.append("- None.")
        for row in rows:
            lines.append(f"- {row['closing_date'] or 'No fixed date'} — {row['title']} — {row['company']} — {row['operational_priority']} — route: {row['application_route'] or 'N/A'}")
    lines.extend(["", "## Packages prepared", ""])
    if not prepared:
        lines.append("- None.")
    for pkg in prepared:
        lines.append(f"- {pkg['job_id']} — {pkg['package_status']} — {pkg['route_type']} — {pkg['application_route']}")
        for label, paths in (pkg.get("paths") or {}).items():
            lines.append(f"  - {label}: {paths}")
    lines.extend(["", "## Best actionable by deadline", ""])
    for row in evidence["best_actionable_by_deadline"]:
        lines.append(f"- {row['closing_date'] or 'No fixed date'} — {row['title']} — {row['company']} — {row['readiness_status']} — {row['application_route'] or 'N/A'}")
    if not evidence["best_actionable_by_deadline"]:
        lines.append("- None.")
    lines.extend(["", "## Low-priority/non-profile noise excluded", ""])
    for row in evidence["low_priority_noise_excluded"]:
        lines.append(f"- {row['title']} — {row['company']} — {row['readiness_status']} / {row['operational_priority']}")
    if not evidence["low_priority_noise_excluded"]:
        lines.append("- None.")
    lines.extend(["", "## Blockers", "", "- Existing Python/httpx live discovery in this sandbox hit TLS/SSL EOF across active HTTPS sources; no employer/application submission was attempted."])
    if submission_violations:
        lines.append(f"- SAFETY VIOLATION: {submission_violations}")
    else:
        lines.append("- Safety check passed: no submitted/applied status and no submitted_at timestamp for prepared packages.")
    REPORT_MD.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    print(f"Live market run report JSON: {REPORT_JSON}")
    print(f"Live market run report MD: {REPORT_MD}")
    print(json.dumps(evidence["counts"], ensure_ascii=False, indent=2))
    if submission_violations:
        raise SystemExit("Submission safety violation detected")


if __name__ == "__main__":
    asyncio.run(main())
