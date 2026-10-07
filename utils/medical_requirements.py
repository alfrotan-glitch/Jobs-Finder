"""
Deterministic medical-job requirement extraction.

This module deliberately avoids LLM calls.  It extracts facts that can be
identified from a vacancy text with rules: education/license requirements,
clinical and Afghanistan health-sector terms, application instructions,
reference numbers, closing dates, locations, gender/nationality/residency
constraints, and provenance snippets.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any
from urllib.parse import urlparse

from utils.source_registry import canonical_source_name

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_DIGIT_TRANSLATION = str.maketrans({
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
})

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

AFGHAN_PROVINCES = [
    "Badakhshan",
    "Badghis",
    "Baghlan",
    "Balkh",
    "Bamyan",
    "Daykundi",
    "Farah",
    "Faryab",
    "Ghazni",
    "Ghor",
    "Helmand",
    "Herat",
    "Jowzjan",
    "Kabul",
    "Kandahar",
    "Kapisa",
    "Khost",
    "Kunar",
    "Kunduz",
    "Laghman",
    "Logar",
    "Nangarhar",
    "Nimroz",
    "Nuristan",
    "Paktia",
    "Paktika",
    "Panjshir",
    "Parwan",
    "Samangan",
    "Sar-e-Pul",
    "Sar-e Pul",
    "Takhar",
    "Uruzgan",
    "Wardak",
    "Maidan Wardak",
    "Zabul",
]

DISTRICT_PATTERNS = [r"\bDistrict\b", r"\bdistricts\b", r"\bfield\s+office\b", r"\bfield\s+deployment\b"]

MEDICAL_ROLE_TERMS = [
    "md",
    "m.d.",
    "mbbs",
    "medical doctor",
    "doctor of medicine",
    "physician",
    "medical officer",
    "doctor",
    "clinician",
    "surgeon",
    "surgery",
    "surgical",
]

MEDICAL_DISCOVERY_KEYWORDS = [
    "medical officer",
    "medical doctor",
    "physician",
    "doctor",
    "md",
    "mbbs",
    "clinician",
    "surgeon",
    "surgery",
    "surgical",
    "health officer",
    "public health",
    "nutrition",
    "moph",
    "hospital",
    "clinic",
    "primary health care",
    "community health",
    "mental health",
    "reproductive health",
    "maternal health",
    "polio",
    "immunization",
    "vaccination",
    "vaccinator",
    "nurse",
    "midwife",
    "pharmacy",
    "pharmacist",
    "laboratory",
    "phc",
    "bphs",
    "ephs",
    "hmis",
    "imnci",
    "imam",
    "srhr",
    "ipc",
]

UNKNOWN_SOURCE_TOKENS = {
    "",
    "unknown",
    "unknown source",
    "n/a",
    "na",
    "none",
    "not specified",
    "not provided",
    "malformed",
}

EMAIL_PATTERN = r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}"

MD_ACCEPTANCE_PATTERNS = [
    r"\bM\.?D\.?\b",
    r"\bMBBS\b",
    r"\bMedical\s+Doctor\b",
    r"\bDoctor\s+of\s+Medicine\b",
    r"\bPhysician\b",
    r"\bMedical\s+Officer\b",
    r"\bDoctor\s*\(\s*MD\s*\)\b",
]

# An MD/physician mention in the vacancy BODY only counts as an accepted
# qualification when it appears in a credential/qualification context.  Real
# vacancies for other professions routinely mention doctors in their duties
# ("Work closely with the medical doctor...", "Contact the physician for
# inaccuracy in prescription order...") and such coordination wording must
# never convert a nurse/pharmacist vacancy into an MD-compatible role.
MD_QUALIFICATION_CONTEXT_CUES = [
    r"degree",
    r"diploma",
    r"certificat",
    r"qualif",
    r"graduat",
    r"educat",
    r"faculty",
    r"universit",
    r"licen[cs]",
    r"regist",
    r"council",
    r"\brequired\b",
    r"\brequirements?\b",
    r"must\s+(?:be|hold|have)",
    r"\bpreferred\b",
    r"\bbackground\b",
    r"\bcandidates?\b",
    r"\bapplicants?\b",
    r"\bholder\b",
    r"or\s+equivalent",
    r"\bspecialist\b",
    r"exit\s+exam",
]

# Coordination/referral phrases that immediately precede a mention of a
# doctor/physician describe ANOTHER staff member's involvement in the duties,
# never the qualification accepted for the advertised role.
MD_DUTY_MENTION_PREFIXES = [
    r"(?:work(?:s|ing)?\s+(?:closely\s+)?|in\s+(?:close\s+)?(?:coordination|collaboration|liaison)\s+|coordinat\w*\s+|collaborat\w*\s+|liais\w*\s+|communicat\w*\s+|consult\w*\s+)with\s+(?:the|a|an|other|all)?\s*$",
    r"(?:contact(?:ing)?|call|inform|notify)\s+(?:the|a|an)?\s*$",
    r"(?:under\s+(?:the\s+)?(?:direct\s+)?supervision\s+of|supervised\s+by|referred?\s+(?:by|to)|report(?:s|ing)?\s+to|prescribed\s+by|accompan\w+)\s+(?:the|a|an)?\s*$",
]

MD_ROLE_TITLE_PATTERNS = [
    r"\bmedical\s+doctor\b",
    r"\bmedical\s+officer\b",
    r"\bphysician\b",
    r"\bclinician\b",
    r"\bdoctor\b",
    r"\bM\.?D\.?\b",
    r"\bMBBS\b",
]

# Health-domain role families: a regulated-health domain prefix combined with
# a role-holder noun. The noun set deliberately includes genuine health-domain
# practitioner/coordination nouns (mentor/trainer/focal point) so e.g.
# "Nutrition Trainer" or "HMIS focal point" are recognized as the health roles
# they are, instead of falling into "ambiguous health words". Generic
# programme/operations titles with no health-domain noun in the TITLE
# ("Project Manager", "CLIC Operator", ...) are intentionally NOT matched
# here: they may stay in broad discovery, but they are never classified as a
# compatible professional role for recommendation.
_PUBLIC_HEALTH_ROLE_DOMAINS = r"(?:public\s+health|health(?:\s+and\s+nutrition)?|nutrition|HMIS|health\s+data|clinical)"
_PUBLIC_HEALTH_ROLE_NOUNS = r"(?:officer|advisor|specialist|coordinator|manager|supervisor|mentor|trainer|focal\s+point)"
PUBLIC_HEALTH_ROLE_PATTERNS = [
    rf"\b{_PUBLIC_HEALTH_ROLE_DOMAINS}\s+{_PUBLIC_HEALTH_ROLE_NOUNS}\b",
    r"\bhealth\s+(?:project|programme|program)\s+manager\b",
    r"\bmedical\s+coordinator\b",
]

# An MD is a general medical qualification, not proof of a specialist
# credential. Keep these titles in an explicit manual-verification family even
# when a title also contains a broad word such as physician or surgeon.
SPECIALIST_MEDICAL_ROLES: list[dict[str, Any]] = [
    {
        "key": "pediatric_specialist",
        "label": "pediatric specialist role",
        "title_patterns": [r"\bpa?ediatrician\b", r"\bpa?ediatric\s+(?:specialist|physician|doctor)\b"],
        "evidence_keys": ["pediatric_specialist"],
    },
    {
        "key": "general_surgeon",
        "label": "general-surgeon role",
        "title_patterns": [r"\bgeneral\s+surgeon\b", r"\bsurgeon\s+specialist\b"],
        "evidence_keys": ["medical_specialist"],
    },
    {
        "key": "specialist_physician",
        "label": "specialist-physician role",
        "title_patterns": [r"\bspecialist\s+(?:physician|doctor)\b", r"\bmedical\s+specialist\b"],
        "evidence_keys": ["medical_specialist"],
    },
]

ROLE_DUTY_COMPATIBILITY_PATTERNS = [
    r"\bclinical\b",
    r"\bpatient\b",
    r"\bdiagnos(?:is|e)\b",
    r"\btreatment\b",
    r"\bOPD\b",
    r"\bPHC\b",
    r"primary\s+health\s*care",
    r"\bHMIS\b",
    r"\bhealth\s+data\b",
    r"\bIMAM\b",
    r"\bCMAM\b",
    r"\bSAM\b",
    r"\bTFU\b",
    r"therapeutic\s+feeding",
    r"\bmalnutrition\b",
    r"\bsupervis(?:e|ion|ory)\b",
    r"\bcoordinat(?:e|ion|or)\b",
    r"\bMoPH\b",
    r"Ministry\s+of\s+Public\s+Health",
]

INCOMPATIBLE_PROFESSIONAL_ROLES: list[dict[str, Any]] = [
    {
        "key": "nursing",
        "label": "nursing / nurse-specific role",
        "title_patterns": [r"\b(?:staff\s+)?nurse\b", r"\bnursing\b", r"\bnutrition\s+nurse\b"],
        "qualification_patterns": [r"\bregistered\s+nurse\b", r"\bnursing\s+(?:degree|diploma|certificate|license|licence)\b", r"\bvalid\s+nurs(?:e|ing)\s+licen[cs]e\b"],
    },
    {
        "key": "midwifery",
        "label": "midwifery-specific role",
        "title_patterns": [r"\bmidwife\b", r"\bmidwifery\b"],
        "qualification_patterns": [r"\bmidwifery\s+(?:degree|diploma|certificate|license|licence)\b", r"\bregistered\s+midwife\b"],
    },
    {
        "key": "pharmacy",
        "label": "pharmacy / pharmacist-specific role",
        "title_patterns": [r"\bpharmacist\b", r"\bpharmacy\s+(?:officer|assistant|technician|manager|supervisor)\b"],
        "qualification_patterns": [r"\b(?:B\.?Sc\.?|Bachelor(?:'s)?)\s+(?:degree\s+)?in\s+pharmacy\b", r"\bPharm\s*D\b", r"\bpharmacy\s+(?:degree|license|licence|registration)\b"],
    },
    {
        "key": "laboratory",
        "label": "laboratory-specific role",
        "title_patterns": [r"\blab(?:oratory)?\s+(?:technician|technologist|officer|assistant|manager)\b", r"\blaboratory\b"],
        "qualification_patterns": [r"\blab(?:oratory)?\s+(?:degree|diploma|certificate|license|licence)\b", r"\bmedical\s+laboratory\s+technology\b"],
    },
    {
        "key": "radiology",
        "label": "radiology / imaging-specific role",
        "title_patterns": [r"\bradiolog(?:y|ist|ic)\b", r"\bx[-\s]?ray\s+(?:technician|technologist|officer)\b", r"\bultrasound\s+(?:technician|technologist)\b"],
        "qualification_patterns": [r"\bradiology\s+(?:degree|diploma|certificate|license|licence)\b", r"\bmedical\s+imaging\s+(?:degree|diploma|certificate)\b"],
    },
    {
        "key": "dentistry",
        "label": "dentist / dental-specific role",
        "title_patterns": [r"\bdentist\b", r"\bdental\s+(?:doctor|surgeon|officer|assistant|technician)\b"],
        "qualification_patterns": [r"\bdental\s+(?:degree|diploma|license|licence|registration)\b", r"\bdoctor\s+of\s+dental\s+(?:surgery|medicine)\b", r"\bDDS\b", r"\bDMD\b"],
    },
    {
        "key": "physiotherapy",
        "label": "physiotherapy-specific role",
        "title_patterns": [r"\bphysiotherapist\b", r"\bphysical\s+therapist\b", r"\bphysiotherapy\b"],
        "qualification_patterns": [r"\bphysiotherapy\s+(?:degree|diploma|license|licence|registration)\b", r"\bphysical\s+therapy\s+(?:degree|diploma|license|licence)\b"],
    },
    {
        "key": "nutrition_promoter",
        "label": "nutrition promoter / community-promotion role",
        "title_patterns": [r"\bnutrition\s+promot(?:er|or)\b", r"\bcommunity\s+nutrition\s+(?:promot(?:er|or)|worker)\b"],
        "qualification_patterns": [r"\bnutrition\s+promot(?:er|or)\s+(?:certificate|experience)\b"],
    },
    {
        "key": "vaccinator",
        "label": "vaccinator / EPI-certificate role",
        "title_patterns": [r"\bvaccinator\b", r"\bEPI\s+vaccinator\b"],
        "qualification_patterns": [r"\bvaccin(?:ation|ator)\s+certificate\b", r"\bEPI\s+(?:certificate|certification)\b"],
    },
    {
        # Psychology/psychosocial counselling is its own professional
        # credential track (e.g. "Bachelor's degree or above in psychology,
        # and counselling / MoPH approved 2 years diploma in psychosocial
        # counselling"); an MD is not eligible unless the vacancy explicitly
        # accepts MD/physician credentials.
        "key": "psychology_counselling",
        "label": "psychology / psychosocial-counselling-specific role",
        "title_patterns": [
            r"\bcounsel?lor\b",
            r"\bpsychologist\b",
            r"\bpsychosocial\s+(?:counsel?lor|worker)\b",
            r"\bmental\s+health\s+promot(?:er|or)\b",
            r"\bMHPSS\s+(?:counsel?lor|assistant|promot(?:er|or)|worker)\b",
        ],
        "qualification_patterns": [
            r"\b(?:degree|diploma|bachelor(?:'s)?|master(?:'s)?)\s+(?:or\s+above\s+)?in\s+(?:clinical\s+)?psycholog(?:y|ical)\b",
            r"\bdiploma\s+in\s+psychosocial\s+counsel?ling\b",
            r"\bpsychosocial\s+counsel?ling\s+(?:diploma|certificate|degree)\b",
            r"\bregistered\s+psychologist\b",
        ],
    },
]

TERM_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "md_degree": {
        "label": "Medical degree (MD / MBBS / physician)",
        "patterns": [
            r"\bM\.?D\.?\b",
            r"\bMBBS\b",
            r"\bMedical Doctor\b",
            r"\bDoctor of Medicine\b",
            r"\bPhysician\b",
            r"\bMedical Officer\b",
        ],
        "criticality": "essential",
    },
    "license_registration": {
        "label": "Professional license / registration",
        "patterns": [
            r"\b(valid\s+)?medical\s+licen[cs]e\b",
            r"\bprofessional\s+licen[cs]e\b",
            r"\b(valid\s+)?medical\s+registration\b",
            r"\bprofessional\s+registration\b",
            r"\bmedical\s+professional\s+registration\b",
            r"\bregistered\s+(?:with|at|by)\s+(?:the\s+)?(?:medical\s+council|professional\s+body|MoPH)\b",
            r"\bMoPH\s+registration\b",
            r"\bmedical\s+council\b",
        ],
        "criticality": "essential",
    },
    "license_number": {
        "label": "License / registration number",
        "patterns": [
            r"\b(?:medical\s+|professional\s+)?(?:licen[cs]e|registration)\s*(?:number|no\.?|#)\b",
            r"\b(?:number|no\.?)\s+(?:of\s+)?(?:the\s+)?(?:medical\s+|professional\s+)?(?:licen[cs]e|registration)\b",
        ],
        "criticality": "essential",
    },
    "license_document": {
        "label": "License / registration document",
        "patterns": [
            r"\b(?:attach|upload|submit|provide|include|send)\b.{0,80}\b(?:copy|scan|document|certificate)\b.{0,80}\b(?:medical\s+|professional\s+)?(?:licen[cs]e|registration)\b",
            r"\b(?:attach|upload|submit|provide|include|send)\b.{0,80}\b(?:medical\s+|professional\s+)?(?:licen[cs]e|registration)\b.{0,80}\b(?:copy|scan|document|certificate)\b",
        ],
        "criticality": "essential",
    },
    "health_public_education": {
        "label": "Relevant health / public-health education",
        "patterns": [
            r"\brelevant\s+education\s+in\s+(?:social\s+sciences?\s*,?\s*)?public\s+health(?:\s*,?\s*(?:and|or)\s*community\s+development)?",
            r"\beducation\s+in\s+(?:social\s+sciences?\s*,?\s*)?public\s+health(?:\s*,?\s*(?:and|or)\s*community\s+development)?",
        ],
        "criticality": "essential",
    },
    "medical_exit_exam": {
        "label": "Medical exit examination",
        # Do not include Medical Council Exam here. The two qualifications are
        # not interchangeable absent wording in the vacancy that actually
        # establishes an exit-exam requirement.
        "patterns": [
            r"\bexit\s+exam(?:ination)?\b",
            r"\bmedical\s+exit\s+exam(?:ination)?\b",
            r"ایگزیت\s*امتحان",
        ],
        "criticality": "essential",
    },
    "medical_council_exam": {
        "label": "Medical Council Exam",
        "patterns": [
            r"\bmedical\s+council\s+exam(?:ination)?\b",
            r"امتحان\s+شورای\s+طبی",
        ],
        "criticality": "essential",
    },
    "medical_specialist": {
        "label": "Medical specialist qualification",
        "patterns": [
            r"\binternal\s+medicine\s+specialist\b",
            r"\bgeneral\s+surgeon\b",
            r"\bsurgeon\s+specialist\b",
            r"\bspecialist\s+surgeon\b",
            r"\bspeciali[sz]ation\s+in\s+general\s+surgery\b",
            r"\bspecialist\s+certification\s+in\s+general\s+surgery\b",
            r"\bspecial(?:ty|ist)\s+certificate\s+in\s+general\s+surgery\b",
            r"\bspecial(?:ty|ist)\s+degree\s+in\s+general\s+surgery\b",
            r"\bpostgraduate\s+(?:degree|qualification)\s+in\s+general\s+surgery\b",
            r"\bdermatolog(?:y|ist)\b",
            r"\baesthetic\s+medicine\b",
            r"\bmedical\s+doctor\s*[–-]\s*dermatology\b",
            r"\bcardiology\s+specialist\b",
            r"\bpostgraduate\s+specialty\s+qualification\s+in\s+cardiology\b",
            r"\binterventional\s+cardiology\b",
            r"\bfellowship\s*/?\s*certification\s+in\s+(?:interventional\s+)?cardiology\b",
            r"\bsurgical\s+oncology\b",
            r"\bmaster'?s?\s+degree\s+or\s+above\s+in\s+surgical\s+oncology\b",
        ],
        "criticality": "essential",
    },
    "specialist_obgyn": {
        "label": "Obstetrician-gynecologist specialization",
        "patterns": [
            r"obstetrician[-/\s]*gynecologist",
            r"\bob(?:s|y)?\s*/\s*gyn(?:ecologist)?\b",
            r"\bobgyn\b",
            r"\bgynecology\b",
            r"\bgyn/obs\b",
            r"speciali[sz]ation\s+program\s+in\s+obstetrician",
        ],
        "criticality": "essential",
    },
    "pharmacy_degree": {
        "label": "Pharmacy degree / PharmD",
        "patterns": [
            r"\bB\.?Sc\.?\s+in\s+Pharmacy\b",
            r"\bBachelor(?:'s)?\s+degree\s+in\s+pharmacy\b",
            r"\bPharm\s*D\b",
            r"\bpharmacy\s+degree\b",
        ],
        "criticality": "essential",
    },
    "nursing_midwifery_certificate": {
        "label": "Nursing / midwifery certificate",
        "patterns": [
            r"\bnursing\s*/\s*midwifery\s+certificate\b",
            r"\bnursing\s+(?:or|and)\s+midwifery\s+certificate\b",
            r"\bnursing\s+certificate\b",
            r"\bmidwifery\s+certificate\b",
            r"\bdiploma\s+in\s+(?:nursing|midwifery)\b",
            r"\bdegree\s+in\s+(?:nursing|midwifery)\b",
            r"\bbachelor(?:'s)?\s+degree\s+in\s+(?:clinical\s+|emergency\s+|intensive\s+care\s+)?nursing\b",
            r"\bregistered\s+nurse\b",
            r"\bvalid\s+nurs(?:e|ing)\s+licen[cs]e\b",
        ],
        "criticality": "essential",
    },
    "pediatric_specialist": {
        "label": "Pediatrics specialist degree",
        "patterns": [
            r"\bspecial(?:ty|ist)\s+degree\s*\(?\s*pediatrics\s*\)?",
            r"\bpediatric(?:s)?\s+specialist\b",
            r"\bspeciali[sz]ation\s+in\s+pediatric(?:s)?\b",
            r"\bpaediatric(?:s)?\s+specialist\b",
        ],
        "criticality": "essential",
    },
    "vaccination_certificate": {
        "label": "Vaccination certificate / EPI credential",
        "patterns": [
            r"\bvaccination\s+certificate\b",
            r"\bvaccinator\s+certificate\b",
            r"\bEPI\s+(?:certificate|certification|training)\b",
            r"\b(?:Ministry|MoPH)\s+vaccination\s+certificate\b",
        ],
        "criticality": "essential",
    },
    "psychosocial_counseling": {
        "label": "Psychosocial / counselling experience",
        "patterns": [
            r"\bpsychosocial\s+support\b",
            r"\bpsychological\s+support\b",
            r"\bcounsell?or\b.{0,80}\b(?:CP|GBV|PwSN|survivors?|specific\s+needs)\b",
            r"\bmental\s+health\s+promoter\b",
            r"\bindividual\s+counselling\b",
        ],
        "criticality": "essential",
    },
    "quality_improvement": {
        "label": "Quality improvement / patient safety",
        "patterns": [
            r"\bquality\s+improvement\b",
            r"\bquality\s+assurance\b",
            r"\bQA\s*/\s*QI\b",
            r"\bclinical\s*/\s*service\s+audit\b",
        ],
        "criticality": "essential",
    },
    "afghanistan_experience": {
        "label": "Afghanistan health-sector experience",
        "patterns": [r"(?:experience|work|worked|based|within).{0,40}\bAfghanistan\b", r"\bAfghanistan\b.{0,40}(?:experience|work|based)", r"\bMoPH\b", r"\bMinistry of Public Health\b"],
        "criticality": "important",
    },
    "bphs": {"label": "BPHS", "patterns": [r"\bBPHS\b", r"Basic Package of Health Services"], "criticality": "important"},
    "ephs": {"label": "EPHS", "patterns": [r"\bEPHS\b", r"Essential Package of Hospital Services"], "criticality": "important"},
    "phc": {"label": "PHC / primary health care", "patterns": [r"\bPHC\b", r"primary health\s*care"], "criticality": "important"},
    "hmis": {"label": "HMIS / DHIS2", "patterns": [r"\bHMIS\b", r"\bDHIS2\b", r"DHIS\s*2", r"health management information system"], "criticality": "important"},
    "imnci": {"label": "IMNCI", "patterns": [r"\bIMNCI\b"], "criticality": "important"},
    "imam": {"label": "IMAM / CMAM", "patterns": [r"\bIMAM\b", r"\bCMAM\b", r"integrated management of acute malnutrition", r"community(?:-based)? management of acute malnutrition"], "criticality": "important"},
    "nutrition": {"label": "Nutrition", "patterns": [r"\bnutrition(?:al)?\b", r"\bmalnutrition\b", r"\bIYCF\b", r"\bSAM\b", r"\bMAM\b", r"\bOTP\b", r"\bTFU\b"], "criticality": "important"},
    "srhr": {"label": "SRHR", "patterns": [r"\bSRHR\b", r"sexual and reproductive health", r"reproductive health"], "criticality": "important"},
    "ipc": {"label": "IPC", "patterns": [r"\bIPC\b", r"infection prevention", r"infection control"], "criticality": "important"},
    "ngo_humanitarian": {
        "label": "Humanitarian / NGO experience",
        "patterns": [r"\bNGO\b", r"\bINGO\b", r"humanitarian", r"emergency response", r"donor"],
        "criticality": "important",
    },
    "reporting": {"label": "Reporting", "patterns": [r"\breporting\b", r"prepare reports", r"monthly reports"], "criticality": "important"},
    "supervision_management": {
        "label": "Supervision / management",
        "patterns": [r"\bsupervis(?:e|ion|ory)\b", r"\bmanage(?:ment|r| team)?\b", r"team lead", r"line manager", r"capacity building"],
        "criticality": "important",
    },
    "moph_coordination": {
        "label": "MoPH / health authority coordination",
        "patterns": [r"\bMoPH\b", r"Ministry of Public Health", r"provincial public health", r"health authorit(?:y|ies)"],
        "criticality": "important",
    },
    "safeguarding_psea": {
        "label": "Safeguarding / PSEA / child protection",
        "patterns": [r"\bsafeguarding\b", r"\bPSEA\b", r"protection from sexual exploitation", r"child protection"],
        "criticality": "important",
    },
    "emergency_response": {
        "label": "Emergency / outbreak response",
        "patterns": [r"emergency response", r"outbreak", r"COVID-?19", r"rapid response", r"contact tracing"],
        "criticality": "important",
    },
    "supply_logistics": {
        "label": "Medical supply / logistics",
        "patterns": [r"medical supply", r"stock (?:management|monitoring)", r"forecasting", r"logistics", r"procurement"],
        "criticality": "important",
    },
}

LANGUAGE_PATTERNS = {
    "english": [r"\bEnglish\b"],
    "dari": [r"\bDari\b"],
    "pashto": [r"\bPashto\b", r"\bPushto\b"],
}

REQUIRED_WORDS = [
    "required",
    "requirement",
    "must",
    "mandatory",
    "essential",
    "minimum",
    "at least",
    "should have",
    "need to have",
    "qualification",
]
PREFERRED_WORDS = ["preferred", "desirable", "advantage", "asset", "plus", "preferably"]


@dataclass
class Requirement:
    key: str
    label: str
    required: str = "Required"  # Required | Preferred | Information
    value: Any = True
    evidence: list[str] = field(default_factory=list)
    source_field: str = "description"
    criticality: str = "important"  # essential | important | info

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedRequirements:
    requirements: list[Requirement]
    facts: dict[str, Any]
    provenance: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirements": [r.to_dict() for r in self.requirements],
            "facts": self.facts,
            "provenance": self.provenance,
        }


def strip_html(text: str) -> str:
    """Convert rough HTML to readable text without adding dependencies."""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<\s*br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*(p|li|div|h\d|tr)\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    return text.strip()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", strip_html(text).translate(_DIGIT_TRANSLATION)).strip()


def requirement_relevant_text(clean_text: str) -> str:
    """Return the vacancy sections that should drive eligibility extraction.

    Many ACBAR pages include a long "About the Company" section listing all
    programs an organization runs.  Those background terms are useful context but
    should not become applicant requirements.  Keep Job Summary/Description, Job
    Requirements, and Submission text when those markers exist; otherwise use the
    original text.
    """
    if not clean_text:
        return ""
    lower = clean_text.lower()
    starts = [
        idx for marker in [
            "job summary",
            "job description",
            "job requirements",
            "requirements:",
            "qualifications:",
            "qualification and education",
        ]
        if (idx := lower.find(marker)) >= 0
    ]
    if not starts:
        return clean_text
    start = min(starts)
    ends = [
        idx for marker in ["similar jobs", "acbar highlights", "member highlights"]
        if (idx := lower.find(marker, start)) > start
    ]
    end = min(ends) if ends else len(clean_text)
    scoped = clean_text[start:end].strip()
    return scoped or clean_text


def _snippet(text: str, start: int, end: int, width: int = 110) -> str:
    left = max(0, start - width // 2)
    right = min(len(text), end + width // 2)
    snip = text[left:right]
    snip = re.sub(r"\s+", " ", snip).strip(" .;:-")
    return snip


def _required_level(text: str, start: int, end: int) -> str:
    window = text[max(0, start - 100): min(len(text), end + 100)].lower()
    if any(word in window for word in REQUIRED_WORDS):
        return "Required"
    if any(word in window for word in PREFERRED_WORDS):
        return "Preferred"
    return "Required"


def _find_first(patterns: Iterable[str], text: str) -> tuple[str, int, int] | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0), match.start(), match.end()
    return None


def _add_requirement(
    requirements: list[Requirement],
    provenance: list[dict[str, str]],
    key: str,
    label: str,
    text: str,
    match_start: int,
    match_end: int,
    value: Any = True,
    criticality: str = "important",
    source_field: str = "description",
) -> None:
    if any(r.key == key for r in requirements):
        return
    quote = _snippet(text, match_start, match_end)
    level = _required_level(text, match_start, match_end)
    requirements.append(
        Requirement(
            key=key,
            label=label,
            required=level,
            value=value,
            evidence=[quote] if quote else [],
            source_field=source_field,
            criticality=criticality,
        )
    )
    provenance.append({"field": key, "source": source_field, "quote": quote})


# ---------------------------------------------------------------------------
# Canonical source / application-route helpers
# ---------------------------------------------------------------------------


def is_valid_http_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(str(url).strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and "." in parsed.netloc
    except Exception:
        return False


def is_valid_email(value: str | None) -> bool:
    return bool(re.fullmatch(EMAIL_PATTERN, str(value or "").strip(), flags=re.IGNORECASE))


def is_valid_application_route(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text.lower().startswith("mailto:"):
        text = text.split(":", 1)[1].split("?", 1)[0].strip()
    return is_valid_email(text) or is_valid_http_url(text)


def _first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            nested = _first_string(*value)
            if nested:
                return nested
            continue
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_valid_http(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            nested = _first_valid_http(*value)
            if nested:
                return nested
            continue
        text = str(value or "").strip()
        if is_valid_http_url(text):
            return text
    return ""


def _metadata_from_job(job: Any) -> dict[str, Any]:
    get = job.get if isinstance(job, dict) else lambda key, default=None: getattr(job, key, default)
    metadata = get("metadata", {}) or {}
    if isinstance(metadata, str):
        try:
            import json

            parsed = json.loads(metadata)
            metadata = parsed if isinstance(parsed, dict) else {}
        except Exception:
            metadata = {}
    return metadata if isinstance(metadata, dict) else {}


def _job_get(job: Any, key: str, default: Any = "") -> Any:
    return job.get(key, default) if isinstance(job, dict) else getattr(job, key, default)


def source_name_is_valid(value: str | None) -> bool:
    text = str(value or "").strip().lower()
    return bool(text and text not in UNKNOWN_SOURCE_TOKENS)


def canonical_source_fields(job: Any) -> dict[str, Any]:
    """Canonical, non-guessed source/application-route model for a vacancy.

    The function only normalizes data already present on the source item. It
    never fabricates a source name or URL. A direct application destination is
    an email or an HTTP(S) application/form URL; an official vacancy page is
    retained as a manual review route but does not by itself prove the job is
    ready to apply.
    """
    metadata = _metadata_from_job(job)
    title = _first_string(_job_get(job, "title"), metadata.get("title"))
    employer = _first_string(_job_get(job, "company"), _job_get(job, "organization"), metadata.get("company"), metadata.get("organization"), metadata.get("employer"))
    source_name = canonical_source_name(_first_string(_job_get(job, "source_name"), metadata.get("source_name"), metadata.get("source"), _job_get(job, "platform"), _job_get(job, "source")))

    source_url = _first_valid_http(
        _job_get(job, "source_url"),
        metadata.get("source_url"),
        metadata.get("source_listing_url"),
        metadata.get("source_homepage"),
    )
    vacancy_url = _first_valid_http(_job_get(job, "vacancy_url"), metadata.get("vacancy_url"), _job_get(job, "url"), metadata.get("url"))
    # Do not fabricate listing/source provenance from a vacancy page. These are
    # intentionally independent concepts: a vacancy URL can prove where the
    # posting was read, but it cannot prove its source/listing URL. Consumers
    # must display ``missing`` until the source actually provides one.

    requested_method = _first_string(_job_get(job, "application_method"), metadata.get("application_method")).upper()
    raw_apply = _first_string(
        _job_get(job, "apply_url"),
        metadata.get("apply_url"),
        metadata.get("application_url"),
        _job_get(job, "apply_email"),
        metadata.get("apply_email"),
        metadata.get("application_email"),
    )
    application_email = ""
    application_url = ""
    for candidate in [_job_get(job, "apply_email"), metadata.get("apply_email"), metadata.get("application_email"), raw_apply]:
        text = str(candidate or "").strip()
        if text.lower().startswith("mailto:"):
            text = text.split(":", 1)[1].split("?", 1)[0].strip()
        if is_valid_email(text):
            application_email = text
            break

    for candidate in [metadata.get("application_url"), metadata.get("apply_url"), _job_get(job, "apply_url"), raw_apply]:
        text = str(candidate or "").strip()
        if not is_valid_http_url(text):
            continue
        # A source/vacancy page is not a web application route unless the
        # source explicitly provided it as a web application/form route.
        if vacancy_url and text == vacancy_url and requested_method not in {"WEB", "ONLINE_FORM"}:
            continue
        application_url = text
        break

    if application_email:
        application_method = "EMAIL"
        apply_email = application_email
        apply_url = application_url or None
    elif application_url:
        application_method = "WEB"
        apply_email = ""
        apply_url = application_url
    else:
        application_method = "UNAVAILABLE"
        apply_email = ""
        apply_url = None

    direct_route = application_email or application_url

    problems: list[str] = []
    if not source_name_is_valid(source_name):
        problems.append("missing_or_unknown_source_name")
    if not source_url:
        problems.append("missing_or_invalid_source_url")
    if not vacancy_url and not direct_route:
        problems.append("missing_official_vacancy_url_or_application_route")
    if not title:
        problems.append("missing_title")
    if not employer or employer.strip().lower() in UNKNOWN_SOURCE_TOKENS or employer.strip().lower() in {"unknown employer", "unknown organization", "unknown org"}:
        problems.append("missing_identifiable_employer")
    if raw_apply and not is_valid_application_route(raw_apply):
        problems.append("malformed_application_route")

    source_valid = not any(problem in problems for problem in [
        "missing_or_unknown_source_name",
        "missing_or_invalid_source_url",
        "missing_official_vacancy_url_or_application_route",
        "missing_title",
        "missing_identifiable_employer",
    ])
    return {
        "source_name": source_name,
        "source_url": source_url,
        "vacancy_url": vacancy_url,
        "apply_url": apply_url,
        "apply_email": apply_email,
        "application_method": application_method,
        "application_email": application_email,
        "application_url": application_url,
        "direct_application_route": direct_route,
        # A source-valid vacancy may remain discoverable for manual route
        # verification; this does not make its application route actionable.
        "direct_application_route_actionable": source_valid and bool(direct_route),
        "source_valid": source_valid,
        "is_actionable": source_valid and bool(vacancy_url or direct_route),
        "problems": problems,
    }


def has_actionable_source(job: Any) -> bool:
    return bool(canonical_source_fields(job).get("is_actionable"))


# ---------------------------------------------------------------------------
# Role-family compatibility extraction
# ---------------------------------------------------------------------------


def _pattern_hit(patterns: Iterable[str], text: str) -> tuple[str, int, int] | None:
    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            return match.group(0), match.start(), match.end()
    return None


def _md_qualification_acceptance_hit(text: str) -> tuple[str, int, int] | None:
    """Find an MD/physician mention that is genuinely an accepted qualification.

    A mention only counts when (a) its surrounding window contains a
    credential/qualification cue (degree, diploma, licence, required, ...)
    and (b) it is not immediately preceded by a coordination/referral phrase
    such as "work closely with the" or "contact the", which describe duties
    involving another staff member rather than the accepted credential.
    """
    for pattern in MD_ACCEPTANCE_PATTERNS:
        for match in re.finditer(pattern, text or "", flags=re.IGNORECASE):
            window = text[max(0, match.start() - 90): match.end() + 90]
            if not any(re.search(cue, window, flags=re.IGNORECASE) for cue in MD_QUALIFICATION_CONTEXT_CUES):
                continue
            prefix = text[max(0, match.start() - 45): match.start()]
            if any(re.search(duty, prefix, flags=re.IGNORECASE) for duty in MD_DUTY_MENTION_PREFIXES):
                continue
            return match.group(0), match.start(), match.end()
    return None


def _md_is_accepted(title: str, scoped_text: str) -> bool:
    """True when the role title or qualifications accept MD/physician credentials.

    Title mentions (e.g. "Medical Doctor (MD)") always count.  Body mentions
    count only in a qualification context -- an incidental duty mention of a
    doctor/physician never makes a different professional role MD-compatible.
    """
    if _pattern_hit(MD_ACCEPTANCE_PATTERNS, title or "") is not None:
        return True
    return _md_qualification_acceptance_hit(scoped_text or "") is not None


def analyze_professional_role(title: str, text: str) -> dict[str, Any]:
    clean_title = normalize_text(title)
    scoped = requirement_relevant_text(normalize_text(text))
    role_text = "\n".join(part for part in [clean_title, scoped] if part) or clean_title
    md_accepted = _md_is_accepted(clean_title, scoped)
    md_title = _pattern_hit(MD_ROLE_TITLE_PATTERNS, clean_title)

    blocker: dict[str, Any] | None = None
    blocker_hit: tuple[str, int, int] | None = None
    for spec in INCOMPATIBLE_PROFESSIONAL_ROLES:
        blocker_hit = _pattern_hit(spec["title_patterns"], clean_title)
        if not blocker_hit:
            blocker_hit = _pattern_hit(spec["qualification_patterns"], scoped)
        if blocker_hit:
            blocker = spec
            break

    if blocker and not md_accepted:
        quote_text = clean_title if _pattern_hit(blocker["title_patterns"], clean_title) else scoped
        _, start, end = blocker_hit or ("", 0, 0)
        return {
            "classification": "incompatible_professional_role",
            "role_family": blocker["key"],
            "label": blocker["label"],
            "md_accepted": False,
            "requires_md": False,
            "evidence": _snippet(quote_text, start, end) if quote_text else blocker["label"],
            "explanation": f"The vacancy is {blocker['label']} and does not state that an MD/physician qualification is accepted.",
        }

    for specialist in SPECIALIST_MEDICAL_ROLES:
        specialist_hit = _pattern_hit(specialist["title_patterns"], clean_title)
        if specialist_hit:
            _, start, end = specialist_hit
            return {
                "classification": "specialist_qualification_required",
                "role_family": specialist["key"],
                "label": specialist["label"],
                "md_accepted": False,
                "requires_md": True,
                "specialist_evidence_keys": specialist["evidence_keys"],
                "evidence": _snippet(clean_title, start, end) or clean_title,
                "explanation": "This is a specialist role. A general MD alone does not prove the specifically required specialty qualification; verify the actual specialist credential.",
            }

    if md_title or md_accepted:
        hit = md_title or _pattern_hit(MD_ACCEPTANCE_PATTERNS, clean_title) or _md_qualification_acceptance_hit(scoped) or ("", 0, 0)
        quote_text = clean_title if md_title or _pattern_hit(MD_ACCEPTANCE_PATTERNS, clean_title) else scoped
        _, start, end = hit
        return {
            "classification": "md_physician_role",
            "role_family": "medical_doctor_physician",
            "label": "MD / physician-compatible role",
            "md_accepted": True,
            "requires_md": True,
            "evidence": _snippet(quote_text, start, end) if quote_text else "MD/physician qualification accepted",
            "explanation": "The role title or qualifications explicitly accept MD/medical-doctor/physician credentials.",
        }

    public_health_hit = _pattern_hit(PUBLIC_HEALTH_ROLE_PATTERNS, clean_title)
    compatible_duty_hit = _pattern_hit(ROLE_DUTY_COMPATIBILITY_PATTERNS, role_text)
    if public_health_hit and compatible_duty_hit:
        _, start, end = public_health_hit
        return {
            "classification": "health_public_health_compatible",
            "role_family": "medical_public_health_nutrition",
            "label": "Medical/public-health/nutrition-compatible role",
            "md_accepted": False,
            "requires_md": False,
            "evidence": _snippet(clean_title, start, end) or clean_title,
            "explanation": "The actual role family and duties are health/public-health/nutrition coordination rather than a different professional license.",
        }

    if looks_medical(role_text):
        return {
            "classification": "ambiguous_health_words",
            "role_family": "ambiguous_health_or_medical_words",
            "label": "Ambiguous health/medical wording",
            "md_accepted": False,
            "requires_md": False,
            "evidence": _snippet(role_text, 0, min(len(role_text), 80)) if role_text else "health/medical terminology",
            "explanation": "The vacancy contains health/medical/nutrition words, but the role family and accepted qualification are not specific enough.",
        }

    return {
        "classification": "not_medical_or_public_health",
        "role_family": "other",
        "label": "Not a medical/public-health role",
        "md_accepted": False,
        "requires_md": False,
        "evidence": clean_title or _snippet(role_text, 0, min(len(role_text), 80)),
        "explanation": "No medical-doctor/public-health role family was deterministically identified.",
    }


def parse_closing_date(text: str, today: date | None = None) -> str | None:
    """Extract the first likely closing/deadline date and return ISO date."""
    if not text:
        return None
    today = today or date.today()
    label = r"(?:closing\s+date|deadline|apply\s+by|valid\s+until|last\s+date|submission\s+deadline|(?:send|submit|email)\b[^.\n]{0,120}\bby)"
    windows = []
    for match in re.finditer(label, text, flags=re.IGNORECASE):
        windows.append(text[match.start(): match.start() + 180])
    # Submission prose often reads "send CV to name@example.org by DATE".
    # Dots in an email address prevent a naïve sentence-only label regex from
    # reaching `by`; a date immediately following `by` is nevertheless a
    # strong deadline signal.
    for match in re.finditer(r"\bby\s+(?=(?:20\d{2})[-/.]|\d{1,2}[-/.]|[A-Za-z]{3,9}\s+\d)", text, flags=re.IGNORECASE):
        windows.append(text[match.start(): match.start() + 120])
    if not windows:
        # Some ACBAR-style cards show "Close date: ..." or just "Close: ...".
        for close_match in re.finditer(r"(?:close\s+date|close|expires?)", text, flags=re.IGNORECASE):
            windows.append(text[close_match.start(): close_match.start() + 160])
    search_space = "\n".join(windows) if windows else text[:300]

    date_patterns = [
        # 2026-09-30 or 2026/09/30
        r"(?P<y>20\d{2})[-/\.](?P<m>0?[1-9]|1[0-2])[-/\.](?P<d>[12]\d|3[01]|0?[1-9])",
        # 30-09-2026, 30/09/2026
        r"(?P<d>[12]\d|3[01]|0?[1-9])[-/\.](?P<m>0?[1-9]|1[0-2])[-/\.](?P<y>20\d{2})",
        # 30 September 2026
        r"(?P<d>[12]\d|3[01]|0?[1-9])(?:st|nd|rd|th)?\s+(?P<mon>[A-Za-z]{3,9})\s*,?\s+(?P<y>20\d{2})",
        # September 30, 2026
        r"(?P<mon>[A-Za-z]{3,9})\s+(?P<d>[12]\d|3[01]|0?[1-9])(?:st|nd|rd|th)?\s*,?\s+(?P<y>20\d{2})",
        # 30 September (assume current year, roll forward if already passed)
        r"(?P<d>[12]\d|3[01]|0?[1-9])(?:st|nd|rd|th)?\s+(?P<mon>[A-Za-z]{3,9})(?!\s*\d)",
    ]
    for pattern in date_patterns:
        date_match = re.search(pattern, search_space, flags=re.IGNORECASE)
        if not date_match:
            continue
        parts = date_match.groupdict()
        try:
            year = int(parts.get("y") or today.year)
            if parts.get("mon"):
                month = MONTHS.get(parts["mon"].lower())
                if not month:
                    continue
            else:
                month = int(parts["m"])
            day = int(parts["d"])
            parsed = date(year, month, day)
            if not parts.get("y") and parsed < today:
                parsed = date(today.year + 1, month, day)
            return parsed.isoformat()
        except (TypeError, ValueError):
            continue
    return None


def _normalize_number_words(text: str) -> str:
    text = (text or "").translate(_DIGIT_TRANSLATION)

    def repl(match):
        return str(NUMBER_WORDS.get(match.group(1).lower(), match.group(1))) + " years"

    return re.sub(r"\b(" + "|".join(NUMBER_WORDS) + r")\s+(?:years?|yrs?)\b", repl, text, flags=re.IGNORECASE)


def _minimum_years_from_match(match: re.Match) -> int:
    groups = match.groupdict()
    if groups.get("low"):
        return int(groups["low"])
    return int(groups.get("years") or 0)


def _experience_scope(context: str) -> str:
    """Classify the vacancy's requested experience dimension conservatively."""
    context = (context or "").lower()
    if any(term in context for term in ["pharmacy", "pharmacist", "pharmaceutical", "pharmacy technician"]):
        return "pharmacy_experience_years"
    if any(term in context for term in ["health and nutrition", "health & nutrition", "health/nutrition", "nutrition program", "nutrition programme", "nutrition experience", "imam", "cmam", "sam", "mam", "tfu", "otp"]):
        return "health_nutrition_experience_years"
    if any(term in context for term in ["management", "supervis", "lead", "coordinat", "mentor", "capacity", "مدیریت", "نظارت", "هماهنگ"]):
        return "management_experience_years"
    if any(term in context for term in ["clinical", "medical", "hospital", "clinic", "phc", "primary health", "patient", "curative", "doctor", "gp", "صحی", "کلینیک"]):
        return "clinical_experience_years"
    if any(term in context for term in ["ngo", "ingo", "humanitarian", "emergency", "donor", "red cross", "red crescent", "un agencies", "بشر دوستانه", "موسسات غیر دولتی", "هلال احمر"]):
        return "ngo_experience_years"
    if any(term in context for term in ["public health", "health program", "health sector", "health systems", "moph", "hmis", "صحت عامه", "برنامه های صحی"]):
        return "afghanistan_health_experience_years" if ("afghan" in context or "afghanistan" in context) else "public_health_experience_years"
    if any(term in context for term in ["frontline", "field experience", "field-based", "field based"]):
        return "frontline_experience_years"
    return "general_experience_years"


def extract_years_requirement(text: str) -> dict[str, int]:
    """Return minimum years required by scope: clinical/general/ngo/management.

    Ranges such as ``3-5 years`` are treated conservatively as a 3-year
    minimum, not a 5-year hard requirement. Common Dari/Persian digits and the
    word ``سال`` are also handled for Afghanistan vacancies.
    """
    years: dict[str, int] = {}
    if not text:
        return years
    text = _normalize_number_words(text)
    year_word = r"(?:years?|yrs?|سال)"
    exp_word = r"(?:experience|work|تجربه)"
    range_value = r"(?:(?P<low>\d{1,2})\s*(?:-|–|—|to)\s*(?P<high>\d{1,2})|(?P<years>\d{1,2})\+?)"
    patterns = [
        rf"(?:(?:minimum|at least|least|over|حد\s*اقل)\s+)?{range_value}\s*{year_word}\s+(?:of\s+)?(?P<context>.{{0,100}}?){exp_word}",
        rf"(?P<context>clinical|medical|relevant|NGO|INGO|humanitarian|management|supervisory|public health|health program|health sector|pharmacy|صحی|مدیریت|نظارت).{{0,70}}?{range_value}\s*{year_word}",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = _minimum_years_from_match(match)
            if not value:
                continue
            captured_context = (match.groupdict().get("context") or "")
            scope = _experience_scope(captured_context)
            surrounding = f"{captured_context} {text[max(0, match.start() - 60): min(len(text), match.end() + 100)]}"
            surrounding_scope = _experience_scope(surrounding)
            explicit_clinical_context = re.search(
                r"(?:clinical|curative|patient|hospital|clinic)\W{0,20}(?:experience|work)"
                r"|(?:experience|work)\W{0,40}(?:clinical|curative|patient|hospital|clinic)",
                surrounding,
                flags=re.IGNORECASE,
            )
            if scope == "general_experience_years" or (
                scope == "clinical_experience_years"
                and not explicit_clinical_context
                and surrounding_scope in {
                    "management_experience_years",
                    "public_health_experience_years",
                    "afghanistan_health_experience_years",
                    "ngo_experience_years",
                    "pharmacy_experience_years",
                }
            ):
                scope = surrounding_scope
            years[scope] = max(years.get(scope, 0), value)

    pharmacy_alternative_min: int | None = None
    for sentence in re.split(r"[.\n;]+", text):
        sentence_lower = sentence.lower()
        if "pharmac" in sentence_lower and " or " in sentence_lower:
            nums = [_minimum_years_from_match(m) for m in re.finditer(rf"{range_value}\s*{year_word}", sentence, flags=re.IGNORECASE)]
            nums = [n for n in nums if n > 0]
            if len(nums) >= 2:
                pharmacy_alternative_min = min(nums) if pharmacy_alternative_min is None else min(pharmacy_alternative_min, min(nums))

    # Dari/Persian common order: "تجربه کاری حد اقل 5 سال ... مدیریت برنامه های صحی".
    persian_pattern = rf"(?P<context>.{{0,80}}?(?:تجربه|کاری).{{0,80}}?)(?:حد\s*اقل\s+)?{range_value}\s*{year_word}(?P<tail>.{{0,120}})"
    for match in re.finditer(persian_pattern, text, flags=re.IGNORECASE):
        value = _minimum_years_from_match(match)
        if not value:
            continue
        context = f"{match.groupdict().get('context') or ''} {match.groupdict().get('tail') or ''}".lower()
        scope = _experience_scope(context)
        years[scope] = max(years.get(scope, 0), value)
    if pharmacy_alternative_min is not None:
        years["pharmacy_experience_years"] = min(
            years.get("pharmacy_experience_years", pharmacy_alternative_min),
            pharmacy_alternative_min,
        )
    return years


def _clean_reference_candidate(value: str) -> str:
    return (value or "").strip().strip(".,;:()[]{}")


def _looks_like_reference_number(value: str, *, explicit_label: bool = False) -> bool:
    candidate = _clean_reference_candidate(value)
    if not candidate or len(candidate) < 3 or len(candidate) > 80:
        return False
    if "@" in candidate or "://" in candidate:
        return False
    # Clinical acronyms and prose paths such as OPD/IPD/emergency or
    # absent/sick/long-stay are not vacancy/reference numbers.  Real vacancy
    # codes from ACBAR/NGOs normally contain at least one digit; explicit labels
    # may allow all-uppercase separator codes, but generic scans must not.
    if not re.search(r"\d", candidate):
        return explicit_label and bool(re.fullmatch(r"[A-Z][A-Z0-9]*(?:[-_/][A-Z0-9]{2,})+", candidate))
    return bool(re.fullmatch(r"[A-Z0-9][A-Z0-9/_\-.]{2,}", candidate, flags=re.IGNORECASE))


def extract_reference_number(text: str) -> str | None:
    explicit_patterns = [
        r"\b(?:Vacancy|Reference|Ref(?:erence)?|VN|Job\s*ID|Requisition|Announcement)\b\s*(?:No\.?|Number|#|ID)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/_\-.]{2,})",
    ]
    for pattern in explicit_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = _clean_reference_candidate(match.group(1))
            if _looks_like_reference_number(candidate, explicit_label=True):
                return candidate
    generic_patterns = [
        r"\b([A-Z]{2,8}(?:[-_/][A-Z0-9]{2,}){2,})\b",
    ]
    for pattern in generic_patterns:
        match = re.search(pattern, text)
        if match:
            candidate = _clean_reference_candidate(match.group(1))
            if _looks_like_reference_number(candidate):
                return candidate
    return None


def extract_application_email(text: str) -> str | None:
    match = re.search(EMAIL_PATTERN, text, flags=re.IGNORECASE)
    return match.group(0) if match else None


def extract_urls(text: str) -> list[str]:
    urls = re.findall(r"https?://[^\s<>\"')\],;]+", text or "", flags=re.IGNORECASE)
    cleaned: list[str] = []
    for url in urls:
        value = url.rstrip(".,;:!?)]")
        if value not in cleaned:
            cleaned.append(value)
    return cleaned


def extract_application_url(text: str, fallback: str = "") -> str | None:
    """Return only a direct application/form URL, never an arbitrary link.

    A vacancy, organisation, careers, job-board, document, or source URL is
    not an application route merely because it appears in the text. A URL is
    retained only when the URL itself is an established application endpoint
    or the surrounding source instruction explicitly tells the applicant to
    apply/submit through that URL. ``fallback`` is accepted only from a caller
    that already holds a source-provided direct application URL.
    """
    urls = extract_urls(text)
    endpoint_terms = [
        "apply", "application", "applicationform", "forms.gle", "docs.google.com/forms",
        "greenhouse", "lever.co", "workday", "smartrecruiters",
    ]
    for url in urls:
        lower = url.lower()
        if any(term in lower for term in endpoint_terms):
            return url
        escaped = re.escape(url)
        # Keep the window narrow enough that a generic job-page link in an
        # unrelated paragraph cannot acquire application semantics.
        if re.search(
            rf"(?:apply|application|submit|complete|fill\s+in|register)[^.\n]{{0,100}}{escaped}|{escaped}[^.\n]{{0,100}}(?:apply|application|submit|complete|fill\s+in|register)",
            text or "",
            flags=re.IGNORECASE,
        ):
            return url
    return fallback if is_valid_http_url(fallback) else None


def is_valid_application_url(url: str | None) -> bool:
    return is_valid_http_url(url)


def extract_application_subject(text: str, title: str = "") -> str | None:
    if title and (
        re.search(r"\b(?:mention|write|include|indicat(?:e|ing))\b[^\n\r]{0,120}\b(?:job\s+title|position(?:\s+title)?|title)\b[^\n\r]{0,120}\bsubject\b", text or "", flags=re.IGNORECASE)
        or re.search(r"\bmention\b[^\n\r]{0,80}\bposition\b[^\n\r]{0,120}\bsubject\b", text or "", flags=re.IGNORECASE)
    ):
        if not re.search(r"\b(?:(?:vacancy|reference|ref\.?|announcement)\s*(?:number|no\.?|#)?|position\s+code|job\s+code)\b", text or "", flags=re.IGNORECASE):
            return title
    patterns = [
        r"(?:email\s+)?subject(?:\s+line)?\s*(?:must\s+be|should\s+be|as)?\s*[:\-]\s*[\"']?([^\n\r\"']{3,120})",
        r"write\s+[\"']([^\"']{3,120})[\"']\s+in\s+the\s+subject",
        r"mention\s+[\"']([^\"']{3,120})[\"']\s+in\s+the\s+subject",
        r"subject[^\n\r]{0,80}?(?:like|as)\s*\(?\s*\*{0,2}([A-Z0-9][A-Z0-9/_\-.]{2,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            subject = match.group(1).strip().strip(" .;:")
            # Avoid consuming the next instruction sentence.
            subject = re.split(r"\s{2,}|\.\s+", subject)[0].strip()
            if subject.lower() in {"not", "required", "mandatory", "is mandatory", "not exposed", "not provided"}:
                return None
            return subject
    return None


def application_subject_required(text: str) -> bool:
    """Detect an actual application-email subject instruction.

    The word ``subject`` is common in legal, policy, and employment language
    (for example, "the employee will be subject to organisational policies").
    It is never sufficient on its own. The surrounding context must connect a
    subject/عنوان to email submission or explicitly direct the applicant to
    include a job title, vacancy/reference code, or position code there.
    """
    text = text or ""
    english_patterns = [
        # "Email subject: ...", "Subject line must include vacancy code".
        r"\b(?:email|e-mail)\s+subject(?:\s+line)?\b[^.\n]{0,160}\b(?:must|should|include|write|mention|indicate|state|use|required|as)\b",
        r"\bsubject\s+line\b[^.\n]{0,160}\b(?:must|should|include|write|mention|indicate|state|use|required|as)\b",
        r"\b(?:write|mention|include|indicate|state|use)\b[^.\n]{0,100}\b(?:job\s+title|position(?:\s+title)?|vacancy(?:\s+(?:number|no\.?|code|reference))?|reference(?:\s+(?:number|no\.?|code))?|(?:job|position)\s+code)\b[^.\n]{0,100}\b(?:email|e-mail)\s+(?:subject|subject\s+line)\b",
        r"\b(?:write|mention|include|indicate|state|use)\b[^.\n]{0,100}\b(?:job\s+title|position(?:\s+title)?|vacancy(?:\s+(?:number|no\.?|code|reference))?|reference(?:\s+(?:number|no\.?|code))?|(?:job|position)\s+code)\b[^.\n]{0,100}\bsubject(?:\s+line)?\b",
        r"\b(?:email|e-mail)\b[^.\n]{0,100}\b(?:subject|subject\s+line)\b[^.\n]{0,100}\b(?:job\s+title|position(?:\s+title)?|vacancy|reference|(?:job|position)\s+code)\b",
    ]
    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in english_patterns):
        return True
    # Common Dari/Persian wording. It requires the email/subject context plus
    # an instruction to write/include the vacancy title or code; a free word
    # عنوان elsewhere on a page is deliberately ignored.
    persian_patterns = [
        r"(?:موضوع|عنوان)\s*(?:ایمیل|ايميل).{0,160}(?:باید|بايد|الزامی|الزامى|ذکر|درج|بنویسید|بنويسيد|شامل).{0,120}(?:کد|كود|کُد|كد|عنوان\s*بست|شماره\s*بست)",
        r"(?:ایمیل|ايميل).{0,120}(?:موضوع|عنوان).{0,160}(?:کد|كود|کُد|كد|عنوان\s*بست|شماره\s*بست).{0,120}(?:باید|بايد|الزامی|الزامى|ذکر|درج|بنویسید|بنويسيد|شامل)",
        r"(?:در\s*)?(?:موضوع|عنوان)\s*(?:ایمیل|ايميل).{0,100}(?:عنوان|کد|كود|کُد|كد)\s*بست",
    ]
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in persian_patterns)


def extract_locations(text: str, explicit_location: str = "") -> list[str]:
    found: list[str] = []
    combined = f"{explicit_location}\n{text}"
    combined = re.sub(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", " ", combined, flags=re.IGNORECASE)
    combined = re.sub(r"https?://\S+", " ", combined, flags=re.IGNORECASE)
    for province in AFGHAN_PROVINCES:
        if re.search(rf"\b{re.escape(province)}\b", combined, flags=re.IGNORECASE):
            canonical = "Sar-e-Pul" if province.lower().replace(" ", "-") in {"sar-e-pul", "sar-e pul"} else province
            if canonical not in found:
                found.append(canonical)
    if re.search(r"\bKabul\b", combined, flags=re.IGNORECASE) and "Kabul" not in found:
        found.append("Kabul")
    if any(re.search(p, combined, flags=re.IGNORECASE) for p in DISTRICT_PATTERNS):
        if "Field / district deployment" not in found:
            found.append("Field / district deployment")
    return found


_GENDER_UNRESTRICTED_PATTERN = r"\b(?:male\s*/\s*female|female\s*/\s*male|male\s+and\s+female|female\s+and\s+male|all\s+genders|any\s+gender|gender\s*[:\-]?\s*any)\b"


def extract_labeled_gender_requirement(text: str) -> str | None:
    """Detect a structured source gender field such as ACBAR's quick-summary row.

    ACBAR detail pages carry a hard "Gender" field whose label and value are
    separate elements, so the extracted page text reads "Gender Female"
    without a colon.  This is source-structured data, not free prose: the
    narrow label-value adjacency below only matches that form (or the
    colon/dash form) and never generic wording such as "non-discrimination
    based on race, gender, age".
    """
    lower = normalize_text(text).lower()
    if not lower:
        return None
    if re.search(_GENDER_UNRESTRICTED_PATTERN, lower):
        return None
    if re.search(r"\bgender\s*[:\-]?\s*(?:female|women)\b", lower):
        return "female"
    if re.search(r"\bgender\s*[:\-]?\s*(?:male|men)\b", lower):
        return "male"
    return None


def extract_gender_requirement(text: str) -> str | None:
    lower = normalize_text(text).lower()
    if not lower:
        return None
    if re.search(_GENDER_UNRESTRICTED_PATTERN, lower):
        return None

    # Preferences/encouragement are not hard eligibility constraints.
    if (
        re.search(r"\b(?:female|women)\s+(?:candidates?\s+)?(?:are\s+)?(?:strongly\s+)?(?:encouraged|preferred)\b", lower)
        or re.search(r"\bfemale\s+candidate\s+(?:is\s+)?(?:a\s+)?(?:point\s+)?plus\b", lower)
    ):
        return "female_encouraged"
    if re.search(r"\b(?:male|men)\s+(?:candidates?\s+)?(?:are\s+)?(?:strongly\s+)?(?:encouraged|preferred)\b", lower):
        return "male_encouraged"

    hard_patterns = [
        ("female", r"\bgender\s*[:\-]?\s*(?:female|women)\b"),
        ("male", r"\bgender\s*[:\-]?\s*(?:male|men)\b"),
        ("female", r"\b(?:sex|gender)\s*[:\-]\s*(?:woman|women)\b"),
        ("male", r"\b(?:sex|gender)\s*[:\-]\s*(?:man|men)\b"),
        ("female", r"\(\s*(?:female|women)(?:\s+only)?\s*\)"),
        ("male", r"\(\s*(?:male|men)(?:\s+only)?\s*\)"),
        ("female", r"\b(?:interested\s+and\s+)?qualified\s+(?:female|women)\s+candidates\s+(?:can|may|should|are\s+(?:invited|requested)\s+to)\s+(?:apply|submit)"),
        ("male", r"\b(?:interested\s+and\s+)?qualified\s+(?:male|men)\s+candidates\s+(?:can|may|should|are\s+(?:invited|requested)\s+to)\s+(?:apply|submit)"),
        ("female", r"\b(?:female|women)\s+only\b"),
        ("male", r"\b(?:male|men)\s+only\b"),
        ("female", r"\bonly\s+(?:female|women)\b"),
        ("male", r"\bonly\s+(?:male|men)\b"),
        ("female", r"\b(?:must\s+be|required\s+to\s+be|candidates?\s+must\s+be|applicants?\s+must\s+be)\s+(?:female|women)\b"),
        ("male", r"\b(?:must\s+be|required\s+to\s+be|candidates?\s+must\s+be|applicants?\s+must\s+be)\s+(?:male|men)\b"),
        ("female", r"\b(?:female|women)\s+(?:applicants?|candidates?|staff)\s+(?:only|required)\b"),
        ("male", r"\b(?:male|men)\s+(?:applicants?|candidates?|staff)\s+(?:only|required)\b"),
        ("female", r"^\s*female\s+(?:medical\s+doctor|doctor|md|physician|nurse|midwife|staff|officer)\b"),
        ("male", r"^\s*male\s+(?:medical\s+doctor|doctor|md|physician|nurse|staff|officer)\b"),
    ]
    for value, pattern in hard_patterns:
        if re.search(pattern, lower, flags=re.IGNORECASE):
            return value
    return None


def extract_nationality_requirement(text: str) -> str | None:
    lower = text.lower()
    if (
        re.search(r"\bafghan\s+(?:national|citizen|applicant)s?\b", lower)
        or "national position" in lower
        or re.search(r"\bnationality\s*[:\-]\s*(?:afghan|national)\b", lower)
    ):
        return "Afghan"
    if (
        "international position" in lower
        or "expatriate" in lower
        or re.search(r"\btype\s*[:\-]?\s*international\b", lower)
        or re.search(r"\bcandidate\s+must\s+be\s+(?:a\s+)?national\s+of\s+(?:a\s+)?country\s+other\s+than\s+the\s+country\s+of\s+assignment\b", lower)
    ):
        return "International"
    return None


def extract_residency_requirement(text: str) -> str | None:
    lower = text.lower()
    if "resident of" in lower or "local resident" in lower or "must reside" in lower:
        match = re.search(r"(?:resident of|must reside in|residents? of)\s+([A-Za-z\- ]{3,40})", text, flags=re.IGNORECASE)
        return match.group(1).strip(" .,") if match else "Local residency"
    return None


def looks_medical(text: str) -> bool:
    lower = normalize_text(text).lower()
    return any(re.search(rf"\b{re.escape(term.lower())}\b", lower) for term in MEDICAL_DISCOVERY_KEYWORDS)


def extract_requirements_from_text(
    text: str,
    *,
    title: str = "",
    location: str = "",
    source_url: str = "",
    application_url: str = "",
    today: date | None = None,
) -> ExtractedRequirements:
    """Extract deterministic requirements and application facts from a vacancy."""
    clean = normalize_text(text)
    scoped_clean = requirement_relevant_text(clean)
    title_clean = normalize_text(title)
    combined = "\n".join(part for part in [title_clean, location, scoped_clean] if part)
    fact_combined = "\n".join(part for part in [title_clean, location, clean] if part)
    requirements: list[Requirement] = []
    provenance: list[dict[str, str]] = []

    role_analysis = analyze_professional_role(title_clean, scoped_clean)
    requirements.append(
        Requirement(
            key="role_family_compatibility",
            label="Role family / professional qualification compatibility",
            required="Required",
            value=role_analysis,
            evidence=[role_analysis.get("evidence", "")],
            source_field="title/requirements/duties",
            criticality="essential",
        )
    )
    provenance.append({"field": "role_family_compatibility", "source": "title/requirements/duties", "quote": str(role_analysis.get("evidence", ""))})

    for key, spec in TERM_REQUIREMENTS.items():
        found = _find_first(spec["patterns"], combined)
        if found:
            _, start, end = found
            _add_requirement(
                requirements,
                provenance,
                key,
                spec["label"],
                combined,
                start,
                end,
                value=True,
                criticality=spec.get("criticality", "important"),
            )

    # Language requirements.
    for lang, patterns in LANGUAGE_PATTERNS.items():
        found = _find_first(patterns, combined)
        if found:
            _, start, end = found
            _add_requirement(
                requirements,
                provenance,
                f"language_{lang}",
                f"{lang.title()} language",
                combined,
                start,
                end,
                value=lang.title(),
                criticality="important",
            )

    # Experience years are important enough to become explicit requirements.
    years = extract_years_requirement(combined)
    for key, min_years in years.items():
        label = {
            "clinical_experience_years": "Clinical experience",
            "health_nutrition_experience_years": "Health / nutrition experience",
            "frontline_experience_years": "Frontline / field experience",
            "ngo_experience_years": "NGO / humanitarian experience years",
            "management_experience_years": "Management / supervision experience years",
            "public_health_experience_years": "Public health experience years",
            "afghanistan_health_experience_years": "Afghanistan health-sector experience years",
            "pharmacy_experience_years": "Pharmacy experience years",
            "general_experience_years": "Relevant experience years",
        }.get(key, "Experience years")
        # Find a quote close to the first occurrence of the number.
        match = re.search(rf"\b{min_years}\+?\s*(?:years?|yrs?)\b", combined, flags=re.IGNORECASE)
        start, end = (match.start(), match.end()) if match else (0, 0)
        _add_requirement(
            requirements,
            provenance,
            key,
            label,
            combined,
            start,
            end,
            value=min_years,
            criticality="essential" if "clinical" in key else "important",
        )

    gender = extract_gender_requirement(combined)
    gender_quote_text = combined
    if not gender:
        # ACBAR-style structured "Gender: Female" / "Gender Female" fields sit
        # in the quick-summary block ABOVE the Job Summary marker, outside the
        # requirement-scoped text, so they must be read from the full page text.
        gender = extract_labeled_gender_requirement(fact_combined)
        gender_quote_text = fact_combined
    if gender:
        idx = gender_quote_text.lower().find("female" if "female" in gender else "male")
        _add_requirement(
            requirements,
            provenance,
            "gender_requirement",
            "Gender requirement",
            gender_quote_text,
            max(0, idx),
            max(0, idx) + 6,
            value=gender,
            criticality="essential" if not gender.endswith("encouraged") else "important",
        )

    nationality = extract_nationality_requirement(combined)
    if nationality:
        idx_match = re.search(r"Afghan|national|international|expatriate", combined, flags=re.IGNORECASE)
        _add_requirement(
            requirements,
            provenance,
            "nationality_requirement",
            "Nationality requirement",
            combined,
            idx_match.start() if idx_match else 0,
            idx_match.end() if idx_match else 0,
            value=nationality,
            criticality="essential",
        )

    residency = extract_residency_requirement(combined)
    if residency:
        idx_match = re.search(r"resident|reside|local", combined, flags=re.IGNORECASE)
        _add_requirement(
            requirements,
            provenance,
            "residency_requirement",
            "Residency requirement",
            combined,
            idx_match.start() if idx_match else 0,
            idx_match.end() if idx_match else 0,
            value=residency,
            criticality="essential",
        )

    locations = extract_locations(combined, explicit_location=location)
    if locations:
        requirements.append(
            Requirement(
                key="location_requirement",
                label="Location / deployment",
                required="Required",
                value=locations,
                evidence=locations,
                source_field="location/description",
                criticality="important",
            )
        )
        provenance.append({"field": "location_requirement", "source": "location/description", "quote": ", ".join(locations)})

    closing_date = parse_closing_date(fact_combined, today=today)
    if closing_date:
        requirements.append(
            Requirement(
                key="closing_date",
                label="Closing date",
                required="Information",
                value=closing_date,
                evidence=[closing_date],
                source_field="description",
                criticality="info",
            )
        )
        provenance.append({"field": "closing_date", "source": "description", "quote": closing_date})

    reference_number = extract_reference_number(fact_combined)
    application_email = extract_application_email(fact_combined)
    subject = extract_application_subject(fact_combined, title=title)
    subject_required = application_subject_required(fact_combined)
    app_url = extract_application_url(fact_combined, fallback=application_url)

    facts = {
        "reference_number": reference_number,
        "application_email": application_email,
        "application_url": app_url,
        "application_url_valid": is_valid_application_url(app_url),
        "application_subject": subject,
        "application_subject_required": subject_required,
        "closing_date": closing_date,
        "locations": locations,
        "gender_requirement": gender,
        "nationality_requirement": nationality,
        "residency_requirement": residency,
        "source_url": source_url,
        "role_analysis": role_analysis,
        "is_medical": role_analysis.get("classification") not in {"not_medical_or_public_health"},
    }
    for field_name, value in facts.items():
        if value:
            provenance.append({"field": field_name, "source": "description/job", "quote": str(value)})

    return ExtractedRequirements(requirements=requirements, facts=facts, provenance=provenance)


def extract_requirements_from_job(job: Any, today: date | None = None) -> ExtractedRequirements:
    """Convenience wrapper for Job dataclass or DB-row dictionaries."""
    get = job.get if isinstance(job, dict) else lambda key, default=None: getattr(job, key, default)
    metadata = _metadata_from_job(job)
    source = canonical_source_fields(job)
    # Pass only a direct application/form URL into URL extraction. The official
    # vacancy page is preserved separately as vacancy_url/application_method and
    # does not by itself satisfy READY_TO_APPLY.
    direct_application_url = source.get("application_url") if source.get("application_method") == "WEB" else ""
    extracted = extract_requirements_from_text(
        get("description", "") or "",
        title=get("title", "") or "",
        location=get("location", "") or "",
        source_url=source.get("source_url") or metadata.get("source_url") or "",
        application_url=direct_application_url or "",
        today=today,
    )
    # A source adapter may have parsed a structured closing-date card even
    # when the date is not repeated in the description text. Preserve that
    # source-provided fact; otherwise an absent deadline is not evidence that a
    # vacancy remains open and becomes a critical manual-verification item.
    metadata_closing = str(metadata.get("closing_date") or "").strip()
    if not extracted.facts.get("closing_date") and metadata_closing:
        try:
            date.fromisoformat(metadata_closing[:10])
        except ValueError:
            metadata_closing = ""
        if metadata_closing:
            extracted.facts["closing_date"] = metadata_closing[:10]
            extracted.requirements.append(
                Requirement(
                    key="closing_date",
                    label="Closing date",
                    required="Information",
                    value=metadata_closing[:10],
                    evidence=[metadata_closing[:10]],
                    source_field="source metadata",
                    criticality="info",
                )
            )
            extracted.provenance.append({"field": "closing_date", "source": "source metadata", "quote": metadata_closing[:10]})
    if not extracted.facts.get("closing_date"):
        extracted.requirements.append(
            Requirement(
                key="closing_date",
                label="Closing date",
                required="Required",
                value=None,
                evidence=[],
                source_field="description/source metadata",
                criticality="essential",
            )
        )
        extracted.provenance.append({"field": "closing_date", "source": "description/source metadata", "quote": "No reliable closing date found."})
    source_requirement = Requirement(
        key="source_validity",
        label="Valid source and official vacancy route",
        required="Required",
        value=source,
        evidence=[
            f"Source: {source.get('source_name') or 'UNKNOWN'}",
            f"Source URL: {source.get('source_url') or 'missing'}",
            f"Vacancy URL: {source.get('vacancy_url') or 'missing'}",
            f"Application method: {source.get('application_method') or 'none'}",
        ],
        source_field="source/application metadata",
        criticality="essential",
    )
    extracted.requirements.insert(0, source_requirement)
    extracted.provenance.insert(0, {"field": "source_validity", "source": "source/application metadata", "quote": "; ".join(source_requirement.evidence)})
    extracted.facts.update(
        {
            "source_name": source.get("source_name"),
            "source_url": source.get("source_url"),
            "vacancy_url": source.get("vacancy_url"),
            "apply_url": source.get("apply_url"),
            "apply_email": source.get("apply_email"),
            "application_method": source.get("application_method"),
            "source_valid": source.get("source_valid"),
            "source_problems": source.get("problems") or [],
            "official_route": source.get("apply_url") or source.get("vacancy_url") or source.get("source_url"),
        }
    )
    if source.get("apply_email") and not extracted.facts.get("application_email"):
        extracted.facts["application_email"] = source["apply_email"]
    if source.get("application_url") and source.get("application_method") == "WEB" and not extracted.facts.get("application_url"):
        extracted.facts["application_url"] = source["application_url"]
        extracted.facts["application_url_valid"] = is_valid_application_url(source["application_url"])
    return extracted
