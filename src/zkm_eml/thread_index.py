"""Regenerate mail/threads/YYYY/MM/YYYY-MM-DD-<thread8>-<slug>.md from all messages in that thread."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter
import yaml

from .naming import slugify, thread_stub

logger = logging.getLogger(__name__)


@dataclass
class ThreadMember:
    path: Path
    date: str
    subject: str
    participants: list = field(default_factory=list)  # list[dict] (new) or list[str] (legacy)


def build_thread_membership(
    messages_dir: Path,
) -> tuple[set[str], dict[str, list[ThreadMember]], dict[str, tuple[Path, str | None]]]:
    """Walk messages_dir once and return (message_ids, thread_membership, parent_index).

    message_ids  — set of all known message_id values (for deduplication).
    membership   — {thread_id: [ThreadMember, ...]} for index writes.
    parent_index — {message_id: (md_path, original_rel)} for quote-strip parent lookup.
    """
    if not messages_dir.exists():
        return set(), {}, {}

    message_ids: set[str] = set()
    membership: dict[str, list[ThreadMember]] = {}
    parent_index: dict[str, tuple[Path, str | None]] = {}

    for md in messages_dir.rglob("*.md"):
        try:
            post = frontmatter.load(md)
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("thread_index: cannot read %s: %s", md, exc)
            continue
        mid = post.metadata.get("message_id", "")
        if mid:
            mid_clean = mid.strip("<>").strip()
            message_ids.add(mid_clean)
            original_rel: str | None = post.metadata.get("original") or None
            parent_index[mid_clean] = (md, original_rel)
        tid = post.metadata.get("thread_id", "")
        if tid:
            member = ThreadMember(
                path=md,
                date=str(post.metadata.get("date", "")),
                subject=str(post.metadata.get("subject", "(no subject)")),
                participants=list(post.metadata.get("participants") or []),
            )
            membership.setdefault(tid, []).append(member)

    return message_ids, membership, parent_index


def thread_index_path(store_path: Path, thread_id: str, members: list[ThreadMember]) -> Path:
    """Return the Path for the thread index, derived from the earliest member."""
    sorted_members = sorted(members, key=lambda m: m.date)
    anchor = sorted_members[0]
    date_str = anchor.date[:10]  # YYYY-MM-DD
    YYYY, MM = date_str[:4], date_str[5:7]
    t8 = thread_stub(thread_id)
    slug = slugify(anchor.subject) or "thread"
    return store_path / "mail" / "threads" / YYYY / MM / f"{date_str}-{t8}-{slug}.md"


def write_thread_index(
    store_path: Path,
    thread_id: str,
    members: list[ThreadMember],
) -> Path:
    """Write mail/threads/YYYY/MM/YYYY-MM-DD-<thread8>-<slug>.md from an in-memory members list.

    No disk scan — callers supply the full member list including pre-existing
    members loaded via build_thread_membership() plus any newly added ones.
    """
    sorted_members = sorted(members, key=lambda m: m.date)
    index_path = thread_index_path(store_path, thread_id, sorted_members)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    _write_index(index_path, thread_id, sorted_members)
    return index_path


def regenerate_thread_index(store_path: Path, thread_id: str) -> Path:
    """Back-compat wrapper: scan messages_dir and write a single thread index.

    Prefer build_thread_membership() + write_thread_index() in batch runs.
    """
    messages_dir = store_path / "mail" / "messages"
    _, membership, _ = build_thread_membership(messages_dir)
    members = membership.get(thread_id, [])
    if not members:
        raise ValueError(f"No messages found for thread_id {thread_id}")
    return write_thread_index(store_path, thread_id, members)


def _write_index(path: Path, thread_id: str, members: list[ThreadMember]) -> None:
    if not members:
        return

    # Flat-dedup participants for thread-level summary (addresses only, no roles).
    seen_addrs: set[str] = set()
    flat_participants: list[str] = []
    for m in members:
        for p in m.participants:
            addr = _participant_display(p)
            if addr and addr not in seen_addrs:
                seen_addrs.add(addr)
                flat_participants.append(addr)

    first_date = members[0].date[:10] if members else ""
    last_date = members[-1].date[:10] if members else ""
    subject = members[0].subject if members else "(thread)"

    meta = {
        "source": "eml",
        "thread_id": thread_id,
        "participants": flat_participants,
        "first_date": first_date,
        "last_date": last_date,
        "message_count": len(members),
    }

    rows = []
    for m in members:
        rel = os.path.relpath(m.path, path.parent)
        sender = _message_sender(m.participants)
        rows.append(
            f"| {m.date[:16]} | {_md_escape(sender)} | [{_md_escape(m.subject)}]({rel}) |"
        )

    body = f"# Thread: {subject}\n\n"
    body += "| Date | From | Subject |\n|------|------|------|\n"
    body += "\n".join(rows)

    post = frontmatter.Post(body, **meta)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


def _participant_display(p: dict | str) -> str:
    """Return a human-readable string from a participant dict or legacy string."""
    if isinstance(p, str):
        return p
    name = p.get("name", "")
    addr = p.get("address", "")
    return f"{name} <{addr}>" if name else addr


def _message_sender(participants: list) -> str:
    """Return display string for the from-role participant, or '?' if absent."""
    for p in participants:
        if isinstance(p, dict) and p.get("role") == "from":
            return _participant_display(p)
        if isinstance(p, str):
            return p  # legacy: first participant was the sender
    return "?"


def _md_escape(s: str) -> str:
    return s.replace("|", "\\|")
