# Evidence recovery audit — applicant-supplied facts vs. the 28 held responsibility drafts

<!-- Audit only. This file records what the applicant already supplied. It does not modify profile.yaml, does not generate CV wording, and does not apply any decision. -->

**Corrected question this audit answers:** *"Did the applicant previously provide this fact?"*

**Question it deliberately does not ask:** *"Is this exact sentence currently present in `profile.yaml`?"*

The current `profile.yaml` is a **normalized, reduced** representation. Responsibility drafts were held because they were not present in that normalized record — not necessarily because the applicant never supplied them. This audit searches the complete repository history for applicant-supplied evidence.

---

## 1. Evidence inventory

### Class A — applicant-supplied evidence (primary)

| Evidence | Location (git-history only) | What it is |
| --- | --- | --- |
| **Applicant source CV** (`SOURCE_CV_EXCERPT`) | `tests/test_dr_frotan_profile.py` — added in `05fbf60`, deleted in `58ae0d5` | The applicant's own CV text, used as the resume input to `build_profile_from_cv_text(...)`; contains professional profile, competencies, all five roles with duty bullets and dates, education, certifications, languages |
| Duplicate of the supervisor bullet + dates | `tests/test_cv_documents_tracker.py` (`05fbf60` …) | Same applicant fact reused as a fixture (`2022-02` / `2022-12`) |

Recovery command: `git show 05fbf60:tests/test_dr_frotan_profile.py`

### Class B — system/AI-authored expansion (NOT applicant evidence)

| Artifact | Why it is not evidence |
| --- | --- |
| `utils/master_cv.py` (`7126a95`, `05fbf60`) | Hardcoded `EXPERIENCE_BULLETS` containing claims the applicant's CV never states ("Led day-to-day Therapeutic Feeding Unit operations", "case investigation, contact tracing", "clinical audits", "coached, mentored", "Managed official correspondence"). This is the origin of much of the 28 drafts' vocabulary. Removed later by the evidence-gate hardening commit. |
| `profile.yaml` `needs_verification` (current) | The 28 system-authored drafts themselves. Each carries `basis: "system-authored scope draft; the applicant supplied no duties for this position"`. |
| `documents/live_market_test_2026-09-30/*` | Generated CVs/cover letters — derivative renders of Class B + profile, not independent evidence. |
| `tests/test_conservative_regressions.py` (current) | Synthetic fixtures ("Confirmed NGO"), not applicant data. |

### Class C — applicant-supplied facts confirmed by derived assertions

`tests/test_dr_frotan_profile.py` also asserts what the evidence builder derives from the source CV: `bphs`, `ephs`, `hmis`, `imam`, `safeguarding_psea`, `moph_coordination`, three languages, and that **no** licence/registration number is stated in the source CV.

---

## 2. The recovered applicant CV (professional content, verbatim)

**Professional profile**

> Medical Doctor with over three years of combined field and supervisory experience across Daikundi Province's health, nutrition, and provincial governance sectors. Proven track record supervising mobile health and nutrition teams delivering BPHS/EPHS and IMAM/CMAM services, maintaining HMIS/DHIS2 reporting and data quality, coordinating medical supply forecasting and logistics, safeguarding (PSEA and Child Protection Focal Point), and cross-sector communication during the COVID-19 emergency response.

**Core competencies** — Provincial & Ministry of Public Health Stakeholder Coordination; Health & Nutrition Program Supervision; Team Supervision & Capacity Building; HMIS / DHIS2 Reporting & Data Quality; Emergency & Outbreak Response (COVID-19); Safeguarding, PSEA & Child Protection; BPHS/EPHS & IMAM/CMAM Program Knowledge.

**Professional experience (supplied duty bullets and dates)**

| Role | Employer · location | Dates | Supplied duties |
| --- | --- | --- | --- |
| TFU Medical Doctor & Safeguarding Focal Point | Action Against Hunger (ACF-International) · Sang-e-Takht TFU, Daikundi | **May 2023 – Jul 2025** | "Maintained accurate HMIS records and served as Safeguarding Focal Point supporting PSEA and child protection." / "Delivered clinical assessment, diagnosis, treatment, and follow-up care for children with SAM applying WHO, IMAM/CMAM, and national clinical protocols." |
| Health and Nutrition Supervisor | Action Against Hunger (ACF-International) · Gizab & Sang-e-Takht, Daikundi | **Feb 2022 – Dec 2022** | "Supervised mobile health and nutrition teams delivering community-based BPHS/EPHS-related services." |
| Medical Doctor / COVID-19 Rapid Response Team Leader | Daikundi Provincial Public Health Directorate · Daikundi, Afghanistan | Oct 2020 – Dec 2020 | "Coordinated with Ministry of Public Health representatives, provincial health authorities, and partner organizations." |
| Public Relations & Communications Advisor | Daikundi Governor's Office · Daikundi, Afghanistan | Dec 2020 – Aug 2021 | "Supported communication and coordination between provincial government departments, NGOs, communities, and development partners." |
| Administrative and Finance Officer | Trend for a Better Tomorrow (TBT) – NGO · Afghanistan | May 2019 – Sep 2019 | "Supported administrative operations, procurement processes, financial documentation, and program logistics." |

Education: MD, Curative Medicine, Kabul Medical Science University 2013–2020. Certifications: Safeguarding & PSEA (ACF 2024); IPC (ACF 2023); HMIS Reporting & Health Data Management (ACF 2023); IMAM, IMNCI, IYCF & Stock Management (ACF 2022). Languages: Dari/Persian native, English fluent, Pashto intermediate.

**Terms the source CV never contains** (checked): OTP, outpatient, inpatient, admitted, audit, case review, quality improvement, awareness, reporting channels, compliance, meetings, health facilities, filing, payment, expenditure, internal procedures, colleagues, counterparts, IPC application, COVID patient care. Those appear only in Class B.

---

## 3. The 28 drafts re-evaluated against Class A

Status key: **VERIFIED_FROM_EXISTING_EVIDENCE** — the applicant's supplied CV explicitly documents the responsibility; **PARTIALLY_SUPPORTED** — only part is documented, retain that part; **NOT_SUPPORTED** — no applicant-supplied statement covers the draft's distinctive claims.

| # | Draft responsibility | Existing applicant evidence that supports it | Evidence source | Status | Recommended action |
| --- | --- | --- | --- | --- | --- |
| 1 | Provided clinical assessment, diagnosis, and treatment for patients admitted to the Therapeutic Feeding Unit with severe acute malnutrition, in line with inpatient SAM and IMAM/CMAM protocols | "Delivered clinical assessment, diagnosis, treatment, and follow-up care for children with SAM applying WHO, IMAM/CMAM, and national clinical protocols." | Source CV — TFU role | VERIFIED_FROM_EXISTING_EVIDENCE | Confirm. Use the CV's wording; drop "admitted"/"inpatient" (not supplied) |
| 2 | Monitored clinical progress, documented inpatient care, and prepared patients for continued outpatient follow-up through OTP services | "…and follow-up care for children with SAM" | Source CV — TFU role | PARTIALLY_SUPPORTED | Retain follow-up care for children with SAM only; drop monitoring/inpatient/outpatient/OTP |
| 3 | Applied infection prevention and control measures within the inpatient therapeutic feeding unit | none — IPC appears only as a certificate title | Source CV (certificate list only) | NOT_SUPPORTED | Keep held; certificate ≠ duty performed |
| 4 | Acted as site Safeguarding and PSEA Focal Point, supporting safeguarding, child-protection, and protection-from-sexual-exploitation-and-abuse awareness, reporting channels, and compliance with organizational policy | "served as Safeguarding Focal Point supporting PSEA and child protection" | Source CV — TFU role | PARTIALLY_SUPPORTED | Retain the appointment + PSEA/child-protection support; drop awareness/reporting channels/policy compliance |
| 5 | Maintained HMIS and nutrition data on TFU activity and supported periodic health reporting to project and health-authority counterparts | "Maintained accurate HMIS records"; "maintaining HMIS/DHIS2 reporting and data quality" | Source CV — TFU role + profile | PARTIALLY_SUPPORTED | Retain HMIS records / HMIS-DHIS2 reporting and data quality; drop the named recipients |
| 6 | Took part in clinical audit, case review, and quality-improvement activity to support quality of care in the therapeutic feeding unit | none (vocabulary originates in `utils/master_cv.py`) | — | NOT_SUPPORTED | Keep held |
| 7 | Liaised with health facility and provincial health counterparts on service-delivery coordination, medical supply needs, and reporting | none for this role (coordination is documented for the COVID role; supply forecasting is a general statement) | Source CV — other roles only | NOT_SUPPORTED | Keep held; do not move another role's evidence here |
| 8 | Supervised health and nutrition service delivery across ACF-supported coverage areas in Gizab and Sang-e-Takht districts, Daikundi | "Supervised mobile health and nutrition teams delivering community-based BPHS/EPHS-related services." | Source CV — Supervisor role | VERIFIED_FROM_EXISTING_EVIDENCE | Confirm. Use the CV's wording ("mobile … teams", "community-based BPHS/EPHS-related services") |
| 9 | Supported IMAM/CMAM implementation, including SAM/MAM case identification, OTP service linkage, and adherence to national nutrition treatment protocols | "…teams delivering BPHS/EPHS and IMAM/CMAM services" | Source CV — profile + Supervisor role | PARTIALLY_SUPPORTED | Retain IMAM/CMAM service delivery; drop SAM/MAM identification, OTP linkage, protocol adherence |
| 10 | Supervised and built the capacity of health and nutrition staff through work planning, on-the-job coaching, and training follow-up | "Supervised mobile health and nutrition teams…" | Source CV — Supervisor role | PARTIALLY_SUPPORTED | Retain supervision of mobile health and nutrition teams; drop capacity-building methods |
| 11 | Conducted field monitoring visits and reviewed service records, registers, and reports to support data quality and timely HMIS reporting | "maintaining HMIS/DHIS2 reporting and data quality" | Source CV — profile | PARTIALLY_SUPPORTED | Retain HMIS/DHIS2 reporting and data quality; drop visits/records/registers |
| 12 | Coordinated with MoPH and provincial health-authority counterparts, community stakeholders, and partner teams to support BPHS/EPHS-aligned service delivery | "…delivering community-based BPHS/EPHS-related services" | Source CV — Supervisor role | PARTIALLY_SUPPORTED | Retain BPHS/EPHS-related service delivery; the MoPH/provincial coordination belongs to the COVID role (see #15/#17/#20) |
| 13 | Supported quality-of-care activities, including review of clinical and nutrition documentation and follow-up of corrective actions with service providers | none | — | NOT_SUPPORTED | Keep held |
| 14 | Monitored nutrition and medical supply availability at supported sites and supported forecasting, stock follow-up, and logistics coordination with the project team | "coordinating medical supply forecasting and logistics" | Source CV — professional profile | PARTIALLY_SUPPORTED | Retain medical supply forecasting and logistics; drop site monitoring/stock follow-up/team coordination |
| 15 | Led the provincial COVID-19 rapid response team and coordinated rapid-response activity with the Provincial Public Health Directorate | Role title (supplied) + "Coordinated with Ministry of Public Health representatives, provincial health authorities, and partner organizations." + "cross-sector communication during the COVID-19 emergency response" | Source CV — COVID role + profile | VERIFIED_FROM_EXISTING_EVIDENCE | Confirm |
| 16 | Provided clinical assessment, medical guidance, and case-management support for COVID-19 patients, in line with national protocols and infection prevention and control measures | none (clinical care is documented for the TFU role, not the COVID role) | — | NOT_SUPPORTED | Keep held |
| 17 | Supported outbreak response coordination and follow-up with health facilities and provincial health authorities | "Coordinated with Ministry of Public Health representatives, provincial health authorities, and partner organizations." | Source CV — COVID role | PARTIALLY_SUPPORTED | Retain the CV's coordination wording; drop "health facilities" (not named) |
| 18 | Collected and reported response data through HMIS and provincial reporting channels, supporting situation reporting for the provincial response | HMIS/DHIS2 reporting and data quality are supplied — but under the ACF roles, not the COVID role | Source CV — profile + TFU role | PARTIALLY_SUPPORTED | Retain HMIS/DHIS2 reporting only if recorded against the correct role; do not attribute it to the COVID role |
| 19 | Supported infection prevention and control and public-health measures within the provincial response, in line with BPHS/EPHS service structures | none (IPC = certificate; BPHS/EPHS = Supervisor role) | — | NOT_SUPPORTED | Keep held |
| 20 | Participated in coordination meetings with health-sector stakeholders, partners, and provincial authorities | "Coordinated with Ministry of Public Health representatives, provincial health authorities, and partner organizations." | Source CV — COVID role | VERIFIED_FROM_EXISTING_EVIDENCE | Confirm; use the CV's wording ("Coordinated with…"); drop "meetings" (not supplied) |
| 21 | Advised the Governor's Office on public relations and communications and prepared official communications and public information materials | Role title (supplied) + "Supported communication and coordination between provincial government departments, NGOs, communities, and development partners." | Source CV — Governor's Office role | PARTIALLY_SUPPORTED | Retain the advisory role and the communication/coordination support; drop preparing official materials |
| 22 | Coordinated public information activities with provincial departments and partner organizations | "Supported communication and coordination between provincial government departments, NGOs, communities, and development partners." | Source CV — Governor's Office role | VERIFIED_FROM_EXISTING_EVIDENCE | Confirm; use the CV's wording; drop "public information activities" phrasing |
| 23 | Supported stakeholder engagement and information-sharing between the provincial office, community representatives, and health-sector partners | "…between provincial government departments, NGOs, communities, and development partners." | Source CV — Governor's Office role | PARTIALLY_SUPPORTED | Retain the documented parties (provincial departments, NGOs, communities, development partners); drop "health-sector partners" |
| 24 | Maintained reporting and documentation of public relations and communication activities for the office | none | — | NOT_SUPPORTED | Keep held |
| 25 | Supported day-to-day administrative operations, office documentation, and filing for programme activities | "Supported administrative operations, procurement processes, financial documentation, and program logistics." | Source CV — TBT role | PARTIALLY_SUPPORTED | Retain administrative operations and program logistics; drop office documentation/filing |
| 26 | Supported finance and procurement documentation, including payment records and expenditure paperwork, in line with internal procedures | "…procurement processes, financial documentation…" | Source CV — TBT role | PARTIALLY_SUPPORTED | Retain procurement processes and financial documentation; drop payment records/expenditure/internal procedures |
| 27 | Maintained supply and stock records and supported follow-up of administrative issues with the responsible officer | none for this role ("program logistics" only) | — | NOT_SUPPORTED | Keep held |
| 28 | Coordinated with programme colleagues and external counterparts on administrative follow-up and reporting | none | — | NOT_SUPPORTED | Keep held |

**Tally:** VERIFIED_FROM_EXISTING_EVIDENCE **5** (#1, #8, #15, #20, #22) · PARTIALLY_SUPPORTED **14** (#2, #4, #5, #9, #10, #11, #12, #14, #17, #18, #21, #23, #25, #26) · NOT_SUPPORTED **9** (#3, #6, #7, #13, #16, #19, #24, #27, #28).

---

## 4. Additional recovered facts (reported, not applied)

1. **The two ACF roles were supplied with dates**: TFU **May 2023 – Jul 2025**, Supervisor **Feb 2022 – Dec 2022**. `profile.yaml` currently records them as blank with the comment that no dates were supplied, and the release suite asserts blank. This is a normalization loss, not an absence of applicant evidence. Acting on it would require an owner decision and matching test updates.
2. **Applicant wording the normalized profile dropped**: "children with SAM" (not "patients"), "WHO … protocols", "community-based" services, "mobile" teams, "three years of combined field and supervisory experience", and the seven supplied core competencies.
3. **Provenance of the unsupported drafts**: the vocabulary of drafts #3, #6, #13, #16, #19, #24, #27, #28 (and the unsupported halves of several partial drafts) matches the hardcoded `EXPERIENCE_BULLETS` in `utils/master_cv.py`, an AI/system-authored expansion — not applicant material.
4. **Licence/registration**: the source CV states registration status but contains no number, authority, or dates — consistent with the current profile. Nothing to recover.

## 5. Implication for the verification gate

The gate must ask **"did the applicant supply this fact?"**, where "supplied" means *documented in any applicant-authored artifact* (this CV), not *present in the normalized `profile.yaml`*. Under that rule:

* 5 drafts are already supported and need no owner interview;
* 14 need only their unsupported wording trimmed, not re-proving;
* 9 remain genuinely unsupported and stay held.

Sections 1-5 above were written before any edit was made: at that point `profile.yaml` was untouched and no CV wording had been generated. Section 6 records the restoration that was applied afterwards.

---

## 6. Restoration applied to the canonical profile

The owner authorised the restoration on 2026-10-07: `profile.yaml` may be updated **only** from
applicant-supplied CV evidence, restoring the facts documented in section 2 and section 4 above.
Nothing outside that evidence was added, no date or number was invented, and the private-reference
boundary is unchanged.

### 6.1 Dates restored

The two ACF-International roles now carry the supplied dates instead of blank fields:

| Role | Supplied start | Supplied end |
| --- | --- | --- |
| TFU Medical Doctor & Safeguarding Focal Point | `2023-05` (May 2023) | `2025-07` (Jul 2025) |
| Health & Nutrition Supervisor | `2022-02` (Feb 2022) | `2022-12` (Dec 2022) |

The three remaining roles already carried their supplied dates and were left untouched. No other
date changed, and behaviour that previously asserted "no dates supplied" for the ACF roles was
rewritten to assert the supplied pairs (`acf_dates_supplied` in `utils/profile.py`).

### 6.2 Responsibilities rebuilt

The 28 drafts were rebuilt by status. **6** applicant-supported responsibilities are now recorded as
verified (one or two per role, every one traceable to a line in section 2), and **24** drafts remain
held in `needs_verification` because no applicant evidence covers them. **15** of those held drafts
carry a `restored_portion` field naming the part of their wording that was restored, so nothing is
silently dropped from the review history.

| Role | Verified responsibilities restored |
| --- | --- |
| TFU Medical Doctor & Safeguarding Focal Point | 2 (clinical assessment/diagnosis/treatment/follow-up for children with SAM under WHO, IMAM/CMAM and national protocols; HMIS records and Safeguarding Focal Point supporting PSEA and child protection) |
| Health & Nutrition Supervisor | 1 (supervised mobile health and nutrition teams delivering community-based BPHS/EPHS-related services and IMAM/CMAM services) |
| Medical Doctor / COVID-19 Rapid Response Team Leader | 1 (coordinated with Ministry of Public Health representatives, provincial health authorities and partner organizations) |
| Public Relations & Communications Advisor | 1 (supported communication and coordination between provincial government departments, NGOs, communities and development partners) |
| Administrative and Finance Officer | 1 (supported administrative operations, procurement processes, financial documentation and program logistics) |

Held back: **24** drafts (TFU 6, Supervisor 6, COVID-19 RRT 5, PR & Communications 3, Admin & Finance 4).
The nine NOT_SUPPORTED drafts of section 3 stay held in full; the fourteen PARTIALLY_SUPPORTED drafts
keep only their supported portion. Banned wording (OTP, outpatient, inpatient, clinical audit, case
review, quality improvement, awareness activity, reporting channels, compliance monitoring, liaison,
coordination meetings, filing, payment records, internal procedures, colleagues, external
counterparts, and every invented metric or outcome) is **not** restored anywhere.

### 6.3 Competencies and profile-level facts

* Verified competencies now include the applicant-supplied set: health & nutrition program
  implementation, IMAM/CMAM, SAM, TFU, IMNCI, IYCF, IPC, BPHS/EPHS, HMIS/DHIS2, MoPH
  liaison/coordination, emergency/outbreak/COVID response, stakeholder coordination,
  safeguarding/PSEA, child protection, medical supply forecasting/logistics, procurement/admin/finance
  support, and team supervision/capacity building, plus the supplied "more than three years of
  combined field and supervisory experience".
* Two competencies stay **held** (`verified: false`) because no applicant artifact supports them:
  *Clinical audit/quality improvement* and *Field monitoring/reporting*. They are excluded from every
  generated document.

### 6.4 What this changes downstream

The Master CV stays position-neutral and prints one to two applicant-supported scope lines per role
plus the competencies, certificates, education, registration status, exit exam, languages and all five
roles; tailored CVs remain downstream projections that never mutate the canonical record. The held
drafts continue to be reported to the owner (dashboard and review warning) and are excluded from every
employer-facing document by the generator itself.

The pre-recovery 28-item review is preserved byte-for-byte as the frozen owner-confirmed record, and is
archived as `docs/archive/responsibility_review_28_items_pre_recovery.md`. It documents the state
*before* the applicant's CV evidence was recovered, so it is history rather than a second list to
action. The single authoritative, always-current review artifact is the regenerated
`docs/held_responsibility_review.md`, and the release suite asserts both: the archived one unchanged,
the generated one in sync with the canonical record.
