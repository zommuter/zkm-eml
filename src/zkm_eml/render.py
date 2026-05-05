"""Render a ParsedMessage body to markdown. v0.1: no quote stripping."""

from __future__ import annotations

from .parse import ParsedMessage


def render_body(msg: ParsedMessage) -> str:
    """
    Return the markdown body for a message.

    Preference order:
      1. Plaintext body (already near-markdown; just returned as-is)
      2. HTML body converted via markdownify
      3. Empty string if neither is present
    """
    if msg.plain_body.strip():
        return msg.plain_body.strip()
    if msg.html_body.strip():
        return _html_to_markdown(msg.html_body)
    return ""


def _html_to_markdown(html: str) -> str:
    try:
        from markdownify import markdownify
        return markdownify(html, heading_style="ATX", bullets="-").strip()
    except ImportError:
        # Graceful degradation: strip tags manually
        import re
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r" {2,}", " ", text)
        return text.strip()
