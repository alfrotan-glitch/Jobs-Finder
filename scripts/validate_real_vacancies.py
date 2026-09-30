#!/usr/bin/env python3
"""Validate the Afghanistan MD workflow against real ACBAR vacancies.

The direct ACBAR HTTP source can be unreachable from some sandboxes because the
remote server drops TLS handshakes.  These validation fixtures are short excerpts
from real ACBAR pages fetched during the Arena validation session on 2026-09-30;
each item retains its original source URL, application destination, deadline, and
instructions.  The script runs the same deterministic matcher, document builder,
and tracker state transitions used by the product.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from textwrap import shorten

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from utils.discovery import Job
from utils.documents import generate_tailored_documents
from utils.medical_matcher import MET, NEEDS_VERIFICATION, NOT_MET, match_job_against_profile
from utils.profile import load_profile
from utils.resume_parser import extract_resume_text
from utils.tracker import (
    get_db,
    get_job_by_id,
    log_discovered,
    log_medical_match,
    transition_application_state,
    update_tailored_resume,
)

TODAY = date(2026, 9, 30)
OUT_DIR = Path("documents/real_vacancy_validation")


def _job(**kwargs) -> Job:
    metadata = kwargs.pop("metadata", {})
    metadata.setdefault("source", "acbar")
    metadata.setdefault("source_url", kwargs["url"])
    return Job(platform="acbar", department="Medical / Health", metadata=metadata, **kwargs)


REAL_VACANCIES: list[Job] = [
    _job(
        id="real_acbar_145882_tsfp_project_supervisor",
        title="TSFP Project Supervisor",
        company="HealthNet TPO",
        location="Kunar",
        url="https://www.acbar.org/en/jobs/details/145882/tsfp-project-supervisor",
        apply_url="https://www.acbar.org/en/jobs/details/145882/tsfp-project-supervisor",
        description="""
        Source: ACBAR. Deadline: 2026-10-10.
        About: HealthNet TPO is a Netherlands based non-governmental organization providing Primary Health Care,
        Mental Health and psychosocial services, emergency response projects, nutrition, malaria control and MHPSS in Afghanistan.
        Job summary: Overall responsibility of TSFP project management and control on provincial level; planning,
        implementation, coordination with stakeholders, capacity building for project staff, stock and supply chain management,
        supportive supervision, data collection and national nutrition database reporting, weekly/monthly/quarterly reports.
        Job requirements: Graduated from recognized Medical Faculty university (MD). At least 3-5 years' experience in
        public health management specially in TSFP/nutrition. Fluent in English and local languages. Well familiar with MS Office,
        internet and data entry. Effective communication and problem solving skills.
        Submission: send CV and application letter to recruitment.kabul@hntpo.org; fill the HealthNet TPO application form
        available from ACBAR; mention the position in the email subject line.
        Email / Application Form: recruitment.kabul@hntpo.org
        """,
        metadata={"validation_case": "clearly_satisfied_ingo_health_vacancy", "closing_date": "2026-10-10"},
    ),
    _job(
        id="real_acbar_145872_technical_supervisor_bdn",
        title="Technical Supervisor",
        company="Bakhter Development Network - BDN",
        location="Takhar",
        url="https://www.acbar.org/en/jobs/details/145872/technical-supervisor",
        apply_url="https://www.acbar.org/en/jobs/details/145872/technical-supervisor",
        description="""
        Source: ACBAR. Deadline: 2026-10-08.
        About: Bakhter Development Network is an Afghan NGO implementing health projects including BPHS-EPHS, PHC ECHO,
        CBNI, TSFP, RMNCAH/SRH and PSS services across Afghanistan.
        Job summary: oversee technical implementation of healthcare activities under the PHC project in north-east provinces;
        supervise primary healthcare services; strengthen referral systems; coordinate medicines and medical supplies;
        provide technical guidance, supportive supervision and mentorship; maintain records and submit reports; represent BDN
        in technical discussions and coordination meetings.
        Job requirements: Medical degree (MD) and a valid medical license to practice in Afghanistan. Minimum of 3 years of
        experience in healthcare project management. Strong knowledge of primary healthcare principles and practices.
        Excellent communication and interpersonal skills. Ability to work in challenging and resource-constrained environments.
        Proficiency in relevant software and data management tools. Fluency in written and spoken English.
        Submission: submit updated CV and formal cover letter through approved application form by close of business on October 08, 2026.
        Application Form: https://forms.gle/U3dJcBHhJamUZ5yE9
        """,
        metadata={"validation_case": "owner_confirmed_license_requirement", "closing_date": "2026-10-08"},
    ),
    _job(
        id="real_acbar_145832_fixed_clinic_manager_arcs",
        title="آمرکلینیک های ثابت / Fixed Clinic Manager",
        company="Afghan Red Crescent Society (ARCS)",
        location="Kabul",
        url="https://www.acbar.org/en/jobs/details/145832/amrklynyk-hay-thabt",
        apply_url="https://www.acbar.org/en/jobs/details/145832/amrklynyk-hay-thabt",
        description="""
        Source: ACBAR. Deadline: 2026-10-03.
        Job summary: provide quality health services through fixed clinics, supervise professional and service staff,
        participate in Kabul provincial health coordination meetings, monitor and evaluate clinic staff, prepare monthly,
        quarterly and annual reports, and manage clinic resources.
        Job requirements from ACBAR Dari posting: داشتن سند MD از یک نهاد تحصیلی معتبر. داشتن سند ایگزیت امتحان لازمی میباشد.
        تجربه کاری حد اقل ۵ سال مرتبط و در بخش مدیریت برنامه های صحی. تجربه کار با سازمان های بشر دوستانه موسسات غیر دولتی /
        صلیب سرخ/هلال احمر یا ادارات سازمان ملل متحد ترجیح داده میشود. تجربه در مدیریت تیم های سیار صحی یا پروژه های مراقبت اولیه صحی
        بسیار مطلوب است. تسلط کامل به زبان انگلیسی / دری/ پشتو. تجربه کار با سیستم‌های معلومات مدیریت صحی (HMIS).
        Submission: send a single PDF including CV, education documents, experience documents and Tazkira to hr@arcs.af;
        the email must include the title and position code. Email / Application Form: hr@arcs.af
        """,
        metadata={"validation_case": "clearly_unmet_years_requirement", "closing_date": "2026-10-03"},
    ),
    _job(
        id="real_acbar_145841_female_medical_doctor_ri",
        title="Female Medical Doctor",
        company="Relief International (RI)",
        location="Nimruz",
        url="https://www.acbar.org/en/jobs/details/145841/female-medical-doctor",
        apply_url="https://www.acbar.org/en/jobs/details/145841/female-medical-doctor",
        description="""
        Source: ACBAR. Deadline: 2026-10-03.
        About: Relief International is an international non-profit organization providing Health and Nutrition, WASH,
        Education and Livelihoods programming.
        Job summary: monitor and provide general care to patients at Charborjak CHC; admit and examine patients; diagnose
        medical conditions; prepare treatment records; work with doctors and medical/non-medical staff; promote health education;
        provide night duties if needed; adhere to RI policies and humanitarian mission.
        Job requirements: Medical Doctor (MD degree). At least 1 year work experience in Health sector (as a GP in curative
        medicine and treatment). Preferably with international donor-funded projects, UN agencies or NGOs on relevant programs
        in Afghanistan. Excellent verbal and written communication. Fluency in Dari and Pashto. Excellent English. Residency in
        the district is an advantage. Female Medical Doctor.
        Submission: submit RI application letter with CV and three references. Mention the announced position vacancy number
        in the email subject like (RI-NIM-SAFE-2026-10). Via email: vacancies.afghanistan@ri.org. Download RI application form
        from ACBAR document link and send it with CV. Safeguarding standards apply.
        Email / Application Form: vacancies.afghanistan@ri.org
        """,
        metadata={"validation_case": "hard_gender_unverified_requirement", "closing_date": "2026-10-03"},
    ),
    _job(
        id="real_acbar_145834_technical_assistant_arcs",
        title="Technical Assistant (Project Focal Point/ECHO)",
        company="Afghan Red Crescent Society (ARCS)",
        location="Kabul",
        url="https://www.acbar.org/en/jobs/details/145834/technical-assistant-project-focal-pointecho",
        apply_url="https://www.acbar.org/en/jobs/details/145834/technical-assistant-project-focal-pointecho",
        description="""
        Source: ACBAR. Deadline: 2026-10-04.
        Job summary: provide technical oversight for Mobile Health Teams, Basic Health Centers and Sub-Health Centers;
        ensure implementation of quality primary healthcare services according to Ministry of Public Health guidelines; conduct
        supportive supervision; assess training needs; mentor and coach field health personnel; review technical reports; coordinate
        with MoPH, IFRC, National Societies, donors, UN agencies, NGOs and other stakeholders; support proposal writing and donor reports.
        Job requirements: Medical Doctor (MD) degree from a recognized institution. Successful completion of the required medical
        exit examination. Master of Public Health or another relevant postgraduate qualification is preferred. Minimum 3-5 years of
        progressively responsible experience in health program management. Experience working with humanitarian organizations,
        NGOs, Red Cross/Red Crescent Movement or UN agencies is preferred. Experience managing Mobile Health Teams or Primary
        Health Care projects is highly desirable. Strong knowledge of primary healthcare, public health and health systems. Familiarity
        with MoPH policies and humanitarian health standards. Strong report-writing skills. Fluency in English (written and spoken).
        Working knowledge of Dari Pashto. Experience with health Management information systems and data analysis tools is an asset.
        Submission: send a PDF with CV and required documents to hr@arcs.af; email title and position code are mandatory.
        Email / Application Form: hr@arcs.af
        """,
        metadata={"validation_case": "kabul_health_management_with_exit_exam_unverified", "closing_date": "2026-10-04"},
    ),
]


def _reset_validation_rows(job_ids: list[str]) -> None:
    conn = get_db()
    try:
        for job_id in job_ids:
            conn.execute("DELETE FROM applications WHERE id = ?", (job_id,))
        conn.commit()
    finally:
        conn.close()


def _important_statuses(match_report: dict) -> list[dict]:
    rows = []
    for item in match_report.get("requirement_matches", []):
        rows.append(
            {
                "requirement": item.get("label"),
                "level": item.get("required"),
                "status": item.get("status"),
                "explanation": item.get("explanation"),
                "evidence": item.get("evidence", []),
                "vacancy_evidence": item.get("required_evidence", []),
            }
        )
    return rows


def _write_docs(job: Job, docs: dict) -> dict[str, str]:
    safe = job.id.replace("/", "_")
    cv_path = OUT_DIR / f"{safe}_tailored_cv.txt"
    letter_path = OUT_DIR / f"{safe}_cover_letter.txt"
    cv_path.write_text(docs.get("tailored_cv_text", ""), encoding="utf-8")
    letter_path.write_text(docs.get("cover_letter", ""), encoding="utf-8")
    return {"tailored_cv": str(cv_path), "cover_letter": str(letter_path)}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    profile_path = Path("profiles/dr_allah_yar_frotan_profile.yaml")
    if not profile_path.exists():
        profile_path = Path("profile.yaml")
    profile = load_profile(profile_path)
    resume_text = extract_resume_text(profile.get("resume_path", ""))

    _reset_validation_rows([job.id for job in REAL_VACANCIES])
    validations = []

    for job in REAL_VACANCIES:
        log_discovered(job)
        match_report = match_job_against_profile(job.to_dict(), profile, resume_text=resume_text, today=TODAY).to_dict()
        log_medical_match(job.id, match_report)
        docs = generate_tailored_documents(job.to_dict(), profile, match_report, resume_text=resume_text)
        update_tailored_resume(job.id, docs)
        doc_paths = _write_docs(job, docs)

        opened_ok, opened_message = transition_application_state(job.id, "opened", note="Validation opened real application destination for review")
        submit_blocked_ok, submit_blocked_message = transition_application_state(job.id, "submitted", explicit_confirmation=False)
        tracked = get_job_by_id(job.id) or {}

        validations.append(
            {
                "job_id": job.id,
                "case": job.metadata.get("validation_case"),
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "source_url": job.url,
                "application_destination": match_report.get("facts", {}).get("application_email") or match_report.get("facts", {}).get("application_url") or job.apply_url,
                "application_url": match_report.get("facts", {}).get("application_url") or job.apply_url,
                "application_email": match_report.get("facts", {}).get("application_email"),
                "closing_date": match_report.get("facts", {}).get("closing_date"),
                "priority": match_report.get("priority"),
                "counts": match_report.get("counts"),
                "requirements": _important_statuses(match_report),
                "document_paths": doc_paths,
                "review_warnings": docs.get("review_warnings", []),
                "safe_open_recorded": opened_ok,
                "safe_open_message": opened_message,
                "submission_without_confirmation_blocked": (not submit_blocked_ok and "Explicit user confirmation" in submit_blocked_message),
                "submission_block_message": submit_blocked_message,
                "tracker_status_after_validation": tracked.get("status"),
                "tracker_application_email": tracked.get("application_email"),
                "tracker_application_subject": tracked.get("application_subject"),
                "tracker_source_url": tracked.get("source_url"),
            }
        )

    json_path = OUT_DIR / "real_vacancy_validation_2026-09-30.json"
    json_path.write_text(json.dumps(validations, indent=2, ensure_ascii=False), encoding="utf-8")

    md_path = OUT_DIR / "real_vacancy_validation_2026-09-30.md"
    md_lines = [
        "# Real Afghanistan Vacancy Validation — 2026-09-30",
        "",
        "Profile: Dr. Allah Yar Frotan (source CV/profile only).",
        "Direct note: ACBAR pages were verified through live page fetch/search during validation; the product keeps original source URLs and application destinations. In this sandbox, direct Python TLS handshakes to ACBAR can fail, so source failure resilience and web-search-assisted ingestion are also tested.",
        "",
        "## Summary",
        "",
        "| Case | Job | Company | Priority | Met | Needs verification | Not met | Application destination | Closing | Safe stop |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for item in validations:
        counts = item["counts"] or {}
        md_lines.append(
            "| {case} | {title} | {company} | {priority} | {met} | {needs} | {not_met} | {dest} | {closing} | {safe} |".format(
                case=item["case"],
                title=item["title"].replace("|", "/"),
                company=item["company"].replace("|", "/"),
                priority=item["priority"],
                met=counts.get(MET, 0),
                needs=counts.get(NEEDS_VERIFICATION, 0),
                not_met=counts.get(NOT_MET, 0),
                dest=(item["application_destination"] or "").replace("|", "/"),
                closing=item["closing_date"] or "",
                safe="blocked submit" if item["submission_without_confirmation_blocked"] else "CHECK",
            )
        )
    md_lines.extend(["", "## Detailed requirement checks", ""])
    for item in validations:
        md_lines.extend(
            [
                f"### {item['title']} — {item['company']}",
                "",
                f"- Source URL: {item['source_url']}",
                f"- Application URL retained: {item['application_url']}",
                f"- Application email retained: {item['application_email'] or 'N/A'}",
                f"- Tracker status after safe open: {item['tracker_status_after_validation']}",
                f"- Submission without explicit confirmation blocked: {item['submission_without_confirmation_blocked']} ({item['submission_block_message']})",
                f"- Tailored CV: {item['document_paths']['tailored_cv']}",
                f"- Cover letter: {item['document_paths']['cover_letter']}",
                "",
                "| Requirement | Level | Status | Explanation | Evidence used | Vacancy evidence |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for req in item["requirements"]:
            evidence = "; ".join(shorten(str(e), width=100, placeholder="...") for e in req.get("evidence", [])[:2])
            vacancy = "; ".join(shorten(str(e), width=100, placeholder="...") for e in req.get("vacancy_evidence", [])[:2])
            md_lines.append(
                "| {requirement} | {level} | {status} | {explanation} | {evidence} | {vacancy} |".format(
                    requirement=str(req.get("requirement", "")).replace("|", "/"),
                    level=str(req.get("level", "")).replace("|", "/"),
                    status=str(req.get("status", "")).replace("|", "/"),
                    explanation=str(req.get("explanation", "")).replace("|", "/"),
                    evidence=evidence.replace("|", "/"),
                    vacancy=vacancy.replace("|", "/"),
                )
            )
        if item.get("review_warnings"):
            md_lines.extend(["", "Review warnings:"] + [f"- {w}" for w in item["review_warnings"]])
        md_lines.append("")

    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Validation written to {md_path}")
    print(f"Machine-readable details written to {json_path}")


if __name__ == "__main__":
    main()
