"""Global professional document design system for Jobs-Finder packages.

This module is deliberately presentation-focused: it receives already-tailored,
verified document text from ``utils.documents`` and renders it with a reusable
medical/NGO visual identity.  It must not add facts.  The TXT artifact remains
ATS/plain-text canonical; the DOCX and PDF artifacts are designed views of that
same content.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DESIGN_SYSTEM_VERSION = "jobs-finder-editorial-medical-v1"


def render_professional_document_artifacts(
    text: str,
    base_path: str | Path,
    *,
    document_type: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Write TXT, DOCX and PDF using the global Jobs-Finder design system.

    ``document_type`` is ``"cv"`` or ``"cover_letter"``.  Unknown types fall
    back to the CV-style text body because the caller should always receive all
    artifacts.  The renderer never changes the factual source text; all visual
    structures are derived from the text and optional package/job metadata.
    """

    base = Path(base_path)
    base.parent.mkdir(parents=True, exist_ok=True)
    txt = base.with_suffix(".txt")
    docx = base.with_suffix(".docx")
    pdf = base.with_suffix(".pdf")
    txt.write_text(text or "", encoding="utf-8")
    metadata = metadata or {}
    if document_type == "cover_letter":
        model = parse_cover_letter_text(text or "", metadata)
        render_cover_letter_pdf(model, pdf)
        render_cover_letter_docx(model, docx)
    else:
        model = parse_cv_text(text or "", metadata)
        render_cv_pdf(model, pdf)
        render_cv_docx(model, docx)
    return {"txt": str(txt), "docx": str(docx), "pdf": str(pdf)}


# ---------------------------------------------------------------------------
# Parsing tailored text into presentation models
# ---------------------------------------------------------------------------


def _value_after(line: str, prefix: str) -> str:
    return line.split(":", 1)[1].strip() if line.lower().startswith(prefix.lower() + ":") and ":" in line else ""


def _section_map(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.isupper() and len(stripped) > 2 and not stripped.startswith("-"):
            current = stripped
            sections.setdefault(current, [])
            continue
        if current:
            sections.setdefault(current, []).append(stripped)
    return sections


def _clean_bullet(line: str) -> str:
    return str(line or "").strip().lstrip("-•* ").strip()


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _split_languages(value: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    text = value.strip().lstrip("- ")
    for part in re.split(r"\s*[,|;]\s*", text):
        part = part.strip()
        if not part:
            continue
        if "—" in part:
            name, level = [p.strip() for p in part.split("—", 1)]
        elif "-" in part:
            name, level = [p.strip() for p in part.split("-", 1)]
        else:
            name, level = part, ""
        result.append((name, level))
    return result


def _parse_experience_header(line: str) -> dict[str, str]:
    text = line.strip()
    dates = ""
    date_match = re.search(r"\(([^()]*\d{4}[^()]*)\)\s*$", text)
    if date_match:
        dates = date_match.group(1).strip()
        text = text[: date_match.start()].strip()
    parts = [p.strip() for p in text.split("|")]
    role = parts[0] if parts else ""
    org = parts[1] if len(parts) > 1 else ""
    loc = parts[2] if len(parts) > 2 else ""
    if len(parts) == 2 and any(token in parts[0].lower() for token in ["ngo", "ministry", "organization", "institute"]):
        org, role = parts[0], parts[1]
    return {"role": role, "org": org, "loc": loc, "dates": dates}


def parse_cv_text(text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = metadata or {}
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    nonempty = [ln.strip() for ln in lines if ln.strip()]
    name = nonempty[0] if nonempty else "Applicant"
    email = phone = location = ""
    target_role = target_org = target_location = ""
    for line in nonempty[:20]:
        email = _value_after(line, "Email") or email
        phone = _value_after(line, "Phone") or phone
        location = _value_after(line, "Location") or location
        target_role = _value_after(line, "TARGET ROLE") or target_role
        target_org = _value_after(line, "TARGET ORGANIZATION") or target_org
        target_location = _value_after(line, "VACANCY LOCATION") or target_location
    job = metadata.get("job") or {}
    package = metadata.get("package") or {}
    target_role = target_role or str(job.get("title") or package.get("job_title") or "Target Role")
    target_org = target_org or str(job.get("company") or package.get("company") or "Target Organization")
    target_location = target_location or str(job.get("location") or "")
    job_metadata = _coerce_dict(job.get("metadata"))
    reference = str(job_metadata.get("reference_number") or package.get("vacancy_reference") or "").strip()
    sections = _section_map(lines)
    profile = " ".join(sections.get("PROFESSIONAL SUMMARY", []) or sections.get("PROFESSIONAL PROFILE", []))
    strengths = [_clean_bullet(x) for x in sections.get("CORE COMPETENCIES", [])]
    expanded: list[str] = []
    for item in strengths:
        expanded.extend([p.strip() for p in item.split(",") if p.strip()])
    strengths = expanded or [_clean_bullet(x) for x in sections.get("VACANCY-FIT HIGHLIGHTS", [])]
    strengths = _unique(strengths)[:8]
    exp_lines = sections.get("PROFESSIONAL EXPERIENCE", [])
    experience: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in exp_lines:
        if line.startswith("-") and current:
            current.setdefault("bullets", []).append(_clean_bullet(line))
        elif not line.startswith("-"):
            if current:
                experience.append(current)
            current = _parse_experience_header(line)
            current["bullets"] = []
    if current:
        experience.append(current)
    education = [_clean_bullet(x) for x in sections.get("EDUCATION", [])]
    registration = [_clean_bullet(x) for x in sections.get("LICENSE / REGISTRATION", [])]
    exit_exam = [_clean_bullet(x) for x in sections.get("MEDICAL EXIT EXAM", [])]
    certs = [_clean_bullet(x) for x in sections.get("CERTIFICATIONS & TRAINING", [])]
    languages_raw = [_clean_bullet(x) for x in sections.get("LANGUAGES", [])]
    languages = _split_languages(languages_raw[0]) if languages_raw else []
    headline = "Medical Doctor | Health & Nutrition Program Coordination"
    return {
        "design_system": DESIGN_SYSTEM_VERSION,
        "name": name,
        "headline": headline,
        "email": email,
        "phone": phone,
        "location": location,
        "target_role": target_role,
        "target_org": target_org,
        "target_location": target_location,
        "reference": reference,
        "profile": profile,
        "strengths": strengths,
        "experience": experience,
        "education": education,
        "registration": registration,
        "exit_exam": exit_exam,
        "certifications": certs,
        "languages": languages,
        "raw_text": text or "",
    }


def parse_cover_letter_text(text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = metadata or {}
    job = metadata.get("job") or {}
    package = metadata.get("package") or {}
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    subject = ""
    body_lines: list[str] = []
    signature = ""
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("subject:"):
            subject = stripped.split(":", 1)[1].strip()
            continue
        if stripped:
            body_lines.append(stripped)
    if body_lines and body_lines[-1].lower() not in {"sincerely,", "regards,"}:
        signature = body_lines[-1]
    name = _full_name_from_package(package) or signature or "Applicant"
    contact = _contact_from_package(package)
    target_role = str(job.get("title") or package.get("job_title") or "Target Role")
    target_org = str(job.get("company") or package.get("company") or "Target Organization")
    target_location = str(job.get("location") or "")
    job_metadata = _coerce_dict(job.get("metadata"))
    reference = str(job_metadata.get("reference_number") or package.get("vacancy_reference") or "").strip()
    return {
        "design_system": DESIGN_SYSTEM_VERSION,
        "name": name,
        "headline": "Medical Doctor | Health & Nutrition Program Coordination",
        "contact": contact,
        "subject": subject or target_role,
        "target_role": target_role,
        "target_org": target_org,
        "target_location": target_location,
        "reference": reference,
        "body_lines": body_lines,
        "raw_text": text or "",
    }


def _full_name_from_package(package: dict[str, Any]) -> str:
    for item in package.get("form_fields_checklist", []) or []:
        if str(item).startswith("Full name:"):
            return str(item).split(":", 1)[1].strip()
    return ""


def _contact_from_package(package: dict[str, Any]) -> dict[str, str]:
    contact = {"email": "", "phone": "", "location": ""}
    for item in package.get("form_fields_checklist", []) or []:
        text = str(item)
        for key, label in [("email", "Email"), ("phone", "Phone"), ("location", "Current location")]:
            if text.startswith(label + ":"):
                contact[key] = text.split(":", 1)[1].strip()
    return contact


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        norm = re.sub(r"\W+", " ", item.lower()).strip()
        if item and norm not in seen:
            seen.add(norm)
            out.append(item)
    return out


# ---------------------------------------------------------------------------
# PDF rendering primitives
# ---------------------------------------------------------------------------


def _register_fonts() -> tuple[str, str, str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    fonts = {
        "JFSerif": "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "JFSerifBold": "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "JFSans": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "JFSansBold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    }
    for name, path in fonts.items():
        try:
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, path))
        except Exception:  # pragma: no cover - font fallback safety
            pass
    return "JFSerif", "JFSerifBold", "JFSans", "JFSansBold"


class Theme:
    ink = "#172A35"
    deep = "#0C3442"
    teal = "#157C78"
    gold = "#A88449"
    muted = "#66737A"
    soft = "#F6F8F7"
    rule = "#D7E0E2"


def _c(hex_value: str):
    from reportlab.lib import colors

    return colors.HexColor(hex_value)


def _string_width(text: str, font: str, size: float) -> float:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    return stringWidth(str(text), font, size)


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else current + " " + word
        if _string_width(trial, font, size) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_wrapped(cnv, text: str, x: float, y: float, width: float, *, font: str, size: float, leading: float, color: str = Theme.ink) -> float:
    cnv.setFont(font, size)
    cnv.setFillColor(_c(color))
    for line in _wrap(text, font, size, width):
        cnv.drawString(x, y, line)
        y -= leading
    return y


def _draw_section(cnv, title: str, x: float, y: float, width: float, fonts: tuple[str, str, str, str]) -> float:
    _, _, _, sans_bold = fonts
    cnv.setFont(sans_bold, 10.2)
    cnv.setFillColor(_c(Theme.deep))
    cnv.drawString(x, y, title.upper())
    cnv.setStrokeColor(_c(Theme.rule))
    cnv.setLineWidth(0.55)
    cnv.line(x, y - 5, x + width, y - 5)
    cnv.setStrokeColor(_c(Theme.gold))
    cnv.setLineWidth(1.35)
    cnv.line(x, y - 5, x + 38, y - 5)
    return y - 20


def _draw_label(cnv, text: str, x: float, y: float, fonts: tuple[str, str, str, str], color: str = Theme.teal) -> float:
    _, _, _, sans_bold = fonts
    cnv.setFont(sans_bold, 6.5)
    cnv.setFillColor(_c(color))
    cnv.drawString(x, y, text.upper())
    return y - 9


def _draw_bullet(cnv, text: str, x: float, y: float, width: float, fonts: tuple[str, str, str, str], *, size: float = 7.45, leading: float = 9.4) -> float:
    _, _, sans, _ = fonts
    cnv.setFillColor(_c(Theme.teal))
    cnv.circle(x, y + 3, 1.35, stroke=0, fill=1)
    return _draw_wrapped(cnv, text, x + 8, y, width - 8, font=sans, size=size, leading=leading)


def _draw_rule(cnv, x: float, y: float, width: float) -> None:
    cnv.setStrokeColor(_c(Theme.rule))
    cnv.setLineWidth(0.45)
    cnv.line(x, y, x + width, y)


def _draw_footer(cnv, page: int, fonts: tuple[str, str, str, str], role: str) -> None:
    _, _, sans, _ = fonts
    from reportlab.lib.pagesizes import A4

    w, _ = A4
    cnv.setStrokeColor(_c(Theme.rule))
    cnv.line(42, 38, w - 42, 38)
    cnv.setFont(sans, 6.6)
    cnv.setFillColor(_c(Theme.muted))
    cnv.drawString(42, 25, "Jobs-Finder · Review copy")
    cnv.drawRightString(w - 42, 25, f"Page {page} / 2")


def _draw_timeline_entry(cnv, item: dict[str, Any], x_date: float, x_line: float, x_text: float, y: float, width: float, fonts: tuple[str, str, str, str]) -> float:
    _, serif_bold, sans, sans_bold = fonts
    # Keep dates within the main text measure rather than in the left rail;
    # that preserves the editorial timeline feel without colliding with the
    # credentials/sidebar content on dense vacancy-specific CVs.
    cnv.setFillColor(_c("#FFFFFF"))
    cnv.setStrokeColor(_c(Theme.teal))
    cnv.circle(x_line, y - 1, 3.1, stroke=1, fill=1)
    cnv.setStrokeColor(_c(Theme.rule))
    cnv.line(x_line, y - 9, x_line, y - 78)
    cnv.setFont(sans_bold, 7.3)
    cnv.setFillColor(_c(Theme.muted))
    cnv.drawString(x_text, y, (item.get("org") or "")[:52])
    if item.get("dates"):
        cnv.setFillColor(_c(Theme.teal))
        cnv.drawRightString(x_text + width, y, item.get("dates") or "")
    y -= 12
    cnv.setFont(serif_bold, 10.5)
    cnv.setFillColor(_c(Theme.deep))
    cnv.drawString(x_text, y, item.get("role") or "")
    y -= 11
    cnv.setFont(sans, 7.3)
    cnv.setFillColor(_c(Theme.muted))
    cnv.drawString(x_text, y, item.get("loc") or "")
    y -= 13
    for bullet in item.get("bullets", [])[:2]:
        y = _draw_bullet(cnv, bullet, x_text + 2, y, width - 2, fonts, size=7.45, leading=9.2)
        y -= 2
    return y - 14


def _draw_timeline_entry_inside(cnv, item: dict[str, Any], x: float, y: float, width: float, fonts: tuple[str, str, str, str]) -> float:
    _, serif_bold, sans, sans_bold = fonts
    cnv.setFillColor(_c(Theme.teal))
    cnv.circle(x + 2.8, y - 1, 3, stroke=0, fill=1)
    cnv.setStrokeColor(_c(Theme.rule))
    cnv.line(x + 2.8, y - 10, x + 2.8, y - 70)
    cnv.setFont(sans_bold, 7.15)
    cnv.setFillColor(_c(Theme.muted))
    cnv.drawString(x + 16, y, item.get("org") or "")
    cnv.setFont(sans_bold, 7.0)
    cnv.setFillColor(_c(Theme.teal))
    cnv.drawRightString(x + width, y, item.get("dates") or "")
    y -= 14
    cnv.setFont(serif_bold, 10.5)
    cnv.setFillColor(_c(Theme.deep))
    cnv.drawString(x + 16, y, item.get("role") or "")
    y -= 11
    cnv.setFont(sans, 7.3)
    cnv.setFillColor(_c(Theme.muted))
    cnv.drawString(x + 16, y, item.get("loc") or "")
    y -= 13
    for bullet in item.get("bullets", [])[:2]:
        y = _draw_bullet(cnv, bullet, x + 18, y, width - 22, fonts, size=7.45, leading=9.2)
        y -= 2
    return y - 13


# ---------------------------------------------------------------------------
# CV PDF / DOCX renderers
# ---------------------------------------------------------------------------


def render_cv_pdf(model: dict[str, Any], path: str | Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    fonts = _register_fonts()
    serif, serif_bold, sans, sans_bold = fonts
    width, height = A4
    cnv = canvas.Canvas(str(path), pagesize=A4)
    cnv.setTitle(f"{model.get('name')} — {model.get('target_role')} CV")
    cnv.setAuthor("Jobs-Finder")

    # Page 1 header.
    cnv.setFillColor(_c("#FFFFFF"))
    cnv.rect(0, 0, width, height, stroke=0, fill=1)
    cnv.setFillColor(_c(Theme.deep))
    cnv.rect(0, height - 11, width, 11, stroke=0, fill=1)
    cnv.setStrokeColor(_c(Theme.gold))
    cnv.setLineWidth(1.2)
    cnv.line(42, height - 38, width - 42, height - 38)
    cnv.setFont(sans_bold, 6.8)
    cnv.setFillColor(_c(Theme.teal))
    ref = f"{model.get('reference')} · " if model.get("reference") else ""
    cnv.drawRightString(width - 42, height - 27, f"{ref}{model.get('target_role', 'APPLICATION')}".upper())
    cnv.setFont(serif_bold, 31)
    cnv.setFillColor(_c(Theme.deep))
    cnv.drawString(42, height - 76, model.get("name") or "Applicant")
    cnv.setFont(sans, 10.2)
    cnv.setFillColor(_c(Theme.teal))
    cnv.drawString(44, height - 96, model.get("headline") or "Medical Professional")
    contact_line = " | ".join([x for x in [model.get("location"), model.get("phone"), model.get("email")] if x])
    cnv.setFont(sans, 7.8)
    cnv.setFillColor(_c(Theme.muted))
    cnv.drawString(44, height - 113, contact_line)
    cnv.setStrokeColor(_c(Theme.rule))
    cnv.line(42, height - 134, width - 42, height - 134)
    cnv.setFont(sans_bold, 7.1)
    cnv.setFillColor(_c(Theme.gold))
    cnv.drawString(44, height - 150, "TARGET")
    target = f"{model.get('target_role')} — {model.get('target_org')}"
    if model.get("target_location"):
        target += f", {model.get('target_location')}"
    cnv.setFont(sans_bold, 8.0)
    cnv.setFillColor(_c(Theme.deep))
    cnv.drawString(92, height - 150, target[:125])

    left_x, left_w = 50, 150
    main_x, main_w = 236, 316
    start_y = height - 185
    _draw_cv_left_rail(cnv, model, left_x, start_y, left_w, fonts, page=1)
    y = _draw_section(cnv, "Professional Profile", main_x, start_y, main_w, fonts)
    cnv.setStrokeColor(_c(Theme.gold))
    cnv.setLineWidth(1.2)
    cnv.line(main_x, y + 2, main_x, y - 56)
    y = _draw_wrapped(cnv, model.get("profile") or "", main_x + 15, y, main_w - 15, font=sans, size=8.75, leading=11.8)
    y -= 12
    y = _draw_section(cnv, "Professional Experience", main_x, y, main_w, fonts)
    for item in (model.get("experience") or [])[:3]:
        y = _draw_timeline_entry(cnv, item, main_x - 78, main_x - 12, main_x, y, main_w, fonts)
    cnv.setStrokeColor(_c(Theme.gold))
    cnv.line(main_x, 90, main_x + 54, 90)
    cnv.setFont(sans_bold, 6.8)
    cnv.setFillColor(_c(Theme.gold))
    cnv.drawString(main_x, 76, "APPLICATION FOCUS")
    _draw_wrapped(cnv, f"Tailored to {model.get('target_role')} using verified clinical, HMIS, coordination, and role-relevant evidence only.", main_x + 93, 76, main_w - 93, font=sans, size=7.2, leading=9.2, color=Theme.muted)
    _draw_footer(cnv, 1, fonts, model.get("target_role") or "")
    cnv.showPage()

    # Page 2.
    cnv.setFillColor(_c("#FFFFFF"))
    cnv.rect(0, 0, width, height, stroke=0, fill=1)
    cnv.setFillColor(_c(Theme.deep))
    cnv.rect(0, height - 9, width, 9, stroke=0, fill=1)
    cnv.setStrokeColor(_c(Theme.rule))
    cnv.line(42, height - 44, width - 42, height - 44)
    cnv.setFont(sans_bold, 9.3)
    cnv.setFillColor(_c(Theme.deep))
    cnv.drawString(42, height - 31, model.get("name") or "Applicant")
    cnv.setFont(sans, 7.4)
    cnv.setFillColor(_c(Theme.muted))
    cnv.drawRightString(width - 42, height - 31, f"{model.get('target_role')} — {model.get('reference') or model.get('target_org')}")
    left_x, left_w = 50, 148
    main_x, main_w = 236, 316
    top = height - 78
    _draw_cv_left_rail(cnv, model, left_x, top, left_w, fonts, page=2)
    y = _draw_section(cnv, "Professional Experience Continued", main_x, top, main_w, fonts)
    for item in (model.get("experience") or [])[3:]:
        y = _draw_timeline_entry_inside(cnv, item, main_x, y, main_w, fonts)
    y -= 5
    y = _draw_cv_credentials(cnv, model, main_x, y, main_w, fonts)
    cnv.setStrokeColor(_c(Theme.gold))
    cnv.line(main_x, 86, main_x + 50, 86)
    cnv.setFont(sans_bold, 6.8)
    cnv.setFillColor(_c(Theme.gold))
    cnv.drawString(main_x, 72, "DOCUMENT SCOPE")
    _draw_wrapped(cnv, f"Prepared for {model.get('reference') or model.get('target_role')} using verified profile evidence only.", main_x + 90, 72, main_w - 90, font=sans, size=7.2, leading=9.2, color=Theme.muted)
    _draw_footer(cnv, 2, fonts, model.get("target_role") or "")
    cnv.save()


def _draw_cv_left_rail(cnv, model: dict[str, Any], x: float, y_top: float, width: float, fonts: tuple[str, str, str, str], *, page: int) -> None:
    serif, serif_bold, sans, sans_bold = fonts
    from reportlab.lib.pagesizes import A4

    _, height = A4
    cnv.setFillColor(_c(Theme.soft))
    cnv.rect(x - 10, 62, width + 16, y_top - 62, stroke=0, fill=1)
    cnv.setFillColor(_c(Theme.teal))
    cnv.rect(x - 10, 62, 2.2, y_top - 62, stroke=0, fill=1)
    if page == 1:
        y = _draw_label(cnv, "Clinical & Professional Strengths", x, y_top - 2, fonts)
        _draw_rule(cnv, x, y + 2, width)
        y -= 12
        for strength in (model.get("strengths") or [])[:8]:
            cnv.setFont(sans, 7.35)
            cnv.setFillColor(_c(Theme.ink))
            cnv.drawString(x, y, strength[:38])
            _draw_rule(cnv, x, y - 5.2, width)
            y -= 15.5
    else:
        cnv.setFont(serif_bold, 13.5)
        cnv.setFillColor(_c(Theme.deep))
        cnv.drawString(x, y_top - 5, model.get("name") or "Applicant")
        cnv.setFont(sans, 7.0)
        cnv.setFillColor(_c(Theme.teal))
        contact_y = _draw_wrapped(cnv, model.get("headline") or "Medical Professional", x, y_top - 23, width - 4, font=sans, size=7.0, leading=9.0, color=Theme.teal)
        cnv.setFillColor(_c(Theme.muted))
        cnv.setFont(sans, 7.4)
        cnv.drawString(x, contact_y - 8, model.get("phone") or "")
        cnv.drawString(x, contact_y - 21, model.get("email") or "")
        y = contact_y - 52
        y = _draw_label(cnv, "Languages", x, y, fonts)
        _draw_rule(cnv, x, y + 2, width)
        y -= 14
        for lang, level in (model.get("languages") or [])[:4]:
            cnv.setFont(sans_bold, 7.2)
            cnv.setFillColor(_c(Theme.ink))
            cnv.drawString(x, y, lang[:22])
            cnv.setFont(sans, 7.2)
            cnv.setFillColor(_c(Theme.teal))
            cnv.drawRightString(x + width, y, level[:18])
            _draw_rule(cnv, x, y - 6, width)
            y -= 20
    y -= 12
    y = _draw_label(cnv, "Verified Medical Basis", x, y, fonts)
    _draw_rule(cnv, x, y + 2, width)
    y -= 13
    basis = []
    basis.extend((model.get("education") or [])[:1])
    basis.extend((model.get("registration") or [])[:1])
    basis.extend((model.get("exit_exam") or [])[:1])
    for item in basis[:3]:
        y = _draw_bullet(cnv, item, x + 2, y, width - 2, fonts, size=7.05, leading=9.3)
        y -= 5


def _draw_cv_credentials(cnv, model: dict[str, Any], x: float, y: float, width: float, fonts: tuple[str, str, str, str]) -> float:
    _, _, sans, sans_bold = fonts
    y = _draw_section(cnv, "Education & Verified Medical Credentials", x, y, width, fonts)
    label_w = 142
    rows = [
        ("Education", model.get("education") or []),
        ("Professional Registration", model.get("registration") or []),
        ("Medical Exit Exam", model.get("exit_exam") or []),
    ]
    for label, values in rows:
        top = y
        cnv.setFont(sans_bold, 6.7)
        cnv.setFillColor(_c(Theme.gold))
        cnv.drawString(x, top, label.upper())
        yy = top
        for line in values[:2]:
            yy = _draw_wrapped(cnv, line, x + label_w, yy, width - label_w, font=sans, size=7.7, leading=9.5)
        y = min(yy, top - 18) - 6
        _draw_rule(cnv, x, y + 3, width)
        y -= 9
    y -= 2
    y = _draw_section(cnv, "Certifications & Training", x, y, width, fonts)
    left_w = (width - 20) / 2
    y_left = y
    y_right = y
    for idx, cert in enumerate((model.get("certifications") or [])[:6]):
        if idx % 2 == 0:
            y_left = _draw_bullet(cnv, cert, x + 1, y_left, left_w - 1, fonts, size=7.35, leading=9.2)
            y_left -= 5
        else:
            y_right = _draw_bullet(cnv, cert, x + left_w + 21, y_right, left_w - 1, fonts, size=7.35, leading=9.2)
            y_right -= 5
    y = min(y_left, y_right) - 8
    y = _draw_section(cnv, "Languages", x, y, width, fonts)
    lang_text = " | ".join([f"{name} — {level}" if level else name for name, level in (model.get("languages") or [])])
    return _draw_wrapped(cnv, lang_text, x, y, width, font=sans, size=7.65, leading=9.8)


def render_cv_docx(model: dict[str, Any], path: str | Path) -> None:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Inches(0.45)
    sec.bottom_margin = Inches(0.45)
    sec.left_margin = Inches(0.55)
    sec.right_margin = Inches(0.55)
    styles = doc.styles
    styles["Normal"].font.name = "Aptos"
    styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "Aptos")
    styles["Normal"].font.size = Pt(8.8)

    def style(name: str, size: float, bold: bool = False, color: tuple[int, int, int] = (23, 42, 53), font: str = "Aptos"):
        st = styles.add_style(name, 1) if name not in styles else styles[name]
        st.font.name = font
        st._element.rPr.rFonts.set(qn("w:eastAsia"), font)
        st.font.size = Pt(size)
        st.font.bold = bold
        st.font.color.rgb = RGBColor(*color)
        st.paragraph_format.space_after = Pt(2)
        return st

    style("JF Name", 24, True, (12, 52, 66), "Georgia")
    style("JF Title", 10.5, False, (21, 124, 120))
    style("JF Contact", 8.1, False, (102, 115, 122))
    style("JF Section", 10, True, (12, 52, 66))
    style("JF Label", 6.8, True, (168, 132, 73))
    style("JF Role", 10.2, True, (12, 52, 66), "Georgia")
    style("JF Meta", 7.5, False, (102, 115, 122))
    style("JF Body", 8.2)

    def shade(cell, fill: str):
        shd = OxmlElement("w:shd")
        shd.set(qn("w:fill"), fill)
        cell._tc.get_or_add_tcPr().append(shd)

    def sec_cell(cell, text: str):
        cell.add_paragraph(text.upper(), style="JF Section")

    def bullet_cell(cell, text: str):
        p = cell.add_paragraph(style="JF Body")
        p.paragraph_format.left_indent = Inches(0.14)
        p.paragraph_format.first_line_indent = Inches(-0.1)
        p.add_run("• " + text)

    p = doc.add_paragraph(model.get("name") or "Applicant", style="JF Name")
    p.paragraph_format.space_after = Pt(0)
    doc.add_paragraph(model.get("headline") or "Medical Professional", style="JF Title")
    contact_line = " | ".join([x for x in [model.get("location"), model.get("phone"), model.get("email")] if x])
    doc.add_paragraph(contact_line, style="JF Contact")
    p = doc.add_paragraph("TARGET  ", style="JF Label")
    p.add_run(f"{model.get('target_role')} — {model.get('target_org')}").bold = True
    table = doc.add_table(1, 2)
    left, right = table.cell(0, 0), table.cell(0, 1)
    shade(left, "F6F8F7")
    sec_cell(left, "Clinical & Professional Strengths")
    for s in (model.get("strengths") or [])[:8]:
        bullet_cell(left, s)
    sec_cell(left, "Verified Medical Basis")
    for item in ((model.get("education") or [])[:1] + (model.get("registration") or [])[:1] + (model.get("exit_exam") or [])[:1]):
        bullet_cell(left, item)
    sec_cell(right, "Professional Profile")
    right.add_paragraph(model.get("profile") or "", style="JF Body")
    sec_cell(right, "Professional Experience")
    for item in (model.get("experience") or [])[:3]:
        right.add_paragraph(item.get("dates") or "", style="JF Label")
        right.add_paragraph(item.get("org") or "", style="JF Meta")
        right.add_paragraph(item.get("role") or "", style="JF Role")
        right.add_paragraph(item.get("loc") or "", style="JF Meta")
        for b in item.get("bullets", [])[:2]:
            bullet_cell(right, b)
    sec_cell(right, "Application Focus")
    right.add_paragraph(f"Tailored to {model.get('target_role')} using verified role-relevant evidence only.", style="JF Body")
    doc.add_page_break()
    doc.add_paragraph(f"{model.get('name')}    {model.get('target_role')} — {model.get('reference') or model.get('target_org')}", style="JF Section")
    table = doc.add_table(1, 2)
    left, right = table.cell(0, 0), table.cell(0, 1)
    shade(left, "F6F8F7")
    left.add_paragraph(model.get("name") or "Applicant", style="JF Section")
    left.add_paragraph((model.get("headline") or "Medical Professional")[:42], style="JF Title")
    left.add_paragraph(f"{model.get('phone') or ''}\n{model.get('email') or ''}", style="JF Contact")
    sec_cell(left, "Languages")
    for name, level in (model.get("languages") or []):
        bullet_cell(left, f"{name} — {level}" if level else name)
    sec_cell(left, "Verified Medical Basis")
    for item in ((model.get("education") or [])[:1] + (model.get("registration") or [])[:1] + (model.get("exit_exam") or [])[:1]):
        bullet_cell(left, item)
    sec_cell(right, "Professional Experience Continued")
    for item in (model.get("experience") or [])[3:]:
        right.add_paragraph(item.get("dates") or "", style="JF Label")
        right.add_paragraph(item.get("org") or "", style="JF Meta")
        right.add_paragraph(item.get("role") or "", style="JF Role")
        right.add_paragraph(item.get("loc") or "", style="JF Meta")
        for b in item.get("bullets", [])[:2]:
            bullet_cell(right, b)
    sec_cell(right, "Education & Verified Medical Credentials")
    for label, values in [("Education", model.get("education") or []), ("Professional Registration", model.get("registration") or []), ("Medical Exit Exam", model.get("exit_exam") or [])]:
        right.add_paragraph(label.upper(), style="JF Label")
        right.add_paragraph("\n".join(values), style="JF Body")
    sec_cell(right, "Certifications & Training")
    for cert in (model.get("certifications") or []):
        bullet_cell(right, cert)
    sec_cell(right, "Languages")
    right.add_paragraph(" | ".join([f"{n} — {lvl}" if lvl else n for n, lvl in (model.get("languages") or [])]), style="JF Body")
    for section in doc.sections:
        f = section.footer.paragraphs[0]
        f.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = f.add_run(f"{model.get('name')} — {model.get('target_role')}")
        run.font.size = Pt(7)
        run.font.color.rgb = RGBColor(102, 115, 122)
    doc.save(str(path))


# ---------------------------------------------------------------------------
# Cover letter renderers
# ---------------------------------------------------------------------------


def render_cover_letter_pdf(model: dict[str, Any], path: str | Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    fonts = _register_fonts()
    serif, serif_bold, sans, sans_bold = fonts
    width, height = A4
    cnv = canvas.Canvas(str(path), pagesize=A4)
    cnv.setTitle(f"{model.get('name')} — Cover Letter")
    cnv.setAuthor("Jobs-Finder")
    cnv.setFillColor(_c("#FFFFFF"))
    cnv.rect(0, 0, width, height, stroke=0, fill=1)
    cnv.setFillColor(_c(Theme.deep))
    cnv.rect(0, height - 11, width, 11, stroke=0, fill=1)
    cnv.setStrokeColor(_c(Theme.gold))
    cnv.setLineWidth(1.2)
    cnv.line(42, height - 48, width - 42, height - 48)
    cnv.setFont(serif_bold, 24)
    cnv.setFillColor(_c(Theme.deep))
    cnv.drawString(42, height - 82, model.get("name") or "Applicant")
    cnv.setFont(sans, 9.5)
    cnv.setFillColor(_c(Theme.teal))
    cnv.drawString(44, height - 101, model.get("headline") or "Medical Professional")
    contact = model.get("contact") or {}
    contact_line = " | ".join([x for x in [contact.get("location"), contact.get("phone"), contact.get("email")] if x])
    cnv.setFont(sans, 7.8)
    cnv.setFillColor(_c(Theme.muted))
    cnv.drawString(44, height - 118, contact_line)
    y = height - 155
    cnv.setFont(sans_bold, 7.0)
    cnv.setFillColor(_c(Theme.gold))
    cnv.drawString(44, y, "APPLICATION LETTER")
    cnv.setFont(sans_bold, 8.3)
    cnv.setFillColor(_c(Theme.deep))
    target = f"{model.get('target_role')} — {model.get('target_org')}"
    cnv.drawString(150, y, target[:98])
    y -= 15
    cnv.setFont(sans, 7.2)
    cnv.setFillColor(_c(Theme.muted))
    recipient = f"To: Hiring Committee, {model.get('target_org')}"
    cnv.drawString(150, y, recipient[:112])
    if model.get("reference"):
        cnv.drawRightString(width - 68, y, f"Reference: {model.get('reference')}")
    y -= 28
    y = _draw_section(cnv, "Subject", 90, y, width - 180, fonts)
    y = _draw_wrapped(cnv, model.get("subject") or "Application", 90, y, width - 180, font=sans_bold, size=9.0, leading=12)
    y -= 12
    cnv.setStrokeColor(_c(Theme.gold))
    cnv.setLineWidth(1.1)
    cnv.line(90, y + 7, 90, 158)
    for line in model.get("body_lines", []):
        if line.lower().startswith("subject:"):
            continue
        if line in {model.get("name"), "Sincerely,"}:
            continue
        if line.startswith("-"):
            y = _draw_bullet(cnv, _clean_bullet(line), 112, y, width - 202, fonts, size=8.35, leading=11.2)
        else:
            y = _draw_wrapped(cnv, line, 112, y, width - 202, font=sans, size=8.55, leading=11.5)
        y -= 6
    y = max(y, 112)
    cnv.setFont(sans, 8.7)
    cnv.setFillColor(_c(Theme.ink))
    cnv.drawString(112, y, "Sincerely,")
    cnv.setFont(serif_bold, 12)
    cnv.setFillColor(_c(Theme.deep))
    cnv.drawString(112, y - 22, model.get("name") or "Applicant")
    cnv.setStrokeColor(_c(Theme.rule))
    cnv.line(42, 38, width - 42, 38)
    cnv.setFont(sans, 6.6)
    cnv.setFillColor(_c(Theme.muted))
    cnv.drawString(42, 25, "Jobs-Finder review package · no submission performed")
    cnv.save()


def render_cover_letter_docx(model: dict[str, Any], path: str | Path) -> None:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Inches(0.62)
    sec.bottom_margin = Inches(0.62)
    sec.left_margin = Inches(0.72)
    sec.right_margin = Inches(0.72)
    styles = doc.styles
    styles["Normal"].font.name = "Aptos"
    styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "Aptos")
    styles["Normal"].font.size = Pt(9)

    def style(name: str, size: float, bold: bool = False, color: tuple[int, int, int] = (23, 42, 53), font: str = "Aptos"):
        st = styles.add_style(name, 1) if name not in styles else styles[name]
        st.font.name = font
        st._element.rPr.rFonts.set(qn("w:eastAsia"), font)
        st.font.size = Pt(size)
        st.font.bold = bold
        st.font.color.rgb = RGBColor(*color)
        st.paragraph_format.space_after = Pt(2)
        return st

    style("JF Name", 22, True, (12, 52, 66), "Georgia")
    style("JF Title", 10.3, False, (21, 124, 120))
    style("JF Contact", 8.0, False, (102, 115, 122))
    style("JF Label", 7.0, True, (168, 132, 73))
    style("JF Section", 10, True, (12, 52, 66))
    style("JF Body", 9.0, False, (23, 42, 53))
    style("JF Signature", 12, True, (12, 52, 66), "Georgia")

    doc.add_paragraph(model.get("name") or "Applicant", style="JF Name")
    doc.add_paragraph(model.get("headline") or "Medical Professional", style="JF Title")
    contact = model.get("contact") or {}
    doc.add_paragraph(" | ".join([x for x in [contact.get("location"), contact.get("phone"), contact.get("email")] if x]), style="JF Contact")
    doc.add_paragraph(f"APPLICATION LETTER — {model.get('target_role')} — {model.get('target_org')}", style="JF Label")
    recipient = f"To: Hiring Committee, {model.get('target_org')}"
    if model.get("reference"):
        recipient += f" | Reference: {model.get('reference')}"
    doc.add_paragraph(recipient, style="JF Contact")
    doc.add_paragraph("SUBJECT", style="JF Section")
    doc.add_paragraph(model.get("subject") or model.get("target_role") or "Application", style="JF Section")
    for line in model.get("body_lines", []):
        if line.lower().startswith("subject:") or line in {model.get("name"), "Sincerely,"}:
            continue
        if line.startswith("-"):
            p = doc.add_paragraph(style="JF Body")
            p.paragraph_format.left_indent = Inches(0.22)
            p.paragraph_format.first_line_indent = Inches(-0.12)
            p.add_run("• " + _clean_bullet(line))
        else:
            doc.add_paragraph(line, style="JF Body")
    doc.add_paragraph("Sincerely,", style="JF Body")
    doc.add_paragraph(model.get("name") or "Applicant", style="JF Signature")
    for section in doc.sections:
        f = section.footer.paragraphs[0]
        f.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = f.add_run("Jobs-Finder review package · no submission performed")
        run.font.size = Pt(7)
        run.font.color.rgb = RGBColor(102, 115, 122)
    doc.save(str(path))
