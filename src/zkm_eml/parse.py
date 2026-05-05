"""Parse a raw .eml file into a structured dataclass."""

from __future__ import annotations

import email
import email.headerregistry
import email.policy
import hashlib
import mimetypes
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path

from .naming import sanitize_filename


@dataclass
class ParsedAttachment:
    filename: str              # sanitized, collision-safe within the message
    content_type: str          # e.g. "application/pdf"
    content_id: str | None     # cid: reference if present
    is_inline: bool            # Content-Disposition: inline
    referenced_in_html: bool   # cid: appears inside html_body
    size: int                  # decoded byte length
    sha256: str                # sha256 of decoded payload
    payload: bytes             # decoded content
    part_index: int            # walk-order index for stub correlation


@dataclass
class ParsedMessage:
    message_id: str          # RFC 5322 Message-ID, angle brackets stripped
    raw_message_id: str      # original header value (with angle brackets)
    in_reply_to: str | None  # parent Message-ID (angle brackets stripped), or None
    references: list[str]    # ancestor chain, oldest first (angle brackets stripped)
    date: datetime           # UTC-normalised send time
    subject: str
    from_addr: str           # "Name <addr>" or bare address
    reply_to: str | None     # "Name <addr>" or bare address, or None
    to_addrs: list[str]
    cc_addrs: list[str]
    bcc_addrs: list[str]     # usually only present in outgoing/Sent mail
    plain_body: str
    html_body: str
    has_attachments: bool
    sha256: str              # sha256 of raw .eml bytes
    source_path: Path        # original file path
    attachments: list[ParsedAttachment] = field(default_factory=list)


def parse_eml(path: Path) -> ParsedMessage:
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()

    msg: EmailMessage = email.message_from_bytes(raw, policy=email.policy.default)  # type: ignore[assignment]

    raw_mid = (msg.get("Message-ID") or "").strip()
    message_id = _strip_angles(raw_mid) or _synthetic_id(raw)

    raw_irt = (msg.get("In-Reply-To") or "").strip()
    in_reply_to = _strip_angles(raw_irt) or None

    raw_refs = (msg.get("References") or "").strip()
    references = [_strip_angles(r) for r in raw_refs.split() if r.strip()] if raw_refs else []

    date = _parse_date(msg.get("Date") or "")
    subject = str(msg.get("Subject") or "(no subject)").strip()

    from_addr = _format_addr(msg.get("From") or "")
    reply_to_raw = (msg.get("Reply-To") or "").strip()
    reply_to = _format_addr(reply_to_raw) if reply_to_raw else None
    to_addrs = _format_addr_list(msg.get("To") or "")
    cc_addrs = _format_addr_list(msg.get("Cc") or "")
    bcc_addrs = _format_addr_list(msg.get("Bcc") or "")

    plain_body, html_body, attachments = _extract_parts(msg)
    # Mark which attachments are referenced by the HTML body (inline decoration)
    for att in attachments:
        if att.content_id:
            cid_bare = att.content_id.strip("<>")
            att.referenced_in_html = cid_bare in html_body or f"cid:{cid_bare}" in html_body

    return ParsedMessage(
        message_id=message_id,
        raw_message_id=raw_mid or f"<{message_id}>",
        in_reply_to=in_reply_to,
        references=references,
        date=date,
        subject=subject,
        from_addr=from_addr,
        reply_to=reply_to,
        to_addrs=to_addrs,
        cc_addrs=cc_addrs,
        bcc_addrs=bcc_addrs,
        plain_body=plain_body,
        html_body=html_body,
        has_attachments=bool(attachments),
        sha256=sha,
        source_path=path,
        attachments=attachments,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_angles(s: str) -> str:
    return s.strip().strip("<>").strip()


def _synthetic_id(raw: bytes) -> str:
    return f"synthetic-{hashlib.sha256(raw[:4096]).hexdigest()[:32]}"


def _parse_date(date_str: str) -> datetime:
    if not date_str:
        return datetime.now(tz=timezone.utc)
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(tz=timezone.utc)


def _format_addr(header_val: str) -> str:
    if not header_val:
        return ""
    try:
        addr = email.headerregistry.Address(addr_spec=header_val.strip())
        if addr.display_name:
            return f"{addr.display_name} <{addr.addr_spec}>"
        return addr.addr_spec
    except Exception:
        return header_val.strip()


def _format_addr_list(header_val: str) -> list[str]:
    if not header_val:
        return []
    results = []
    for part in re.split(r",\s*", header_val.strip()):
        part = part.strip()
        if part:
            results.append(_format_addr(part))
    return results


_MULTIPART_TYPES = frozenset({
    "multipart/alternative", "multipart/mixed",
    "multipart/related", "multipart/signed",
    "multipart/encrypted",
})


def _extract_parts(msg: EmailMessage) -> tuple[str, str, list[ParsedAttachment]]:
    """Return (plain_text, html_text, attachments)."""
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[ParsedAttachment] = []
    seen_filenames: set[str] = set()

    for idx, part in enumerate(msg.walk()):
        content_type = part.get_content_type()
        disposition = part.get_content_disposition() or ""

        if content_type in _MULTIPART_TYPES:
            continue

        if content_type == "text/plain" and disposition != "attachment":
            payload = _decode_part(part)
            if payload:
                plain_parts.append(payload)
        elif content_type == "text/html" and disposition != "attachment":
            payload = _decode_part(part)
            if payload:
                html_parts.append(payload)
        else:
            raw_payload = part.get_payload(decode=True)
            if not isinstance(raw_payload, bytes):
                continue
            if not raw_payload:
                continue

            raw_filename = part.get_filename() or ""
            ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
            fallback = f"part-{idx}{ext}"
            base_name = sanitize_filename(raw_filename, fallback)
            # Collision-suffix within this message
            filename = _unique_filename(base_name, seen_filenames)
            seen_filenames.add(filename)

            cid = (part.get("Content-Id") or "").strip().strip("<>") or None
            is_inline = disposition == "inline"
            sha = hashlib.sha256(raw_payload).hexdigest()

            attachments.append(ParsedAttachment(
                filename=filename,
                content_type=content_type,
                content_id=cid,
                is_inline=is_inline,
                referenced_in_html=False,  # filled in by caller
                size=len(raw_payload),
                sha256=sha,
                payload=raw_payload,
                part_index=idx,
            ))

    plain = "\n\n".join(plain_parts).strip()
    html = "\n\n".join(html_parts).strip()
    return plain, html, attachments


def _unique_filename(name: str, seen: set[str]) -> str:
    if name not in seen:
        return name
    stem, _, ext = name.rpartition(".")
    if not stem:
        stem, ext = name, ""
    else:
        ext = f".{ext}"
    i = 1
    while True:
        candidate = f"{stem}_{i}{ext}"
        if candidate not in seen:
            return candidate
        i += 1


def _decode_part(part: EmailMessage) -> str:
    try:
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            return ""
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    except Exception:
        return ""
