"""Render a ParsedMessage body to markdown."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .parse import ParsedMessage
from .quote_strip import strip_full_quote

# ---------------------------------------------------------------------------
# Body section detection (signature + salutation) — used for γ-schema scopes
# ---------------------------------------------------------------------------

# RFC 3676 "-- " delimiter and common plain-text variants
_RE_SIG_HARD_SEP = re.compile(r"^--\s*$")
_RE_SIG_DASH_SEP = re.compile(r"^-{3,}\s*$")

# Common English + German sign-off phrases (line may end with comma/period)
_RE_SIG_SIGNOFF = re.compile(
    r"^(?:Best(?: regards?)?|Kind regards?|Warm regards?|Regards?|Cheers?|"
    r"Sincerely|Thanks?|Thank you|Yours(?: truly| sincerely)?|Cordially|"
    r"Mit (?:freundlichen?|besten?|herzlichen?) Grüsse?n?|"
    r"Freundliche Grüsse?|Viele (?:Grüsse?|liebe Grüsse?)|"
    r"Herzliche Grüsse?|Beste Grüsse?|Liebe Grüsse?|"
    r"Mit freundlichem Gruss|Grüsse?)[,.]?\s*$",
    re.IGNORECASE,
)

# Common English + German greeting patterns (line must START with one of these)
_RE_SALUTATION = re.compile(
    r"^(?:Dear|Hallo|Hi|Hey|Sehr geehrte(?:r|n|s)?|Guten (?:Tag|Morgen|Abend)|"
    r"Liebe(?:r|s)?|Good (?:morning|afternoon|evening))\b",
    re.IGNORECASE,
)


def split_body_sections(body: str) -> tuple[str | None, str | None]:
    """Detect salutation and signature blocks in a rendered email body.

    Returns ``(salutation_block, signature_block)``.  Either may be ``None``
    when not detected.  Detection is conservative — false negatives are
    preferred over false positives.

    The search window for signatures is the last 50 % of the body to avoid
    matching embedded `--` separators in old quoted content.
    """
    lines = body.splitlines()
    n = len(lines)

    # --- Signature ---
    sig_start: int | None = None
    search_from = max(0, n // 2)
    for i in range(search_from, n):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if _RE_SIG_HARD_SEP.match(stripped) or _RE_SIG_DASH_SEP.match(stripped):
            sig_start = i + 1   # content after the separator line
            break
        if _RE_SIG_SIGNOFF.match(stripped):
            sig_start = i       # include the sign-off line itself
            break

    signature_block: str | None = None
    if sig_start is not None:
        sig_text = "\n".join(lines[sig_start:]).strip()
        if sig_text:
            signature_block = sig_text

    # --- Salutation ---
    salutation_block: str | None = None
    first_nb = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if first_nb is not None and _RE_SALUTATION.match(lines[first_nb].strip()):
        # Include up to 2 additional continuation lines (e.g. "Dear\nJohn,")
        end = min(first_nb + 3, n)
        salutation_block = "\n".join(lines[first_nb:end]).strip()

    return salutation_block, signature_block


@dataclass
class ParentInfo:
    md_path: Path
    plain_body: str   # raw body text for quote-match comparison
    subject: str


def render_body(
    msg: ParsedMessage,
    parent_lookup: Callable[[str], ParentInfo | None] | None = None,
    dest: Path | None = None,
) -> str:
    """Return the markdown body for a message.

    Preference order:
      1. Plaintext body (returned as-is after optional quote stripping)
      2. HTML body converted via markdownify
      3. Empty string if neither is present

    When parent_lookup and dest are both provided, a matching tail-quote block
    is collapsed to a single link line referencing the parent message.
    """
    body = _select_body(msg)
    if parent_lookup is None or dest is None or not body:
        return body

    parent = _resolve_parent(msg, parent_lookup)
    if parent is None:
        return body

    rel = os.path.relpath(parent.md_path, dest.parent)
    md_link = f"[{parent.subject}]({rel})"
    return strip_full_quote(body, parent.plain_body, md_link)


def html_to_markdown(html: str) -> str:
    return _html_to_markdown(html)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _select_body(msg: ParsedMessage) -> str:
    if msg.plain_body.strip():
        return msg.plain_body.strip()
    if msg.html_body.strip():
        return _html_to_markdown(msg.html_body)
    return ""


def _resolve_parent(
    msg: ParsedMessage,
    parent_lookup: Callable[[str], ParentInfo | None],
) -> ParentInfo | None:
    candidates: list[str] = []
    if msg.in_reply_to:
        candidates.append(msg.in_reply_to)
    if msg.references:
        last = msg.references[-1]
        if last not in candidates:
            candidates.append(last)
    for mid in candidates:
        info = parent_lookup(mid)
        if info is not None:
            return info
    return None


def _html_to_markdown(html: str) -> str:
    try:
        from markdownify import markdownify
        return markdownify(html, heading_style="ATX", bullets="-").strip()
    except ImportError:
        import re
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r" {2,}", " ", text)
        return text.strip()
