"""Global professional document design system for Jobs-Finder packages.

This module is deliberately presentation-focused: it receives already-tailored
document text from ``utils.documents`` (which is itself responsible for only
presenting verified facts as confirmed credentials -- see the EDUCATION /
LICENSE / MEDICAL EXIT EXAM gating in ``generate_tailored_documents``) and
renders it with a reusable medical/NGO visual identity.  It must not add
facts, and it must not claim a stronger verification status than the source
text actually supports.  The TXT artifact remains ATS/plain-text canonical;
the DOCX and PDF artifacts are designed views of that same content.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DESIGN_SYSTEM_NAME = "jobs-finder-editorial-medical"


def render_professional_document_artifacts(
    text: str,
    base_path: str | Path,
    *,
    document_type: str,
    metadata: dict[str, Any] | None = None,
    canonical_cv_model: dict[str, Any] | None = None,
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
        # The tailored generator can provide the content model directly. This
        # prevents a text re-parser from dropping/reinterpreting experience
        # lines between the canonical CV and its PDF/DOCX views.
        model = canonical_cv_model if isinstance(canonical_cv_model, dict) else parse_cv_text(text or "", metadata)
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
    headline_from_text = ""
    if len(nonempty) > 1 and ":" not in nonempty[1] and not nonempty[1].isupper():
        headline_from_text = nonempty[1]
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
    strengths = [_clean_bullet(x) for x in (sections.get("CORE PROFESSIONAL COMPETENCIES", []) or sections.get("CORE MEDICAL / PUBLIC HEALTH COMPETENCIES", []) or sections.get("CORE COMPETENCIES", []))]
    expanded: list[str] = []
    for item in strengths:
        expanded.extend([p.strip() for p in item.split(",") if p.strip()])
    strengths = expanded or [_clean_bullet(x) for x in sections.get("VACANCY-FIT HIGHLIGHTS", [])]
    strengths = _unique(strengths)
    def parse_experience(lines_for_section: list[str], group: str) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for line in lines_for_section:
            if line.startswith("-") and current:
                current.setdefault("bullets", []).append(_clean_bullet(line))
            elif current and " | " in line and not current.get("org"):
                # Canonical CV text uses a separate Employer | Location | Dates
                # metadata line below each title for readability.
                parts = [part.strip() for part in line.split("|")]
                current["org"] = parts[0] if parts else ""
                current["loc"] = parts[1] if len(parts) > 1 else ""
                current["dates"] = parts[2] if len(parts) > 2 else ""
            elif not line.startswith("-"):
                if current:
                    parsed.append(current)
                current = _parse_experience_header(line)
                current["bullets"] = []
                current["group"] = group
        if current:
            parsed.append(current)
        return parsed

    relevant_experience = parse_experience(
        sections.get("MOST RELEVANT PROFESSIONAL EXPERIENCE", []) or sections.get("PROFESSIONAL EXPERIENCE", []),
        "most_relevant",
    )
    remaining_experience = parse_experience(sections.get("REMAINING PROFESSIONAL EXPERIENCE", []), "remaining")
    experience = relevant_experience + remaining_experience
    education = [_clean_bullet(x) for x in sections.get("EDUCATION", [])]
    registration = [_clean_bullet(x) for x in (sections.get("PROFESSIONAL REGISTRATION", []) or sections.get("PROFESSIONAL REGISTRATION / LICENSE", []) or sections.get("LICENSE / REGISTRATION", []))]
    exit_exam = [_clean_bullet(x) for x in (sections.get("MEDICAL EXIT EXAMINATION", []) or sections.get("MEDICAL EXIT EXAM", []))]
    certs = [_clean_bullet(x) for x in (sections.get("RELEVANT TRAINING & CERTIFICATIONS", []) or sections.get("RELEVANT PROFESSIONAL TRAINING & CERTIFICATIONS", []) or sections.get("CERTIFICATIONS & TRAINING", []))]
    languages_raw = [_clean_bullet(x) for x in sections.get("LANGUAGES", [])]
    languages = _split_languages(languages_raw[0]) if languages_raw else []
    headline = headline_from_text or "Medical Doctor"
    return {
        "design_system": DESIGN_SYSTEM_NAME,
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
        "design_system": DESIGN_SYSTEM_NAME,
        "name": name,
        "headline": "Application Letter",
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
    """Register the design-system fonts portably.

    TTF candidates are tried per platform (Linux DejaVu, Windows system
    fonts, macOS system fonts). When no candidate file is available or
    registration fails, the role falls back to ReportLab's built-in Type 1
    fonts (Times/Helvetica), which require no font files on any OS, so every
    returned name is registered and renderable on Windows, Linux, and macOS.
    """
    import os

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates: dict[str, list[Path]] = {
        "JFSerif": [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
            windows_fonts / "georgia.ttf",
            windows_fonts / "times.ttf",
            Path("/Library/Fonts/Georgia.ttf"),
        ],
        "JFSerifBold": [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
            windows_fonts / "georgiab.ttf",
            windows_fonts / "timesbd.ttf",
            Path("/Library/Fonts/Georgia Bold.ttf"),
        ],
        "JFSans": [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            windows_fonts / "arial.ttf",
            Path("/Library/Fonts/Arial.ttf"),
        ],
        "JFSansBold": [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            windows_fonts / "arialbd.ttf",
            Path("/Library/Fonts/Arial Bold.ttf"),
        ],
    }
    builtin_fallbacks = {
        "JFSerif": "Times-Roman",
        "JFSerifBold": "Times-Bold",
        "JFSans": "Helvetica",
        "JFSansBold": "Helvetica-Bold",
    }
    resolved: dict[str, str] = {}
    registered = set(pdfmetrics.getRegisteredFontNames())
    for name, paths in candidates.items():
        if name in registered:
            resolved[name] = name
            continue
        for path in paths:
            try:
                if path.is_file():
                    pdfmetrics.registerFont(TTFont(name, str(path)))
                    resolved[name] = name
                    break
            except Exception:  # pragma: no cover - corrupt/unreadable font file
                continue
        if name not in resolved:
            resolved[name] = builtin_fallbacks[name]
    return resolved["JFSerif"], resolved["JFSerifBold"], resolved["JFSans"], resolved["JFSansBold"]


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


# ---------------------------------------------------------------------------
# CV PDF / DOCX renderers
# ---------------------------------------------------------------------------


def render_cv_pdf(model: dict[str, Any], path: str | Path) -> None:
    """Render a readable, content-driven CV with automatic pagination."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    serif, serif_bold, sans, sans_bold = _register_fonts()
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=12 * mm, bottomMargin=13 * mm,
        title=f"{model.get('name') or 'Applicant'} — Curriculum Vitae",
        author=model.get("name") or "Applicant",
    )
    styles = getSampleStyleSheet()
    name_style = ParagraphStyle("CVName", parent=styles["Title"], fontName=serif_bold, fontSize=22, leading=25, textColor=colors.HexColor(Theme.deep), spaceAfter=2)
    title_style = ParagraphStyle("CVTitle", parent=styles["Normal"], fontName=sans, fontSize=10.5, leading=13, textColor=colors.HexColor(Theme.teal), spaceAfter=3)
    contact_style = ParagraphStyle("CVContact", parent=styles["Normal"], fontName=sans, fontSize=8.5, leading=11, textColor=colors.HexColor(Theme.muted), spaceAfter=10)
    section_style = ParagraphStyle("CVSection", parent=styles["Heading2"], fontName=sans_bold, fontSize=10.3, leading=12.2, textColor=colors.HexColor(Theme.deep), spaceBefore=5, spaceAfter=2.5, borderColor=colors.HexColor(Theme.rule), borderWidth=0, borderBottomWidth=.6, borderPadding=(0, 0, 2.5, 0), keepWithNext=True)
    role_style = ParagraphStyle("CVRole", parent=styles["Heading3"], fontName=serif_bold, fontSize=10.2, leading=12, textColor=colors.HexColor(Theme.deep), spaceBefore=3, spaceAfter=.7, keepWithNext=True)
    meta_style = ParagraphStyle("CVMeta", parent=styles["Normal"], fontName=sans, fontSize=8, leading=9.4, textColor=colors.HexColor(Theme.muted), spaceAfter=2, keepWithNext=True)
    body_style = ParagraphStyle("CVBody", parent=styles["BodyText"], fontName=sans, fontSize=8.8, leading=11.1, textColor=colors.HexColor(Theme.ink), spaceAfter=3.5)
    bullet_style = ParagraphStyle("CVBullet", parent=body_style, leftIndent=11, firstLineIndent=-7, bulletIndent=0, spaceAfter=.5)

    def esc(value: Any) -> str:
        from xml.sax.saxutils import escape
        return escape(str(value or ""))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor(Theme.rule))
        canvas.line(18 * mm, 11 * mm, A4[0] - 18 * mm, 11 * mm)
        canvas.setFont(sans, 7)
        canvas.setFillColor(colors.HexColor(Theme.muted))
        canvas.drawString(18 * mm, 7 * mm, str(model.get("name") or "Applicant"))
        canvas.drawRightString(A4[0] - 18 * mm, 7 * mm, f"Page {document.page}")
        canvas.restoreState()

    story: list[Any] = [
        Paragraph(esc(model.get("name") or "Applicant"), name_style),
        Paragraph(esc(model.get("headline") or "Medical Professional"), title_style),
        Paragraph(esc(" | ".join(str(x) for x in (model.get("contact_lines") or [model.get("location"), model.get("phone"), model.get("email")]) if x)), contact_style),
        Paragraph("PROFESSIONAL SUMMARY", section_style),
        Paragraph(esc(model.get("profile") or ""), body_style),
    ]
    if model.get("strengths"):
        story.append(Paragraph("CORE PROFESSIONAL COMPETENCIES", section_style))
        for item in model.get("strengths") or []:
            story.append(Paragraph(esc(item), bullet_style, bulletText="•"))

    experience = list(model.get("experience") or [])

    def add_experience(title: str, entries: list[dict[str, Any]]) -> None:
        if not entries:
            return
        story.append(Paragraph(title, section_style))
        for item in entries:
            role = esc(item.get("role") or "")
            org = esc(item.get("org") or "")
            dates = esc(item.get("dates") or "")
            story.append(Paragraph(role, role_style))
            meta = " | ".join(x for x in [org, esc(item.get("loc") or ""), dates] if x)
            story.append(Paragraph(meta, meta_style))
            for bullet in item.get("bullets") or []:
                story.append(Paragraph(esc(bullet), bullet_style, bulletText="•"))

    # Place credentials before chronology to balance real multi-page CVs; this
    # is mirrored by TXT and DOCX from the same canonical model.
    for title, values in [
        ("EDUCATION", model.get("education") or []),
        ("PROFESSIONAL REGISTRATION", model.get("registration") or []),
        ("MEDICAL EXIT EXAMINATION", model.get("exit_exam") or []),
    ]:
        if values:
            story.append(Paragraph(title, section_style))
            for value in values:
                story.append(Paragraph(esc(value), bullet_style, bulletText="•"))
    add_experience("PROFESSIONAL EXPERIENCE", experience)
    if model.get("certifications"):
        story.append(Paragraph("TRAINING & CERTIFICATIONS", section_style))
        for value in model.get("certifications") or []:
            story.append(Paragraph(esc(value), bullet_style, bulletText="•"))
    if model.get("languages"):
        story.append(Paragraph("LANGUAGES", section_style))
        language_line = "  |  ".join(f"{language} — {level}" if level else language for language, level in model.get("languages") or [])
        story.append(Paragraph(esc(language_line), bullet_style, bulletText="•"))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def render_cv_docx(model: dict[str, Any], path: str | Path) -> None:
    """Render the complete CV in a single-column, auto-paginating layout."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.48)
    section.bottom_margin = Inches(0.50)
    section.left_margin = Inches(0.60)
    section.right_margin = Inches(0.60)
    styles = doc.styles
    styles["Normal"].font.name = "Aptos"
    styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "Aptos")
    styles["Normal"].font.size = Pt(8.8)

    def style(name: str, size: float, bold: bool = False, color=(23, 42, 53), font="Aptos"):
        st = styles.add_style(name, 1) if name not in styles else styles[name]
        st.font.name = font
        st._element.rPr.rFonts.set(qn("w:eastAsia"), font)
        st.font.size = Pt(size)
        st.font.bold = bold
        st.font.color.rgb = RGBColor(*color)
        return st

    name_style = style("CV Name", 22, True, (12, 52, 66), "Georgia")
    name_style.paragraph_format.space_after = Pt(0)
    title_style = style("CV Professional Title", 10.5, False, (21, 124, 120))
    title_style.paragraph_format.space_after = Pt(2)
    contact_style = style("CV Contact", 8.2, False, (102, 115, 122))
    contact_style.paragraph_format.space_after = Pt(7)
    section_style = style("CV Section", 10.2, True, (12, 52, 66))
    section_style.paragraph_format.space_before = Pt(6)
    section_style.paragraph_format.space_after = Pt(2)
    role_style = style("CV Role", 10.2, True, (12, 52, 66), "Georgia")
    role_style.paragraph_format.space_before = Pt(4)
    role_style.paragraph_format.space_after = Pt(0)
    role_style.paragraph_format.keep_with_next = True
    meta_style = style("CV Meta", 7.8, False, (102, 115, 122))
    meta_style.paragraph_format.space_after = Pt(1)
    meta_style.paragraph_format.keep_with_next = True
    body_style = style("CV Body", 8.8, False, (23, 42, 53))
    body_style.paragraph_format.space_after = Pt(2)

    def add_section(title: str) -> None:
        p = doc.add_paragraph(title, style="CV Section")
        p.paragraph_format.keep_with_next = True
        pPr = p._p.get_or_add_pPr()
        borders = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "4")
        bottom.set(qn("w:color"), "D7E0E2")
        borders.append(bottom)
        pPr.append(borders)

    def add_bullet(text: str) -> None:
        p = doc.add_paragraph(style="CV Body")
        p.paragraph_format.left_indent = Inches(0.18)
        p.paragraph_format.first_line_indent = Inches(-0.12)
        p.paragraph_format.space_after = Pt(1)
        p.add_run("• ")
        p.add_run(str(text))

    doc.add_paragraph(model.get("name") or "Applicant", style="CV Name")
    doc.add_paragraph(model.get("headline") or "Medical Professional", style="CV Professional Title")
    contact = " | ".join(str(x) for x in (model.get("contact_lines") or [model.get("location"), model.get("phone"), model.get("email")]) if x)
    doc.add_paragraph(contact, style="CV Contact")
    add_section("PROFESSIONAL SUMMARY")
    doc.add_paragraph(model.get("profile") or "", style="CV Body")
    if model.get("strengths"):
        add_section("CORE PROFESSIONAL COMPETENCIES")
        for value in model.get("strengths") or []:
            add_bullet(value)

    experience = list(model.get("experience") or [])

    def add_experience(title: str, entries: list[dict[str, Any]]) -> None:
        if not entries:
            return
        add_section(title)
        for item in entries:
            doc.add_paragraph(item.get("role") or "", style="CV Role")
            meta = " | ".join(x for x in [item.get("org"), item.get("loc"), item.get("dates")] if x)
            doc.add_paragraph(meta, style="CV Meta")
            for bullet in item.get("bullets") or []:
                add_bullet(bullet)

    for title, values in [
        ("EDUCATION", model.get("education") or []),
        ("PROFESSIONAL REGISTRATION", model.get("registration") or []),
        ("MEDICAL EXIT EXAMINATION", model.get("exit_exam") or []),
    ]:
        if values:
            add_section(title)
            for value in values:
                add_bullet(value)
    add_experience("PROFESSIONAL EXPERIENCE", experience)
    if model.get("certifications"):
        add_section("TRAINING & CERTIFICATIONS")
        for value in model.get("certifications") or []:
            add_bullet(value)
    if model.get("languages"):
        add_section("LANGUAGES")
        language_line = "  |  ".join(f"{language} — {level}" if level else language for language, level in model.get("languages") or [])
        add_bullet(language_line)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run(str(model.get("name") or "Applicant"))
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
    cnv.setAuthor(model.get("name") or "Applicant")
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
    cnv.drawString(42, 25, f"{model.get('name') or 'Applicant'} — Cover Letter")
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
        run = f.add_run(f"{model.get('name') or 'Applicant'} — Cover Letter")
        run.font.size = Pt(7)
        run.font.color.rgb = RGBColor(102, 115, 122)
    doc.save(str(path))
