"""Write per-message markdown files per the zkm messaging-spec."""

from __future__ import annotations

from pathlib import Path

import frontmatter

from .parse import ParsedMessage

PLUGIN_NAME = "zkm-eml"
PLUGIN_VERSION = "0.1.0"


def write_message_md(
    dest: Path,
    msg: ParsedMessage,
    thread_id: str,
    thread_path: str,
    direction: str,
    body: str,
    original_path: str | None,
) -> None:
    """Write (or overwrite) the markdown file for one message."""
    participants = _collect_participants(msg)

    meta: dict = {
        "source": PLUGIN_NAME,
        "date": msg.date.isoformat(timespec="seconds"),
        "tags": [],
        "sha256": msg.sha256,
        "processor": PLUGIN_NAME,
        "processor_version": PLUGIN_VERSION,
        # messaging-spec fields
        "message_id": msg.raw_message_id,
        "thread_id": thread_id,
        "thread": thread_path,
        "participants": participants,
        "direction": direction,
        "subject": msg.subject,
    }
    if msg.in_reply_to:
        meta["in_reply_to"] = f"<{msg.in_reply_to}>"
    if msg.references:
        meta["references"] = [f"<{r}>" for r in msg.references]
    if original_path:
        meta["original"] = original_path

    post = frontmatter.Post(body, **meta)
    dest.write_text(frontmatter.dumps(post), encoding="utf-8")


def _collect_participants(msg: ParsedMessage) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for addr in [msg.from_addr, *msg.to_addrs, *msg.cc_addrs]:
        if addr and addr not in seen:
            seen.add(addr)
            result.append(addr)
    return result
