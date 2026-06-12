"""Thread-ID derivation and thread-tree construction from RFC 5322 References chains."""

from __future__ import annotations

import hashlib


def thread_id_for(
    message_id: str,
    references: list[str],
    *,
    in_reply_to: str | None = None,
) -> str:
    """
    Return a stable 16-char hex thread ID.

    Thread root = oldest entry in the References chain; if References is empty,
    fall back to in_reply_to (common for webmail/mobile clients that omit
    References); finally fall back to the message's own message_id. This is
    stable: re-importing the same message always produces the same thread_id.
    """
    root = references[0] if references else (in_reply_to or message_id)
    return hashlib.sha256(root.encode()).hexdigest()[:16]
