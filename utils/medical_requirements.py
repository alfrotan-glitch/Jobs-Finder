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
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Iterable
from urllib.parse import urlparse


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
        "patterns": [
            r"\bexit\s+exam(?:ination)?\b",
            r"\bmedical\s+exit\s+exam(?:ination)?\b",
            r"\bmedical\s+council\s+exam(?:ination)?\b",
            r"ایگزیت\s*امتحان",
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
    text = re.sub(r"<\s*br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</\s*(p|li|div|h\d|tr)\s*>", "\n", text, flags=re.I)
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
        match = re.search(pattern, text, flags=re.I)
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


def parse_closing_date(text: str, today: date | None = None) -> str | None:
    """Extract the first likely closing/deadline date and return ISO date."""
    if not text:
        return None
    today = today or date.today()
    label = r"(?:closing\s+date|deadline|apply\s+by|valid\s+until|last\s+date|submission\s+deadline)"
    windows = []
    for match in re.finditer(label, text, flags=re.I):
        windows.append(text[match.start(): match.start() + 180])
    if not windows:
        # Some ACBAR-style cards show "Close date: ..." or just "Close: ...".
        for match in re.finditer(r"(?:close\s+date|close|expires?)", text, flags=re.I):
            windows.append(text[match.start(): match.start() + 160])
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
        match = re.search(pattern, search_space, flags=re.I)
        if not match:
            continue
        parts = match.groupdict()
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

    return re.sub(r"\b(" + "|".join(NUMBER_WORDS) + r")\s+(?:years?|yrs?)\b", repl, text, flags=re.I)


def _minimum_years_from_match(match: re.Match) -> int:
    groups = match.groupdict()
    if groups.get("low"):
        return int(groups["low"])
    return int(groups.get("years") or 0)


def _experience_scope(context: str) -> str:
    context = (context or "").lower()
    if any(term in context for term in ["pharmacy", "pharmacist", "pharmaceutical", "pharmacy technician"]):
        return "pharmacy_experience_years"
    if any(term in context for term in ["management", "supervis", "lead", "coordinat", "mentor", "capacity", "مدیریت", "نظارت", "هماهنگ"]):
        return "management_experience_years"
    if any(term in context for term in ["clinical", "medical", "hospital", "clinic", "phc", "primary health", "patient", "curative", "doctor", "gp", "صحی", "کلینیک"]):
        return "clinical_experience_years"
    if any(term in context for term in ["ngo", "ingo", "humanitarian", "emergency", "donor", "red cross", "red crescent", "un agencies", "بشر دوستانه", "موسسات غیر دولتی", "هلال احمر"]):
        return "ngo_experience_years"
    if any(term in context for term in ["public health", "health program", "health sector", "health systems", "moph", "hmis", "صحت عامه", "برنامه های صحی"]):
        return "afghanistan_health_experience_years" if ("afghan" in context or "afghanistan" in context) else "public_health_experience_years"
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
        for match in re.finditer(pattern, text, flags=re.I):
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
                flags=re.I,
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
            nums = [_minimum_years_from_match(m) for m in re.finditer(rf"{range_value}\s*{year_word}", sentence, flags=re.I)]
            nums = [n for n in nums if n > 0]
            if len(nums) >= 2:
                pharmacy_alternative_min = min(nums) if pharmacy_alternative_min is None else min(pharmacy_alternative_min, min(nums))

    # Dari/Persian common order: "تجربه کاری حد اقل 5 سال ... مدیریت برنامه های صحی".
    persian_pattern = rf"(?P<context>.{{0,80}}?(?:تجربه|کاری).{{0,80}}?)(?:حد\s*اقل\s+)?{range_value}\s*{year_word}(?P<tail>.{{0,120}})"
    for match in re.finditer(persian_pattern, text, flags=re.I):
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
    return bool(re.fullmatch(r"[A-Z0-9][A-Z0-9/_\-.]{2,}", candidate, flags=re.I))


def extract_reference_number(text: str) -> str | None:
    explicit_patterns = [
        r"\b(?:Vacancy|Reference|Ref(?:erence)?|VN|Job\s*ID|Requisition|Announcement)\b\s*(?:No\.?|Number|#|ID)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/_\-.]{2,})",
    ]
    for pattern in explicit_patterns:
        match = re.search(pattern, text, flags=re.I)
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
    match = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text, flags=re.I)
    return match.group(0) if match else None


def extract_urls(text: str) -> list[str]:
    urls = re.findall(r"https?://[^\s<>\"')\],;]+", text or "", flags=re.I)
    cleaned: list[str] = []
    for url in urls:
        value = url.rstrip(".,;:!?)]")
        if value not in cleaned:
            cleaned.append(value)
    return cleaned


def extract_application_url(text: str, fallback: str = "") -> str | None:
    urls = extract_urls(text)
    strong_terms = [
        "apply", "application", "applicationform", "forms.gle", "docs.google.com/forms",
        "form", "greenhouse", "lever", "workday", "smartrecruiters",
    ]
    weak_terms = ["career", "job", "vacanc", "document"]
    for url in urls:
        lower = url.lower()
        if any(term in lower for term in strong_terms):
            return url
    for url in urls:
        lower = url.lower()
        if any(term in lower for term in weak_terms):
            return url
    if fallback:
        return fallback
    return urls[0] if urls else None


def is_valid_application_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def extract_application_subject(text: str, title: str = "") -> str | None:
    if title and (
        re.search(r"\b(?:mention|write|include|indicat(?:e|ing))\b[^\n\r]{0,120}\b(?:job\s+title|position(?:\s+title)?|title)\b[^\n\r]{0,120}\bsubject\b", text or "", flags=re.I)
        or re.search(r"\bmention\b[^\n\r]{0,80}\bposition\b[^\n\r]{0,120}\bsubject\b", text or "", flags=re.I)
    ):
        if not re.search(r"\b(?:(?:vacancy|reference|ref\.?|announcement)\s*(?:number|no\.?|#)?|position\s+code|job\s+code)\b", text or "", flags=re.I):
            return title
    patterns = [
        r"(?:email\s+)?subject(?:\s+line)?\s*(?:must\s+be|should\s+be|as)?\s*[:\-]\s*[\"']?([^\n\r\"']{3,120})",
        r"write\s+[\"']([^\"']{3,120})[\"']\s+in\s+the\s+subject",
        r"mention\s+[\"']([^\"']{3,120})[\"']\s+in\s+the\s+subject",
        r"subject[^\n\r]{0,80}?(?:like|as)\s*\(?\s*\*{0,2}([A-Z0-9][A-Z0-9/_\-.]{2,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            subject = match.group(1).strip().strip(" .;:")
            # Avoid consuming the next instruction sentence.
            subject = re.split(r"\s{2,}|\.\s+", subject)[0].strip()
            if subject.lower() in {"not", "required", "mandatory", "is mandatory", "not exposed", "not provided"}:
                return None
            return subject
    return None


def application_subject_required(text: str) -> bool:
    text = text or ""
    if re.search(r"\bsubject\b", text, flags=re.I):
        return True
    # Common Dari/Persian ACBAR wording: applicants must write the job title
    # and position code in the email. If no exact code is present, readiness
    # must remain NEEDS_VERIFICATION instead of inventing a subject/reference.
    return bool(
        re.search(r"عنوان.{0,80}(?:کد|كود|کُد|كد).{0,80}بست.{0,120}(?:ایمیل|ايميل).{0,80}الزام", text, flags=re.I)
        or re.search(r"(?:ایمیل|ايميل).{0,120}عنوان.{0,80}(?:کد|كود|کُد|كد).{0,80}بست", text, flags=re.I)
    )


def extract_locations(text: str, explicit_location: str = "") -> list[str]:
    found: list[str] = []
    combined = f"{explicit_location}\n{text}"
    combined = re.sub(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", " ", combined, flags=re.I)
    combined = re.sub(r"https?://\S+", " ", combined, flags=re.I)
    for province in AFGHAN_PROVINCES:
        if re.search(rf"\b{re.escape(province)}\b", combined, flags=re.I):
            canonical = "Sar-e-Pul" if province.lower().replace(" ", "-") in {"sar-e-pul", "sar-e pul"} else province
            if canonical not in found:
                found.append(canonical)
    if re.search(r"\bKabul\b", combined, flags=re.I) and "Kabul" not in found:
        found.append("Kabul")
    if any(re.search(p, combined, flags=re.I) for p in DISTRICT_PATTERNS):
        if "Field / district deployment" not in found:
            found.append("Field / district deployment")
    return found


def extract_gender_requirement(text: str) -> str | None:
    lower = text.lower()
    first_line = (text or "").splitlines()[0].lower() if text else ""
    if re.search(r"\bmale\s*/\s*female\b|\bfemale\s*/\s*male\b|\bmale\s+and\s+female\b", first_line):
        return None
    if re.search(r"\bfemale\b", first_line):
        return "female"
    if re.search(r"\bmale\b", first_line):
        return "male"
    if re.search(r"\bmale\s*/\s*female\b|\bfemale\s*/\s*male\b|\bmale\s+and\s+female\b", lower):
        return None
    if (
        "female candidates are strongly encouraged" in lower
        or "women are strongly encouraged" in lower
        or re.search(r"\bfemale\s+candidate\s+(?:is\s+)?point\s+plus\b", lower)
        or re.search(r"\bfemale\s+(?:candidate|candidates)\s+(?:preferred|encouraged)\b", lower)
    ):
        return "female_encouraged"
    if re.search(r"\bgender\s*[:\-]\s*female\b", lower):
        return "female"
    if re.search(r"\bgender\s*[:\-]\s*male\b", lower):
        return "male"
    if re.search(r"\b(?:must\s+be|shortlist(?:ed)?\s+candidates?\s+must\s+be|only)\s+female\b", lower):
        return "female"
    if re.search(r"\bfemale\s+(?:only|required|applicants|candidate|candidates|(?:medical\s+)?doctor|md|staff)\b", lower) or re.search(r"\bonly\s+female\b", lower):
        return "female"
    if re.search(r"\b(?:must\s+be|only)\s+male\b", lower):
        return "male"
    if re.search(r"\bmale\s+(?:only|required|applicants|candidate|candidates|(?:medical\s+)?doctor|md|staff)\b", lower) or re.search(r"\bonly\s+male\b", lower):
        return "male"
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
        match = re.search(r"(?:resident of|must reside in|residents? of)\s+([A-Za-z\- ]{3,40})", text, flags=re.I)
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
            "ngo_experience_years": "NGO / humanitarian experience years",
            "management_experience_years": "Management / supervision experience years",
            "public_health_experience_years": "Public health experience years",
            "afghanistan_health_experience_years": "Afghanistan health-sector experience years",
            "pharmacy_experience_years": "Pharmacy experience years",
            "general_experience_years": "Relevant experience years",
        }.get(key, "Experience years")
        # Find a quote close to the first occurrence of the number.
        match = re.search(rf"\b{min_years}\+?\s*(?:years?|yrs?)\b", combined, flags=re.I)
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
    if gender:
        idx = combined.lower().find("female" if "female" in gender else "male")
        _add_requirement(
            requirements,
            provenance,
            "gender_requirement",
            "Gender requirement",
            combined,
            max(0, idx),
            max(0, idx) + 6,
            value=gender,
            criticality="essential" if not gender.endswith("encouraged") else "important",
        )

    nationality = extract_nationality_requirement(combined)
    if nationality:
        idx = re.search(r"Afghan|national|international|expatriate", combined, flags=re.I)
        _add_requirement(
            requirements,
            provenance,
            "nationality_requirement",
            "Nationality requirement",
            combined,
            idx.start() if idx else 0,
            idx.end() if idx else 0,
            value=nationality,
            criticality="essential",
        )

    residency = extract_residency_requirement(combined)
    if residency:
        idx = re.search(r"resident|reside|local", combined, flags=re.I)
        _add_requirement(
            requirements,
            provenance,
            "residency_requirement",
            "Residency requirement",
            combined,
            idx.start() if idx else 0,
            idx.end() if idx else 0,
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
        "is_medical": looks_medical(f"{title}\n{text}"),
    }
    for field_name, value in facts.items():
        if value:
            provenance.append({"field": field_name, "source": "description/job", "quote": str(value)})

    return ExtractedRequirements(requirements=requirements, facts=facts, provenance=provenance)


def extract_requirements_from_job(job: Any, today: date | None = None) -> ExtractedRequirements:
    """Convenience wrapper for Job dataclass or DB-row dictionaries."""
    get = job.get if isinstance(job, dict) else lambda key, default=None: getattr(job, key, default)
    metadata = get("metadata", {}) or {}
    if isinstance(metadata, str):
        try:
            import json

            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    source_url = metadata.get("source_url") or get("url", "")
    return extract_requirements_from_text(
        get("description", "") or "",
        title=get("title", "") or "",
        location=get("location", "") or "",
        source_url=source_url,
        application_url=get("apply_url", "") or get("url", ""),
        today=today,
    )
