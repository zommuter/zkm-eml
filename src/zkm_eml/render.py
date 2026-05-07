"""Render a ParsedMessage body to markdown."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .parse import ParsedMessage
from .quote_strip import strip_full_quote


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
