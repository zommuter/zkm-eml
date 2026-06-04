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

from zkm.encoding import post_decode as _post_decode_shared
from charset_normalizer import from_bytes as _cn_from_bytes

def _magic_sniff(data: bytes, fallback_ct: str) -> str:
    """Detect MIME type from bytes via python-magic; fall back to declared type."""
    if not data:
        return fallback_ct
    try:
        import magic  # python-magic optional dep
        sniffed = magic.from_buffer(data[:4096], mime=True)
        return sniffed if sniffed else fallback_ct
    except Exception:  # ImportError or libmagic error
        return fallback_ct


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
    is_signature_part: bool = False  # PGP/MIME or S/MIME signature leaf — exclude from inbox fan-out


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
    signed: str | None = None       # "pgp-mime" | "smime" | None (Tier A)
    auth_results: list[dict] = field(default_factory=list)  # Tier B parsed auth headers


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

    plain_body, html_body, attachments, signed = _extract_parts(msg)
    # Mark which attachments are referenced by the HTML body (inline decoration)
    for att in attachments:
        if att.content_id:
            cid_bare = att.content_id.strip("<>")
            att.referenced_in_html = cid_bare in html_body or f"cid:{cid_bare}" in html_body

    auth_results = _parse_auth_headers(msg)

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
        signed=signed,
        auth_results=auth_results,
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

# Maps signature leaf content-type → signed enum value
_SIGNATURE_LEAF_TYPES: dict[str, str] = {
    "application/pgp-signature": "pgp-mime",
    "application/pkcs7-signature": "smime",
    "application/x-pkcs7-signature": "smime",
}


def _extract_parts(msg: EmailMessage) -> tuple[str, str, list[ParsedAttachment], str | None]:
    """Return (plain_text, html_text, attachments, signed_type)."""
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[ParsedAttachment] = []
    seen_filenames: set[str] = set()
    signed_type: str | None = None

    for idx, part in enumerate(msg.walk()):
        content_type = part.get_content_type()
        disposition = part.get_content_disposition() or ""

        if content_type in _MULTIPART_TYPES:
            # Detect signed container by protocol parameter (more reliable than leaf type)
            if content_type == "multipart/signed":
                protocol_raw = part.get_param("protocol") or ""
                # get_param may return (charset, language, value) for RFC 2231 encoded params
                if isinstance(protocol_raw, tuple):
                    protocol = (protocol_raw[2] or "").lower()
                else:
                    protocol = str(protocol_raw).lower()
                if "pgp-signature" in protocol:
                    signed_type = "pgp-mime"
                elif "pkcs7-signature" in protocol or "smime" in protocol:
                    signed_type = "smime"
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

            # Detect signature leaf (fallback when protocol param was absent)
            is_sig = content_type in _SIGNATURE_LEAF_TYPES
            if is_sig and signed_type is None:
                signed_type = _SIGNATURE_LEAF_TYPES[content_type]

            raw_filename_raw = part.get_filename() or ""
            raw_filename = _decode_header_str(raw_filename_raw)
            # When no filename is declared, sniff the actual type for a better extension.
            effective_ct = (
                _magic_sniff(raw_payload, content_type)
                if not raw_filename
                else content_type
            )
            ext = mimetypes.guess_extension(effective_ct.split(";")[0].strip()) or ""
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
                is_signature_part=is_sig,
            ))

    plain = "\n\n".join(plain_parts).strip()
    html = "\n\n".join(html_parts).strip()
    return plain, html, attachments, signed_type


def _parse_auth_results_value(header_val: str) -> dict | None:
    """Parse one Authentication-Results header value into a structured dict."""
    parts = [p.strip() for p in header_val.split(";")]
    if not parts or not parts[0]:
        return None
    record: dict = {
        "source": "Authentication-Results",
        "verified_by": parts[0].strip(),
    }
    for token in parts[1:]:
        token = token.strip()
        if not token:
            continue
        m = re.match(r"(\w+)=(\w+)", token)
        if m:
            method = m.group(1).lower()
            verdict = m.group(2).lower()
            if method in ("dkim", "spf", "dmarc", "arc", "bimi"):
                record[method] = verdict
    return record


def _parse_auth_headers(msg: EmailMessage) -> list[dict]:
    """Extract structured auth records from Authentication-Results, DKIM-Signature, ARC-*, X-Pm-* headers."""
    records: list[dict] = []

    for val in msg.get_all("Authentication-Results") or []:
        rec = _parse_auth_results_value(val)
        if rec is not None:
            records.append(rec)

    for val in msg.get_all("ARC-Authentication-Results") or []:
        # ARC headers begin with "i=N; authserv-id; ..."
        stripped = re.sub(r"^i=\d+;\s*", "", val.strip())
        arc_rec = _parse_auth_results_value(stripped)
        if arc_rec is not None:
            arc_rec["source"] = "ARC-Authentication-Results"
            instance_m = re.match(r"i=(\d+)", val.strip())
            if instance_m:
                arc_rec["instance"] = int(instance_m.group(1))
            records.append(arc_rec)

    for val in msg.get_all("DKIM-Signature") or []:
        dkim_rec: dict = {"source": "DKIM-Signature"}
        for tag in val.split(";"):
            tag = tag.strip()
            if "=" not in tag:
                continue
            k, _, v = tag.partition("=")
            k = k.strip().lower()
            if k == "d":
                dkim_rec["domain"] = v.strip()
            elif k == "s":
                dkim_rec["selector"] = v.strip()
            elif k == "a":
                dkim_rec["algorithm"] = v.strip()
        if "domain" in dkim_rec or "selector" in dkim_rec:
            records.append(dkim_rec)

    # Proton-specific headers (X-Pm-*)
    for header in ("X-Pm-Spamscore", "X-Pm-Message-Id", "X-Pm-Recipient-Authentication"):
        for val in msg.get_all(header) or []:
            records.append({"source": header, "value": val.strip()})

    return records


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
    return _post_decode_shared(text)


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
