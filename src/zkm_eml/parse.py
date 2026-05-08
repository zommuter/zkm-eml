"""Parse a raw .eml file into a structured dataclass."""

from __future__ import annotations

import email
import email.header
import email.policy
import hashlib
import mimetypes
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

import ftfy
from charset_normalizer import from_bytes as _cn_from_bytes


from .naming import sanitize_filename


@dataclass
class ParsedAttachment:
    filename: str              # sanitized, NFC-normalized, collision-safe within the message
    filename_raw: str          # pre-sanitize value from get_filename() for forensic re-decode
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
    subject = _decode_header_str(msg.get("Subject")) or "(no subject)"

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


def _decode_header_str(value: str | None) -> str:
    """Defensive RFC 2047 decode — idempotent on already-decoded strings."""
    if not value:
        return ""
    try:
        decoded = str(email.header.make_header(email.header.decode_header(value)))
    except Exception:
        decoded = str(value)
    return _post_decode(decoded)


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


def _format_addr_list(header_val: str) -> list[str]:
    if not header_val:
        return []
    out = []
    for raw_name, addr in getaddresses([header_val]):
        name = _decode_header_str(raw_name).strip()
        addr = addr.strip()
        if not addr and not name:
            continue
        out.append(f"{name} <{addr}>" if name else addr)
    return out


def _format_addr(header_val: str) -> str:
    addrs = _format_addr_list(header_val)
    return addrs[0] if addrs else ""


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

            raw_filename_raw = part.get_filename() or ""
            raw_filename = _decode_header_str(raw_filename_raw)
            ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
            fallback = f"part-{idx}{ext}"
            base_name = unicodedata.normalize("NFC", sanitize_filename(raw_filename, fallback))
            # Collision-suffix within this message
            filename = _unique_filename(base_name, seen_filenames)
            seen_filenames.add(filename)

            cid = (part.get("Content-Id") or "").strip().strip("<>") or None
            is_inline = disposition == "inline"
            sha = hashlib.sha256(raw_payload).hexdigest()

            attachments.append(ParsedAttachment(
                filename=filename,
                filename_raw=raw_filename_raw,
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


_PERMISSIVE_CODECS = frozenset({"latin1", "iso88591", "cp1252", "windows1252"})


def _try_strict_decode(payload: bytes, declared: str | None, content_type: str) -> str | None:
    """Try declared charset first, then utf-8 as a strict fallback.

    Permissive codecs (latin-1, cp1252) are trusted when explicitly declared by the
    sender, but never added as implicit fallbacks — they accept every byte sequence
    and would mask mis-declared charsets.  When the declared codec is permissive,
    try utf-8 first; if utf-8 fails, the declared permissive codec is the tiebreaker.
    """
    candidates: list[str] = []

    # Discover declared charset
    if declared:
        declared_norm = declared.lower().replace("-", "").replace("_", "")
        if declared_norm in _PERMISSIVE_CODECS:
            # Permissive declared: try utf-8 first, then trust the declaration
            candidates = ["utf-8", declared]
        else:
            candidates = [declared]
    elif content_type == "text/html":
        m = re.search(rb'charset=["\']?([\w\-]+)', payload[:1024], re.IGNORECASE)
        if m:
            candidates.append(m.group(1).decode("ascii", errors="ignore"))

    # Always try utf-8 as a strict fallback (skip if already in list)
    if "utf-8" not in [c.lower().replace("-", "") for c in candidates]:
        candidates.append("utf-8")

    for cs in candidates:
        try:
            return payload.decode(cs)
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def _detect_decode(payload: bytes) -> str | None:
    """Use charset-normalizer to detect the encoding and decode."""
    result = _cn_from_bytes(payload).best()
    if result is None:
        return None
    return str(result)


def _post_decode(text: str) -> str:
    """Strip BOM, repair mojibake with ftfy, NFC-normalize."""
    text = text.lstrip("﻿")  # UTF-8/UTF-16 BOM
    text = ftfy.fix_text(
        text,
        uncurl_quotes=False,
        fix_line_breaks=False,
        fix_latin_ligatures=False,
        fix_character_width=False,
        normalization="NFC",
    )
    return text


def _decode_part(part: EmailMessage) -> str:
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    declared = part.get_content_charset()

    text = _try_strict_decode(payload, declared, part.get_content_type())
    if text is None:
        text = _detect_decode(payload)
    if text is None:
        text = payload.decode("utf-8", errors="replace")

    return _post_decode(text)
