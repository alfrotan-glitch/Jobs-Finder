"""Safe local email-client drafts with precisely the employer-required attachments.

Create a standards-compliant RFC 822 .eml that opens in the default Windows
email application with recipient, subject, body, and attached reviewed files.
Never authenticate, transmit, send, or mark an application as submitted.
"""

from __future__ import annotations

import os
import re
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path

from utils.medical_requirements import is_valid_email
from utils.paths import PROJECT_ROOT

MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
MAX_MESSAGE_BYTES = 22 * 1024 * 1024


class EmailDraftError(ValueError):
    pass


def _attachment_kinds(required: list[str]) -> tuple[bool, bool, list[str]]:
    """Translate requirements without inventing or quietly omitting extras."""
    cv = False
    cover = False
    other: list[str] = []
    for value in required:
        label = str(value).strip()
        lower = label.lower()
        if "cv" in lower or "resume" in lower:
            cv = True
        elif "cover letter" in lower or "application letter" in lower:
            cover = True
        elif label:
            other.append(label)
    return cv, cover, other


def build_email_draft(job: dict, *, project_root: Path = PROJECT_ROOT) -> tuple[str, bytes]:
    """Build an unsent MIME draft ONLY from an explicit valid email route.

    Other required documents (employer forms, IDs, approved referee files,
    additional certificates) are not synthesised. The user must supply them.
    """
    package = job.get("package") or {}
    if job.get("is_expired") or package.get("route_type") != "email":
        raise EmailDraftError("This posting has no active verified email application route.")
    if package.get("package_status") != "READY_FOR_REVIEW" or package.get("missing_items"):
        raise EmailDraftError("Complete the outstanding eligibility and document checks before opening the email draft.")
    draft = package.get("email_draft") or {}
    recipient = str(draft.get("to") or "").strip()
    if not is_valid_email(recipient) or "\n" in recipient or "\r" in recipient:
        raise EmailDraftError("The advertised application email address is not valid.")
    subject = str(draft.get("subject") or "").strip()
    body = str(draft.get("body") or "").strip()
    if not subject or any(c in subject for c in "\r\n") or not body:
        raise EmailDraftError("The application draft requires a valid subject and message.")
    paths = (job.get("documents") or {}).get("generated_paths") or {}
    required = package.get("required_documents_checklist") or []
    needs_cv, needs_cover, other = _attachment_kinds(required)
    if other:
        raise EmailDraftError(
            "This vacancy requests additional documents that need your review: "
            + "; ".join(other[:5])
            + ". Prepare those documents separately before applying."
        )
    if not needs_cv and not needs_cover:
        needs_cv = True
    attachments: list[tuple[str, bytes]] = []
    root = (project_root / "documents" / "applications").resolve()
    total = 0
    for kind, required_for_email in (("tailored_cv", needs_cv), ("cover_letter", needs_cover)):
        if not required_for_email:
            continue
        entry = paths.get(kind) or {}
        file_value = entry.get("pdf") if isinstance(entry, dict) else ""
        if not file_value:
            raise EmailDraftError(f"The requested {kind.replace('_', ' ')} PDF has not been generated.")
        path = Path(str(file_value)).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
            raise EmailDraftError("Application attachments must be existing, local, reviewed generated PDFs.")
        size = path.stat().st_size
        total += size
        if size < 100 or size > MAX_ATTACHMENT_BYTES or total > MAX_ATTACHMENT_BYTES:
            raise EmailDraftError("The attachment exceeds the safe email size limit or is empty.")
        data = path.read_bytes()
        if not data.startswith(b"%PDF-"):
            raise EmailDraftError("The attachment is not a real PDF.")
        attachments.append((path.name, data))
    if not attachments:
        raise EmailDraftError("No eligible employer-requested attachment is available.")
    message = EmailMessage(policy=SMTP)
    message["To"] = recipient
    message["Subject"] = subject
    # Intentionally NO From or Sender: the selected user's email client sets
    # the real authenticated sending account. Never spoof the profile address.
    message["X-Unsent"] = "1"
    message.set_content(body + "\n")
    for filename, data in attachments:
        message.add_attachment(data, maintype="application", subtype="pdf", filename=filename)
    result = message.as_bytes()
    if len(result) > MAX_MESSAGE_BYTES:
        raise EmailDraftError("The complete draft is too large for the email client.")
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "-", str(job.get("id") or "application")).strip("-")[:45]
    return f"Jobs-Finder-{safe_name or 'application'}-UNSENT.eml", result


def open_windows_email_draft(path: Path) -> None:
    """Launch a previously constructed EML in the registered Windows client.

    Windows may have no .eml association or may prompt for a mail app. Do not
    claim successful sending and never run a shell command with user data.
    """
    if os.name != "nt":
        raise EmailDraftError("Automatic email-client opening is supported on Windows only.")
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except OSError as exc:
        raise EmailDraftError(
            "Windows could not open the .eml draft. Download it and open in an email app such as Outlook."
        ) from exc
