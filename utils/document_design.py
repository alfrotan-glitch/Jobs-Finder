"""Global professional document design system for Jobs-Finder packages.

This module is deliberately presentation-focused: it receives already-tailored
document text from ``utils.documents`` (which is itself responsible for only
presenting verified facts as confirmed credentials -- see the EDUCATION /
LICENSE / MEDICAL EXIT EXAM gating in ``generate_tailored_documents``) and
renders it with a reusable medical/NGO visual identity.  It must not add
facts, and it must not claim a stronger verification status than the source
text actually supports.  The TXT artifact remains plain-text canonical;
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
        scale = render_cv_pdf(model, pdf)
        render_cv_docx(model, docx, scale=scale)
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
    name = nonempty[0] if nonempty else "CONFIRM BEFORE SUBMISSION"
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
    competency_lines = (
        sections.get("CORE PROFESSIONAL COMPETENCIES", [])
        or sections.get("CORE MEDICAL / PUBLIC HEALTH COMPETENCIES", [])
        or sections.get("CORE COMPETENCIES", [])
    )
    # Preferred shape is the grouped professional skills architecture
    # ("Group: item; item"); the flat/comma-separated shape is still accepted
    # so older plain-text CVs keep rendering.
    expertise: list[dict[str, Any]] = []
    flat: list[str] = []
    for raw in competency_lines:
        line = _clean_bullet(raw)
        if not line:
            continue
        if ":" in line and "://" not in line:
            label, values = line.split(":", 1)
            items = [value.strip() for value in re.split(r"\s*[;·]\s*", values) if value.strip()]
            if label.strip() and items:
                expertise.append({"group": label.strip(), "items": _unique(items)})
                flat.extend(items)
                continue
        flat.extend([p.strip() for p in line.split(",") if p.strip()])
    strengths = _unique(flat) or [_clean_bullet(x) for x in sections.get("VACANCY-FIT HIGHLIGHTS", [])]
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
                current = {**_parse_experience_header(line), "bullets": [], "group": group}
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
    certs = [_clean_bullet(x) for x in (sections.get("PROFESSIONAL TRAINING & CERTIFICATIONS", []) or sections.get("RELEVANT TRAINING & CERTIFICATIONS", []) or sections.get("RELEVANT PROFESSIONAL TRAINING & CERTIFICATIONS", []) or sections.get("CERTIFICATIONS & TRAINING", []) or sections.get("TRAINING & CERTIFICATIONS", []))]
    languages_raw = [_clean_bullet(x) for x in sections.get("LANGUAGES", [])]
    languages = _split_languages(languages_raw[0]) if languages_raw else []
    references = [_clean_bullet(x) for x in sections.get("REFERENCES", [])]
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
        "expertise": expertise,
        "strengths": strengths,
        "experience": experience,
        "education": education,
        "registration": registration,
        "exit_exam": exit_exam,
        "certifications": certs,
        "languages": languages,
        "references": references,
        "raw_text": text or "",
    }


def parse_cover_letter_text(text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Split a generated cover letter into its body and signature block.

    The signature block (``Sincerely,`` plus the name, professional title, and
    contact lines) is separated from the body so the renderer can lay it out
    once, in the right position, instead of letting it flow as body text.
    """
    metadata = metadata or {}
    job = metadata.get("job") or {}
    package = metadata.get("package") or {}
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    subject = ""
    body_lines: list[str] = []
    signature: dict[str, str] = {"name": "", "title": "", "email": "", "phone": ""}
    in_signature = False
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("subject:"):
            subject = stripped.split(":", 1)[1].strip()
            continue
        if not stripped:
            continue
        if stripped.lower() in {"sincerely,", "sincerely", "yours sincerely,"}:
            in_signature = True
            continue
        if in_signature:
            lowered = stripped.lower()
            if lowered.startswith("email:"):
                signature["email"] = stripped.split(":", 1)[1].strip()
                continue
            if lowered.startswith("phone:"):
                signature["phone"] = stripped.split(":", 1)[1].strip()
                continue
            if not signature["name"]:
                signature["name"] = stripped
                continue
            if not signature["title"]:
                signature["title"] = stripped
                continue
            continue
        body_lines.append(stripped)
    name = signature["name"] or _full_name_from_package(package) or "CONFIRM BEFORE SUBMISSION"
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
        "signature": signature,
        "raw_text": text or "",
    }


def _reference_shown_in_heading(model: dict[str, Any]) -> bool:
    """Show the vacancy reference in the letter heading only if the subject lacks it.

    The subject line carries the reference whenever the posting asks for it, so
    printing it again in the heading would only repeat the same value.
    """
    reference = str(model.get("reference") or "").strip()
    if not reference:
        return False
    return reference not in str(model.get("subject") or "")


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
            usable_font = False
            try:
                usable_font = path.is_file()
                if usable_font:
                    pdfmetrics.registerFont(TTFont(name, str(path)))
            except Exception:  # pragma: no cover - corrupt/unreadable font file
                usable_font = False
            if usable_font:
                resolved[name] = name
                break
        if name not in resolved:
            resolved[name] = builtin_fallbacks[name]
    # ReportLab silently drops markup emphasis unless the family is registered:
    # a bare ``<b>`` in a Paragraph is otherwise rendered in the regular weight.
    # There is no bundled italic face, so italic maps to the regular face rather
    # than to a slanted substitute -- emphasis in these documents is bold.
    for family, (regular, bold) in {
        "JFSerif": ("JFSerif", "JFSerifBold"),
        "JFSans": ("JFSans", "JFSansBold"),
    }.items():
        pdfmetrics.registerFontFamily(
            family,
            normal=resolved[regular],
            bold=resolved[bold],
            italic=resolved[regular],
            boldItalic=resolved[bold],
        )
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


def _cv_contact_line(model: dict[str, Any]) -> str:
    values = model.get("contact_lines") or [model.get("location"), model.get("phone"), model.get("email")]
    return " | ".join(str(value) for value in values if value)


def _cv_expertise_groups(model: dict[str, Any]) -> list[dict[str, Any]]:
    groups = [group for group in (model.get("expertise") or []) if group.get("items")]
    if groups:
        return groups
    strengths = [str(item) for item in (model.get("strengths") or []) if str(item).strip()]
    return [{"group": "", "items": strengths}] if strengths else []


def _pdf_last_page_fill_ratio(path: str | Path) -> float:
    """How full the final page of a built PDF is (0..1), ignoring the footer.

    Used only to detect a sparse trailing page that would leave a large empty
    area at the end of a CV. It never changes any text content.
    """
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            if len(pdf.pages) < 2:
                return 1.0
            page = pdf.pages[-1]
            usable_bottom = page.height - 45
            body = [char for char in page.chars if char.get("bottom", 0) < usable_bottom]
            if not body:
                return 0.0
            top = min(char["top"] for char in body)
            bottom = max(char["bottom"] for char in body)
            span = max(usable_bottom - 40, 1)
            return max(0.0, min(1.0, (bottom - top) / span))
    except Exception:  # pragma: no cover - measurement is best-effort only
        return 1.0


# Shared CV typography (points). Compact only trims whitespace: body text
# never shrinks to squeeze a comprehensive CV onto one page.
CV_PDF_LAYOUTS: dict[str, dict[str, float]] = {
    "comfortable": {
        "name": 25, "title": 11, "contact": 9, "section": 9.5,
        "role": 11, "meta": 9.5, "body": 10.5, "leading": 14.4,
        "bullets": 9, "bullet_leading": 14.4, "section_before": 14,
        "section_after": 6, "role_before": 10, "meta_after": 4,
        "group_after": 3, "bullet_after": 4,
    },
}
CV_PDF_LAYOUTS["compact"] = {
    **CV_PDF_LAYOUTS["comfortable"], "leading": 13.6,
    "bullet_leading": 13.6, "section_before": 9, "section_after": 5,
    "role_before": 7, "meta_after": 3, "group_after": 2, "bullet_after": 2,
}
CV_MARGIN_MM = 18
CV_TOP_MM = 16
CV_BOTTOM_MM = 17


def _cv_word_font() -> str:
    """Use the PDF's installed sans family in Word on the generating system.

    Word may substitute on another machine; embedding fonts or promising
    identical pagination across Word engines would be misleading.
    """
    from reportlab.pdfbase import pdfmetrics

    sans = _register_fonts()[2]
    family = getattr(pdfmetrics.getFont(sans).face, "familyName", "Arial")
    return family.decode("utf-8") if isinstance(family, bytes) else str(family)


def _cv_bullet_glyph() -> str:
    """Type 1 WinAnsi bullets can extract as undefined CID 127 in PDF readers.

    On fontless machines use an ordinary searchable dash in both CV formats;
    installed TrueType fonts retain the round bullet and Unicode mapping.
    """
    from reportlab.pdfbase import pdfmetrics

    font = pdfmetrics.getFont(_register_fonts()[2])
    return "•" if getattr(font, "_dynamicFont", False) else "-"


def _build_cv_pdf(model: dict[str, Any], path: str | Path, scale: dict[str, float]) -> int:
    """Build one CV PDF with the given typographic scale; return its page count."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        HRFlowable,
        KeepTogether,
        PageTemplate,
        Paragraph,
    )

    serif, serif_bold, sans, sans_bold = _register_fonts()
    doc = BaseDocTemplate(
        str(path), pagesize=A4, rightMargin=CV_MARGIN_MM * mm, leftMargin=CV_MARGIN_MM * mm,
        topMargin=CV_TOP_MM * mm, bottomMargin=CV_BOTTOM_MM * mm,
        title=f"{model.get('name') or 'CONFIRM BEFORE SUBMISSION'} — Curriculum Vitae",
        author=model.get("name") or "CONFIRM BEFORE SUBMISSION",
        subject="Curriculum Vitae",
    )
    # SimpleDocTemplate otherwise adds hidden 6pt padding on all four sides.
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    styles = getSampleStyleSheet()
    name_style = ParagraphStyle("CVName", parent=styles["Title"], fontName=sans_bold, fontSize=scale["name"], leading=scale["name"] * 1.15, textColor=colors.HexColor(Theme.deep), spaceAfter=1, alignment=0)
    title_style = ParagraphStyle("CVTitle", parent=styles["Normal"], fontName=sans, fontSize=scale["title"], leading=scale["title"] * 1.22, textColor=colors.HexColor(Theme.teal), spaceAfter=3)
    contact_style = ParagraphStyle("CVContact", parent=styles["Normal"], fontName=sans, fontSize=scale["contact"], leading=scale["contact"] * 1.3, textColor=colors.HexColor(Theme.muted), spaceAfter=8)
    section_style = ParagraphStyle(
        "CVSection", parent=styles["Heading2"], fontName=sans_bold, fontSize=scale["section"], leading=scale["section"] * 1.2, textColor=colors.HexColor(Theme.deep),
        spaceBefore=scale["section_before"], spaceAfter=3,
        keepWithNext=True,
    )
    group_style = ParagraphStyle("CVGroup", parent=styles["Normal"], fontName=sans, fontSize=scale["body"], leading=scale["leading"], textColor=colors.HexColor(Theme.ink), spaceAfter=scale["group_after"])
    role_style = ParagraphStyle("CVRole", parent=styles["Heading3"], fontName=sans_bold, fontSize=scale["role"], leading=scale["role"] * 1.19, textColor=colors.HexColor(Theme.deep), spaceBefore=scale["role_before"], spaceAfter=.8, keepWithNext=True)
    meta_style = ParagraphStyle("CVMeta", parent=styles["Normal"], fontName=sans, fontSize=scale["meta"], leading=scale["meta"] * 1.22, textColor=colors.HexColor(Theme.muted), spaceAfter=scale["meta_after"], keepWithNext=True)
    body_style = ParagraphStyle("CVBody", parent=styles["BodyText"], fontName=sans, fontSize=scale["body"], leading=scale["leading"], textColor=colors.HexColor(Theme.ink), spaceBefore=0, spaceAfter=3.2)
    bullet_style = ParagraphStyle(
        "CVBullet", parent=body_style, leftIndent=11, firstLineIndent=0, bulletIndent=0,
        spaceAfter=scale["bullet_after"], leading=scale["bullet_leading"],
        bulletFontName=sans, bulletFontSize=scale["bullets"], bulletColor=colors.HexColor(Theme.teal),
    )

    def esc(value: Any) -> str:
        import html
        return html.escape(str(value or ""))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor(Theme.rule))
        canvas.setLineWidth(0.5)
        canvas.line(CV_MARGIN_MM * mm, 11.5 * mm, A4[0] - CV_MARGIN_MM * mm, 11.5 * mm)
        canvas.setFont(sans, 7)
        canvas.setFillColor(colors.HexColor(Theme.muted))
        canvas.drawString(CV_MARGIN_MM * mm, 7.5 * mm, str(model.get("name") or "CONFIRM BEFORE SUBMISSION"))
        canvas.drawRightString(A4[0] - CV_MARGIN_MM * mm, 7.5 * mm, f"Page {document.page}")
        canvas.restoreState()

    def add_section(title):
        story.append(Paragraph(title, section_style))
        # borderBottomWidth is not implemented by ReportLab Paragraph. Use a
        # real flowable, chained to the heading and its first content block.
        rule = HRFlowable(width="100%", thickness=.6, color=colors.HexColor(Theme.rule),
                          spaceAfter=scale["section_after"])
        rule.keepWithNext = True
        story.append(rule)

    story: list[Any] = [
        Paragraph(esc(model.get("name") or "CONFIRM BEFORE SUBMISSION"), name_style),
        Paragraph(esc(model.get("headline") or "Medical Professional"), title_style),
    ]
    contact_line = _cv_contact_line(model)
    if contact_line:
        story.append(Paragraph(esc(contact_line), contact_style))
    header_rule = HRFlowable(width="100%", thickness=1.5, color=colors.HexColor(Theme.teal))
    header_rule.keepWithNext = True
    story.append(header_rule)
    if model.get("profile"):
        add_section("PROFESSIONAL SUMMARY")
        story.append(Paragraph(esc(model.get("profile")), body_style))

    groups = _cv_expertise_groups(model)
    if groups:
        add_section("CORE PROFESSIONAL COMPETENCIES")
        for group in groups:
            items = "&nbsp;· ".join(esc(item) for item in group.get("items") or [])
            label = esc(group.get("group") or "")
            paragraph = Paragraph(f"<b>{label}:</b> {items}" if label else items, group_style)
            # A group label must never be left stranded at the foot of a page
            # with its competencies continuing overleaf.
            story.append(KeepTogether(paragraph))

    experience = list(model.get("experience") or [])
    if experience:
        add_section("PROFESSIONAL EXPERIENCE")
        for item in experience:
            story.append(Paragraph(esc(item.get("role") or ""), role_style))
            meta = " | ".join(value for value in [
                f"<b>{esc(item['org'])}</b>" if item.get("org") else "",
                esc(item.get("dates")),
            ] if value)
            if meta:
                story.append(Paragraph(meta, meta_style))
            if item.get("loc"):
                story.append(Paragraph(esc(item["loc"]), meta_style))
            for bullet in item.get("bullets") or []:
                story.append(Paragraph(esc(bullet), bullet_style, bulletText=_cv_bullet_glyph()))

    for title, values in [
        ("EDUCATION", model.get("education") or []),
        ("PROFESSIONAL REGISTRATION", model.get("registration") or []),
        ("MEDICAL EXIT EXAMINATION", model.get("exit_exam") or []),
        ("PROFESSIONAL TRAINING & CERTIFICATIONS", model.get("certifications") or []),
    ]:
        if values:
            add_section(title)
            # A single statement is set as a line; only a real list is bulleted,
            # matching how LANGUAGES and REFERENCES are set.
            single = len(values) == 1
            for value in values:
                if single:
                    story.append(Paragraph(esc(value), body_style))
                else:
                    story.append(Paragraph(esc(value), bullet_style, bulletText=_cv_bullet_glyph()))
    if model.get("languages"):
        add_section("LANGUAGES")
        language_line = "  |  ".join(f"{name}{(' — ' + level) if level else ''}" for name, level in model.get("languages") or [])
        story.append(Paragraph(esc(language_line), body_style))
    references = [str(item) for item in (model.get("references") or []) if str(item).strip()]
    if references:
        add_section("REFERENCES")
        for value in references:
            story.append(Paragraph(esc(value), body_style))
    # BaseDocTemplate respects our zero-padding frame on every page.
    doc.addPageTemplates(PageTemplate(id="CV", frames=frame, onPage=footer))
    doc.build(story)
    return int(getattr(doc, "page", 1)) if isinstance(getattr(doc, "page", None), int) else _pdf_page_count(path)


def _pdf_page_count(path: str | Path) -> int:
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            return len(pdf.pages)
    except Exception:  # pragma: no cover - best-effort only
        return 1


def render_cv_pdf(model: dict[str, Any], path: str | Path) -> dict[str, float]:
    """Render complete, automatically paginated content; return shared scale.

    Retry a sparse final page with whitespace-only compaction. Keep it only if
    it removes a page; otherwise restore the comfortable original. The caller
    applies the same chosen scale to DOCX. No facts, font sizes or ordering
    change, and no fixed page count is imposed.
    """
    scale = CV_PDF_LAYOUTS["comfortable"]
    pages = _build_cv_pdf(model, path, scale)
    if pages > 1 and _pdf_last_page_fill_ratio(path) < 0.4:
        compact_pages = _build_cv_pdf(model, path, CV_PDF_LAYOUTS["compact"])
        if compact_pages < pages:
            return CV_PDF_LAYOUTS["compact"]
        _build_cv_pdf(model, path, scale)
    return scale


def _docx_page_field(paragraph) -> None:
    """Append a real Word PAGE field so pagination is visible in Word."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = "PAGE"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instruction)
    run._r.append(end)


def render_cv_docx(model: dict[str, Any], path: str | Path, *, scale: dict[str, float] | None = None) -> None:
    """Render the complete CV in a single-column, auto-paginating layout."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    scale = scale or CV_PDF_LAYOUTS["comfortable"]
    font = _cv_word_font()
    doc = Document()
    doc.core_properties.title = f"{model.get('name') or 'CV'} — Curriculum Vitae"
    doc.core_properties.author = str(model.get("name") or "")
    section = doc.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.top_margin, section.bottom_margin = Mm(CV_TOP_MM), Mm(CV_BOTTOM_MM)
    section.left_margin = section.right_margin = Mm(CV_MARGIN_MM)
    section.footer_distance = Mm(8)
    styles = doc.styles
    styles["Normal"].font.name = font
    styles["Normal"].font.size = Pt(scale["body"])
    styles["Normal"].paragraph_format.space_after = Pt(0)

    def style(name, size, *, bold=False, color=Theme.ink, leading=None, before=0, after=0, keep=False, heading=None):
        st = styles.add_style(name, 1)
        st.base_style = styles[heading or "Normal"]
        st.font.name = font
        st._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), font)
        st.font.size = Pt(size)
        st.font.bold = bold
        st.font.color.rgb = RGBColor.from_string(color.lstrip("#"))
        fmt = st.paragraph_format
        fmt.line_spacing = Pt(leading or size * 1.22)
        fmt.space_before, fmt.space_after = Pt(before), Pt(after)
        fmt.keep_with_next = keep
        fmt.keep_together = True
        fmt.widow_control = True
        return st

    style("CV Name", scale["name"], bold=True, color=Theme.deep, leading=scale["name"] * 1.15, after=1, keep=True)
    style("CV Professional Title", scale["title"], color=Theme.teal, after=3, keep=True)
    style("CV Contact", scale["contact"], color=Theme.muted, leading=scale["contact"] * 1.3, after=8, keep=True)
    style("CV Section", scale["section"], bold=True, color=Theme.deep, before=scale["section_before"], after=scale["section_after"] + 3, keep=True, heading="Heading 1")
    style("CV Competency Group", scale["body"], leading=scale["leading"], after=scale["group_after"])
    style("CV Role", scale["role"], bold=True, color=Theme.deep, leading=scale["role"] * 1.19, before=scale["role_before"], after=.8, keep=True, heading="Heading 2")
    style("CV Meta", scale["meta"], color=Theme.muted, after=scale["meta_after"], keep=True)
    style("CV Body", scale["body"], leading=scale["leading"], after=3.2)
    style("CV Bullet", scale["body"], leading=scale["bullet_leading"], after=scale["bullet_after"])

    def border(p, color, size):
        borders = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        for key, value in {"val": "single", "sz": str(size), "color": color.lstrip("#"), "space": "3"}.items():
            bottom.set(qn("w:" + key), value)
        borders.append(bottom)
        p._p.get_or_add_pPr().append(borders)

    def add_section(title: str) -> None:
        p = doc.add_paragraph(title, style="CV Section")
        p.paragraph_format.keep_with_next = True
        border(p, Theme.rule, 4)

    def add_bullet(text: str) -> None:
        p = doc.add_paragraph(style="CV Bullet")
        p.paragraph_format.left_indent = Pt(11)
        p.paragraph_format.first_line_indent = Pt(-11)
        p.paragraph_format.tab_stops.add_tab_stop(Pt(11))
        p.add_run(_cv_bullet_glyph() + "\t").font.color.rgb = RGBColor.from_string(Theme.teal[1:])
        p.add_run(str(text))

    doc.add_paragraph(model.get("name") or "CONFIRM BEFORE SUBMISSION", style="CV Name")
    doc.add_paragraph(model.get("headline") or "Medical Professional", style="CV Professional Title")
    contact_line = _cv_contact_line(model)
    if contact_line:
        doc.add_paragraph(contact_line, style="CV Contact")

    border(doc.paragraphs[-1], Theme.teal, 12)

    if model.get("profile"):
        add_section("PROFESSIONAL SUMMARY")
        doc.add_paragraph(model.get("profile") or "", style="CV Body")

    groups = _cv_expertise_groups(model)
    if groups:
        add_section("CORE PROFESSIONAL COMPETENCIES")
        for group in groups:
            p = doc.add_paragraph(style="CV Competency Group")
            label = str(group.get("group") or "")
            if label:
                run = p.add_run(f"{label}: ")
                run.bold = True
                run.font.color.rgb = RGBColor(12, 52, 66)
            p.add_run("\u00a0· ".join(str(item) for item in group.get("items") or []))

    experience = list(model.get("experience") or [])
    if experience:
        add_section("PROFESSIONAL EXPERIENCE")
        for item in experience:
            doc.add_paragraph(item.get("role") or "", style="CV Role")
            if item.get("org") or item.get("dates"):
                p = doc.add_paragraph(style="CV Meta")
                if item.get("org"):
                    p.add_run(str(item["org"])).bold = True
                if item.get("dates"):
                    p.add_run((" | " if item.get("org") else "") + str(item["dates"]))
            if item.get("loc"):
                doc.add_paragraph(str(item["loc"]), style="CV Meta")
            for bullet in item.get("bullets") or []:
                add_bullet(bullet)

    for title, values in [
        ("EDUCATION", model.get("education") or []),
        ("PROFESSIONAL REGISTRATION", model.get("registration") or []),
        ("MEDICAL EXIT EXAMINATION", model.get("exit_exam") or []),
        ("PROFESSIONAL TRAINING & CERTIFICATIONS", model.get("certifications") or []),
    ]:
        if values:
            add_section(title)
            # Mirrors the PDF: a single statement is set as a line, and only a
            # real list is bulleted.
            single = len(values) == 1
            for value in values:
                if single:
                    doc.add_paragraph(str(value), style="CV Body")
                else:
                    add_bullet(value)
    if model.get("languages"):
        add_section("LANGUAGES")
        language_line = "  |  ".join(f"{name}{(' — ' + level) if level else ''}" for name, level in model.get("languages") or [])
        doc.add_paragraph(language_line, style="CV Body")
    references = [str(item) for item in (model.get("references") or []) if str(item).strip()]
    if references:
        add_section("REFERENCES")
        for value in references:
            doc.add_paragraph(value, style="CV Body")

    # Footer: name on the left, a real page number on the right.
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.LEFT
    footer.paragraph_format.tab_stops.add_tab_stop(section.page_width - section.left_margin - section.right_margin, WD_TAB_ALIGNMENT.RIGHT)
    run = footer.add_run(str(model.get("name") or "CONFIRM BEFORE SUBMISSION"))
    run.font.size = Pt(7)
    run.font.color.rgb = RGBColor(102, 115, 122)
    page_run = footer.add_run("\tPage ")
    page_run.font.size = Pt(7)
    page_run.font.color.rgb = RGBColor(102, 115, 122)
    _docx_page_field(footer)
    for run in footer.runs:
        run.font.name = font
        run.font.size = Pt(7)
        run.font.color.rgb = RGBColor.from_string(Theme.muted[1:])
    border(footer, Theme.rule, 4)
    update = OxmlElement("w:updateFields")
    update.set(qn("w:val"), "true")
    doc.settings.element.append(update)
    doc.save(str(path))


# ---------------------------------------------------------------------------
# Cover letter renderers
# ---------------------------------------------------------------------------


def render_cover_letter_pdf(model: dict[str, Any], path: str | Path) -> None:
    """Render the cover letter with the same design system and auto-pagination.

    Content flows naturally across pages, so a longer verified letter can never
    place its signature above its own closing paragraphs.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

    serif, serif_bold, sans, sans_bold = _register_fonts()
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm,
        topMargin=14 * mm, bottomMargin=15 * mm,
        title=f"{model.get('name')} — Cover Letter",
        author=model.get("name") or "CONFIRM BEFORE SUBMISSION",
        subject="Application letter",
    )
    styles = getSampleStyleSheet()

    def esc(value: Any) -> str:
        import html

        return html.escape(str(value or ""))

    name_style = ParagraphStyle("CLName", parent=styles["Title"], fontName=serif_bold, fontSize=20, leading=23, textColor=colors.HexColor(Theme.deep), spaceAfter=1, alignment=0)
    headline_style = ParagraphStyle("CLHeadline", parent=styles["Normal"], fontName=sans, fontSize=10.2, leading=12.6, textColor=colors.HexColor(Theme.teal), spaceAfter=2)
    contact_style = ParagraphStyle("CLContact", parent=styles["Normal"], fontName=sans, fontSize=8.3, leading=10.6, textColor=colors.HexColor(Theme.muted), spaceAfter=6)
    target_style = ParagraphStyle("CLTarget", parent=styles["Normal"], fontName=sans_bold, fontSize=9.2, leading=11.6, textColor=colors.HexColor(Theme.deep), spaceAfter=1)
    recipient_style = ParagraphStyle("CLRecipient", parent=styles["Normal"], fontName=sans, fontSize=8.3, leading=10.6, textColor=colors.HexColor(Theme.muted), spaceAfter=8)
    section_style = ParagraphStyle("CLSection", parent=styles["Heading2"], fontName=sans_bold, fontSize=9.4, leading=11.4, textColor=colors.HexColor(Theme.deep), spaceBefore=4, spaceAfter=3)
    subject_style = ParagraphStyle("CLSubject", parent=styles["Normal"], fontName=sans_bold, fontSize=9.6, leading=12, textColor=colors.HexColor(Theme.ink), spaceAfter=8)
    body_style = ParagraphStyle("CLBody", parent=styles["Normal"], fontName=sans, fontSize=9.1, leading=12.4, textColor=colors.HexColor(Theme.ink), spaceAfter=6)
    bullet_style = ParagraphStyle("CLBullet", parent=body_style, leftIndent=12, firstLineIndent=-8, bulletIndent=0, spaceAfter=3, bulletFontName=sans, bulletFontSize=8.4, bulletColor=colors.HexColor(Theme.teal))
    signature_style = ParagraphStyle("CLSignature", parent=styles["Normal"], fontName=serif_bold, fontSize=12, leading=14, textColor=colors.HexColor(Theme.deep), spaceBefore=4)
    signature_meta_style = ParagraphStyle("CLSignatureMeta", parent=styles["Normal"], fontName=sans, fontSize=8.3, leading=10.4, textColor=colors.HexColor(Theme.muted), spaceAfter=1)

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor(Theme.rule))
        canvas.setLineWidth(0.5)
        canvas.line(20 * mm, 12 * mm, A4[0] - 20 * mm, 12 * mm)
        canvas.setFont(sans, 7)
        canvas.setFillColor(colors.HexColor(Theme.muted))
        canvas.drawString(20 * mm, 8 * mm, f"{model.get('name') or 'CONFIRM BEFORE SUBMISSION'} — Cover Letter")
        canvas.drawRightString(A4[0] - 20 * mm, 8 * mm, f"Page {document.page}")
        canvas.restoreState()

    story: list[Any] = [
        Paragraph(esc(model.get("name")), name_style),
        Paragraph(esc(model.get("headline") or "Application Letter"), headline_style),
    ]
    contact = model.get("contact") or {}
    contact_line = " | ".join(str(value) for value in [contact.get("location"), contact.get("phone"), contact.get("email")] if value)
    if contact_line:
        story.append(Paragraph(esc(contact_line), contact_style))
    story.append(HRFlowable(width="100%", thickness=0.9, color=colors.HexColor(Theme.gold), spaceBefore=1, spaceAfter=9))
    target_line = " — ".join(str(value) for value in [model.get("target_role"), model.get("target_org")] if value)
    if target_line:
        story.append(Paragraph(esc(target_line), target_style))
    recipient = f"To: Hiring Committee, {model.get('target_org')}" if model.get("target_org") else "To: Hiring Committee"
    if _reference_shown_in_heading(model):
        recipient += f" | Reference: {model.get('reference')}"
    story.append(Paragraph(esc(recipient), recipient_style))
    story.append(Paragraph("SUBJECT", section_style))
    story.append(Paragraph(esc(model.get("subject") or model.get("target_role") or "Application"), subject_style))
    for line in model.get("body_lines", []):
        if line.startswith("-"):
            story.append(Paragraph(esc(_clean_bullet(line)), bullet_style, bulletText="\u2022"))
        else:
            story.append(Paragraph(esc(line), body_style))
    signature = model.get("signature") or {}
    story.append(Spacer(1, 4))
    story.append(Paragraph("Sincerely,", body_style))
    story.append(Paragraph(esc(model.get("name") or signature.get("name") or "CONFIRM BEFORE SUBMISSION"), signature_style))
    if signature.get("title"):
        story.append(Paragraph(esc(signature["title"]), signature_meta_style))
    if signature.get("email"):
        story.append(Paragraph(esc(f"Email: {signature['email']}"), signature_meta_style))
    if signature.get("phone"):
        story.append(Paragraph(esc(f"Phone: {signature['phone']}"), signature_meta_style))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


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

    doc.add_paragraph(model.get("name") or "CONFIRM BEFORE SUBMISSION", style="JF Name")
    doc.add_paragraph(model.get("headline") or "Medical Professional", style="JF Title")
    contact = model.get("contact") or {}
    doc.add_paragraph(" | ".join([x for x in [contact.get("location"), contact.get("phone"), contact.get("email")] if x]), style="JF Contact")
    doc.add_paragraph(f"APPLICATION LETTER — {model.get('target_role')} — {model.get('target_org')}", style="JF Label")
    recipient = f"To: Hiring Committee, {model.get('target_org')}"
    if _reference_shown_in_heading(model):
        recipient += f" | Reference: {model.get('reference')}"
    doc.add_paragraph(recipient, style="JF Contact")
    doc.add_paragraph("SUBJECT", style="JF Section")
    doc.add_paragraph(model.get("subject") or model.get("target_role") or "Application", style="JF Section")
    for line in model.get("body_lines", []):
        if line.lower().startswith("subject:"):
            continue
        if line.startswith("-"):
            p = doc.add_paragraph(style="JF Body")
            p.paragraph_format.left_indent = Inches(0.22)
            p.paragraph_format.first_line_indent = Inches(-0.12)
            p.add_run("• " + _clean_bullet(line))
        else:
            doc.add_paragraph(line, style="JF Body")
    doc.add_paragraph("Sincerely,", style="JF Body")
    doc.add_paragraph((model.get("signature") or {}).get("name") or model.get("name") or "CONFIRM BEFORE SUBMISSION", style="JF Signature")
    signature = model.get("signature") or {}
    for value in [signature.get("title"), f"Email: {signature['email']}" if signature.get("email") else "", f"Phone: {signature['phone']}" if signature.get("phone") else ""]:
        if value:
            doc.add_paragraph(value, style="JF Contact")
    for section in doc.sections:
        f = section.footer.paragraphs[0]
        f.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = f.add_run(f"{model.get('name') or 'CONFIRM BEFORE SUBMISSION'} — Cover Letter")
        run.font.size = Pt(7)
        run.font.color.rgb = RGBColor(102, 115, 122)
    doc.save(str(path))
