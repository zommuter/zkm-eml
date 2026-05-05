"""Thread-ID derivation and thread-tree construction from RFC 5322 References chains."""

from __future__ import annotations

import hashlib


def thread_id_for(message_id: str, references: list[str]) -> str:
    """
    Return a stable 16-char hex thread ID.

    Thread root = oldest entry in the References chain, or the message's own
    message_id if References is empty. This is stable: re-importing the same
    message always produces the same thread_id.
    """
    root = references[0] if references else message_id
    return hashlib.sha256(root.encode()).hexdigest()[:16]
