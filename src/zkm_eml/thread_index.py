"""Regenerate mail/threads/<aa>/<rest>.md from all messages in that thread."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from .naming import shard_path


@dataclass
class ThreadMember:
    path: Path
    date: str
    subject: str
    participants: list[str] = field(default_factory=list)


def build_thread_membership(
    messages_dir: Path,
) -> tuple[set[str], dict[str, list[ThreadMember]]]:
    """Walk messages_dir once and return (message_ids, thread_membership).

    message_ids  — set of all known message_id values (for deduplication).
    membership   — {thread_id: [ThreadMember, ...]} for index writes.
    """
    if not messages_dir.exists():
        return set(), {}

    message_ids: set[str] = set()
    membership: dict[str, list[ThreadMember]] = {}

    for md in messages_dir.rglob("*.md"):
        try:
            post = frontmatter.load(md)
        except Exception:
            continue
        mid = post.metadata.get("message_id", "")
        if mid:
            message_ids.add(mid.strip("<>").strip())
        tid = post.metadata.get("thread_id", "")
        if tid:
            member = ThreadMember(
                path=md,
                date=str(post.metadata.get("date", "")),
                subject=str(post.metadata.get("subject", "(no subject)")),
                participants=list(post.metadata.get("participants") or []),
            )
            membership.setdefault(tid, []).append(member)

    return message_ids, membership


def write_thread_index(
    store_path: Path,
    thread_id: str,
    members: list[ThreadMember],
) -> Path:
    """Write mail/threads/<aa>/<rest>.md from an in-memory members list.

    No disk scan — callers supply the full member list including pre-existing
    members loaded via build_thread_membership() plus any newly added ones.
    """
    aa, rest = shard_path(thread_id)
    threads_dir = store_path / "mail" / "threads" / aa
    threads_dir.mkdir(parents=True, exist_ok=True)

    sorted_members = sorted(members, key=lambda m: m.date)
    index_path = threads_dir / f"{rest}.md"
    _write_index(index_path, thread_id, sorted_members)
    return index_path


def regenerate_thread_index(store_path: Path, thread_id: str) -> Path:
    """Back-compat wrapper: scan messages_dir and write a single thread index.

    Prefer build_thread_membership() + write_thread_index() in batch runs.
    """
    messages_dir = store_path / "mail" / "messages"
    _, membership = build_thread_membership(messages_dir)
    members = membership.get(thread_id, [])
    return write_thread_index(store_path, thread_id, members)


def _write_index(path: Path, thread_id: str, members: list[ThreadMember]) -> None:
    if not members:
        return

    participants: list[str] = []
    seen: set[str] = set()
    for m in members:
        for p in m.participants:
            if p not in seen:
                seen.add(p)
                participants.append(p)

    first_date = members[0].date[:10] if members else ""
    last_date = members[-1].date[:10] if members else ""
    subject = members[0].subject if members else "(thread)"

    meta = {
        "source": "zkm-eml",
        "thread_id": thread_id,
        "participants": participants,
        "first_date": first_date,
        "last_date": last_date,
        "message_count": len(members),
    }

    rows = []
    for m in members:
        rel = os.path.relpath(m.path, path.parent)
        from_addr = m.participants[0] if m.participants else "?"
        rows.append(
            f"| {m.date[:16]} | {_md_escape(from_addr)} | [{_md_escape(m.subject)}]({rel}) |"
        )

    body = f"# Thread: {subject}\n\n"
    body += "| Date | From | Subject |\n|------|------|------|\n"
    body += "\n".join(rows)

    post = frontmatter.Post(body, **meta)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


def _md_escape(s: str) -> str:
    return s.replace("|", "\\|")
