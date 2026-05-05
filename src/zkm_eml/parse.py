"""Parse a raw .eml file into a structured dataclass."""

from __future__ import annotations

import email
import email.headerregistry
import email.policy
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path


@dataclass
class ParsedMessage:
    message_id: str          # RFC 5322 Message-ID, angle brackets stripped
    raw_message_id: str      # original header value (with angle brackets)
    in_reply_to: str | None  # parent Message-ID (angle brackets stripped), or None
    references: list[str]    # ancestor chain, oldest first (angle brackets stripped)
    date: datetime           # UTC-normalised send time
    subject: str
    from_addr: str           # "Name <addr>" or bare address
    to_addrs: list[str]
    cc_addrs: list[str]
    plain_body: str
    html_body: str
    has_attachments: bool
    sha256: str              # sha256 of raw .eml bytes
    source_path: Path        # original file path


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
    to_addrs = _format_addr_list(msg.get("To") or "")
    cc_addrs = _format_addr_list(msg.get("Cc") or "")

    plain_body, html_body, has_attachments = _extract_bodies(msg)

    return ParsedMessage(
        message_id=message_id,
        raw_message_id=raw_mid or f"<{message_id}>",
        in_reply_to=in_reply_to,
        references=references,
        date=date,
        subject=subject,
        from_addr=from_addr,
        to_addrs=to_addrs,
        cc_addrs=cc_addrs,
        plain_body=plain_body,
        html_body=html_body,
        has_attachments=has_attachments,
        sha256=sha,
        source_path=path,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_angles(s: str) -> str:
    """Remove surrounding angle brackets and whitespace from a Message-ID."""
    return s.strip().strip("<>").strip()


def _synthetic_id(raw: bytes) -> str:
    """Synthesize a stable Message-ID from header bytes when none is present."""
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
    """Return 'Display Name <addr@example.com>' or bare address."""
    if not header_val:
        return ""
    try:
        addr = email.headerregistry.Address(addr_spec=header_val.strip())
        if addr.display_name:
            return f"{addr.display_name} <{addr.addr_spec}>"
        return addr.addr_spec
    except Exception:
        # Fall back to raw value
        return header_val.strip()


def _format_addr_list(header_val: str) -> list[str]:
    if not header_val:
        return []
    # Split on comma, format each
    results = []
    for part in re.split(r",\s*", header_val.strip()):
        part = part.strip()
        if part:
            results.append(_format_addr(part))
    return results


def _extract_bodies(msg: EmailMessage) -> tuple[str, str, bool]:
    """Return (plain_text, html_text, has_attachments)."""
    plain_parts: list[str] = []
    html_parts: list[str] = []
    has_attachments = False

    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = part.get_content_disposition() or ""

        if disposition == "attachment":
            has_attachments = True
            continue

        if content_type == "text/plain":
            payload = _decode_part(part)
            if payload:
                plain_parts.append(payload)
        elif content_type == "text/html":
            payload = _decode_part(part)
            if payload:
                html_parts.append(payload)
        elif content_type not in ("multipart/alternative", "multipart/mixed",
                                  "multipart/related", "multipart/signed",
                                  "multipart/encrypted"):
            # Non-text, non-multipart, non-attachment → implicit attachment
            if part.get_filename():
                has_attachments = True

    plain = "\n\n".join(plain_parts).strip()
    html = "\n\n".join(html_parts).strip()
    return plain, html, has_attachments


def _decode_part(part: EmailMessage) -> str:
    try:
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            return ""
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    except Exception:
        return ""
