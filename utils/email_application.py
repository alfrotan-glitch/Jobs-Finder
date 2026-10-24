"""Local, reviewable vacancy-accurate email composition with real attachments.

A browser mailto: link cannot attach files. We therefore create a standard
RFC 5322 .eml MIME *draft* for the applicant's desktop mail program and leave
the actual Send click to the applicant. This module NEVER sends mail.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
from typing import Any

from utils.medical_requirements import canonical_source_fields, is_valid_email
from utils.paths import PROJECT_ROOT

MAX_EMAIL_ATTACHMENT_BYTES = 12 * 1024 * 1024
MAX_TOTAL_EMAIL_BYTES = 22 * 1024 * 1024
MAX_EMAIL_ATTACHMENTS = 5


class EmailCompositionError(ValueError):
    """The selected vacancy has no safe, complete email draft."""


def _required_artifact_types(checklist: list[str]) -> tuple[bool, bool, list[str]]:
    """Return attachment requirements; never infer an optional extra document.

    Lack of an explicit CV request is *not* permission to omit the essential
    CV: a standalone email application defaults to CV only.
    """
    wants_cv = False
    wants_cover = False
    manual: list[str] = []
    for raw in checklist:
        text = str(raw or "").strip()
        lower = text.lower()
        if "only if" in lower or "if later" in lower or "if selected" in lower or "if requested" in lower:
            continue
        contains_cv = re.search(r"\b(cv|resume|curriculum vitae)\b", lower) is not None
        contains_cover = "cover letter" in lower or "application letter" in lower
        if contains_cv:
            wants_cv = True
        if contains_cover:
            wants_cover = True
        if not contains_cv and not contains_cover and text:
            # Employer-supplied forms, credential scans, references and IDs
            # must NOT silently be replaced by generated fake attachments.
            manual.append(text)
    if not wants_cv and not wants_cover:
        wants_cv = True
    return wants_cv, wants_cover, manual


def _local_document_path(value: str, root: Path) -> Path:
    path = Path(value)
    resolved = path.resolve()
    allowed = (root / "documents" / "applications").resolve()
    if not resolved.is_relative_to(allowed) or path.is_symlink() or not resolved.is_file():
        raise EmailCompositionError("The generated document is missing or outside the private application folder.")
    if resolved.suffix.lower() != ".pdf":
        raise EmailCompositionError("An employer-facing PDF is required; review DOCX separately.")
    return resolved


def compose_application_email(job: dict[str, Any], *, root: Path = PROJECT_ROOT) -> tuple[str, bytes, list[str]]:
    """Create an attachment-complete .eml only for a prepared email-route job.

    Does not send, mark applied or modify application records. Email clients
    vary: some open .eml as a message viewer rather than an editable draft.
    """
    if job.get("status") == "APPLIED_MANUALLY":
        raise EmailCompositionError("This application is already recorded as submitted.")
    if job.get("is_expired"):
        raise EmailCompositionError("The vacancy deadline has passed; confirm any reopening with the employer.")

    route = canonical_source_fields(job)
    if route.get("application_method") != "EMAIL" or not route.get("apply_email"):
        raise EmailCompositionError("This posting requires an online form or its email destination is unavailable.")

    package = job.get("package") or {}
    if package.get("package_status") != "READY_FOR_REVIEW":
        raise EmailCompositionError("The package still needs verified information or required attachments. Review the checklist before applying.")
    draft = package.get("email_draft") or {}
    to = str(draft.get("to") or "").strip()
    if to.lower() != str(route["apply_email"]).lower() or not is_valid_email(to):
        raise EmailCompositionError("The saved email draft does not match the posting's current application destination.")
    subject = str(draft.get("subject") or "").strip()
    body = str(draft.get("body") or "").strip()
    if not subject or not body or any(c in subject for c in "\r\n") or len(subject) > 255:
        raise EmailCompositionError("The email subject or body needs review.")

    checklist = package.get("required_documents_checklist") or []
    if not isinstance(checklist, list):
        raise EmailCompositionError("The vacancy document checklist is invalid.")
    cv_required, cover_required, manual = _required_artifact_types(checklist)
    if manual:
        raise EmailCompositionError("Employer-required documents still need to be supplied: " + ", ".join(manual[:3]))

    doc_tree = (job.get("documents") or {}).get("generated_paths") or {}
    attachments: list[Path] = []
    for label, needed in (("tailored_cv", cv_required), ("cover_letter", cover_required)):
        if not needed:
            continue
        entry = doc_tree.get(label) or {}
        if not isinstance(entry, dict) or not entry.get("pdf"):
            raise EmailCompositionError("A required reviewed PDF is missing: " + label.replace("_", " "))
        attachments.append(_local_document_path(str(entry["pdf"]), root))
    if not attachments or len(attachments) > MAX_EMAIL_ATTACHMENTS:
        raise EmailCompositionError("No valid attachment set is available.")
    size = sum(path.stat().st_size for path in attachments)
    if size > MAX_TOTAL_EMAIL_BYTES or any(path.stat().st_size > MAX_EMAIL_ATTACHMENT_BYTES for path in attachments):
        raise EmailCompositionError("Attachments exceed safe email size limits.")

    message = EmailMessage(policy=SMTP)
    message["To"] = to
    message["Subject"] = subject
    # Do not put the unverified sender into From, or impersonate an address.
    # The applicant's email client supplies its actual authorized account.
    message.set_content(body + "\n")
    for path in attachments:
        message.add_attachment(path.read_bytes(), maintype="application", subtype="pdf", filename=path.name)
    if not message.is_multipart():
        raise EmailCompositionError("The email was not prepared with attachments.")
    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(job.get("id") or "job"))[:55]
    return f"Application_{safe_id}.eml", message.as_bytes(), [path.name for path in attachments]


def open_classic_outlook_composer(job: dict[str, Any], *, root: Path = PROJECT_ROOT) -> bool:
    """Display an unsent, fully attached compose window in classic Outlook.

    This is an optional Windows convenience. Modern Outlook/new Outlook,
    browser Gmail and other clients may not expose the classic Outlook COM
    API, in which case the caller should use the portable .eml download.
    Neither this function nor the PowerShell script ever invokes Send.
    """
    _, raw, names = compose_application_email(job, root=root)
    if sys.platform != "win32":
        return False
    executable = shutil.which("powershell.exe")
    if not executable:
        return False

    # Build the path set entirely from the same reviewed/generated PDFs
    # verified by compose_application_email; never accept a browser-supplied
    # filesystem path or untrusted address.
    generated = (job.get("documents") or {}).get("generated_paths") or {}
    paths: list[str] = []
    for label in ("tailored_cv", "cover_letter"):
        entry = generated.get(label) or {}
        if not isinstance(entry, dict) or not entry.get("pdf"):
            continue
        path = _local_document_path(str(entry["pdf"]), root)
        if path.name in names:
            paths.append(str(path))
    if len(paths) != len(names):
        raise EmailCompositionError("The reviewed attachment files are incomplete.")

    from email import policy
    from email.parser import BytesParser

    message = BytesParser(policy=policy.default).parsebytes(raw)
    body = message.get_body(preferencelist=("plain",)).get_content()
    payload = {
        "to": str(message["To"]),
        "subject": str(message["Subject"]),
        "body": body,
        "attachments": paths,
    }
    # JSON over standard input, never embedded into executable PowerShell
    # code: vacancy strings cannot inject commands. COM.Display() does not
    # dispatch email. The actual user presses Send from their Outlook account.
    script = r"""
$ErrorActionPreference = 'Stop'
try {
    $p = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $app = New-Object -ComObject Outlook.Application
    $draft = $app.CreateItem(0)
    $draft.To = [string]$p.to
    $draft.Subject = [string]$p.subject
    $draft.Body = [string]$p.body
    foreach ($file in $p.attachments) {
        [void]$draft.Attachments.Add([string]$file)
    }
    $draft.Display()
    Write-Output 'UNSENT_COMPOSE_OPENED'
} catch {
    exit 21
}
"""
    try:
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-Command", script],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "UNSENT_COMPOSE_OPENED" in result.stdout
