"""Write per-message markdown files per the zkm messaging-spec."""

from __future__ import annotations

from pathlib import Path

import frontmatter

from .parse import ParsedAttachment, ParsedMessage

PLUGIN_NAME = "zkm-eml"
PLUGIN_VERSION = "0.2.1"


def write_message_md(
    dest: Path,
    msg: ParsedMessage,
    thread_id: str,
    thread_path: str,
    direction: str,
    body: str,
    original_path: str | None,
    attachment_meta: list[tuple[ParsedAttachment, str]] | None = None,
    source_path_rel_home: str | None = None,
    source_repo_commit: str | None = None,
    source_blob: str | None = None,
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
    if source_path_rel_home:
        meta["source_path"] = source_path_rel_home
    if source_repo_commit:
        meta["source_repo_commit"] = source_repo_commit
    if source_blob:
        meta["source_blob"] = source_blob
    if attachment_meta:
        meta["attachments"] = [
            _att_entry(att, rel_path)
            for att, rel_path in attachment_meta
        ]

    dest.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(body, **meta)
    dest.write_text(frontmatter.dumps(post), encoding="utf-8")


def _att_entry(att: ParsedAttachment, rel_path: str) -> dict:
    sha = att.sha256
    return {
        "filename": att.filename,
        "content_type": att.content_type,
        "size": att.size,
        "sha256": sha,
        "path": rel_path,
        "object": f"originals/mail/_objects/{sha[:2]}/{sha[2:]}",
        "inline": att.is_inline,
        "cid_referenced": att.referenced_in_html,
    }


def _collect_participants(msg: ParsedMessage) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for addr in [msg.from_addr, *msg.to_addrs, *msg.cc_addrs]:
        if addr and addr not in seen:
            seen.add(addr)
            result.append(addr)
    return result
