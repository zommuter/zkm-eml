"""Regenerate mail/threads/<thread_id>.md from all messages in that thread."""

from __future__ import annotations

from pathlib import Path

import frontmatter


def regenerate_thread_index(store_path: Path, thread_id: str) -> Path:
    """
    Collect all messages for thread_id, sort by date, write thread index.
    Returns the path to the written thread index file.
    """
    messages_dir = store_path / "mail" / "messages"
    threads_dir = store_path / "mail" / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)

    thread_messages = _collect_thread_messages(messages_dir, thread_id)

    index_path = threads_dir / f"{thread_id}.md"
    _write_index(index_path, thread_id, thread_messages)
    return index_path


def _collect_thread_messages(messages_dir: Path, thread_id: str) -> list[dict]:
    if not messages_dir.exists():
        return []

    msgs = []
    for md in messages_dir.rglob("*.md"):
        try:
            post = frontmatter.load(md)
            if post.metadata.get("thread_id") != thread_id:
                continue
            msgs.append({
                "path": md,
                "date": post.metadata.get("date", ""),
                "subject": post.metadata.get("subject", "(no subject)"),
                "from": _extract_from(post.metadata.get("participants", [])),
                "rel_path": str(md),
            })
        except Exception:
            continue

    msgs.sort(key=lambda m: m["date"])
    return msgs


def _extract_from(participants: list) -> str:
    return participants[0] if participants else "?"


def _write_index(path: Path, thread_id: str, messages: list[dict]) -> None:
    if not messages:
        return

    participants: list[str] = []
    seen: set[str] = set()
    for msg in messages:
        for p in _all_participants_for_msg(msg["path"]):
            if p not in seen:
                seen.add(p)
                participants.append(p)

    first_date = messages[0]["date"][:10] if messages else ""
    last_date = messages[-1]["date"][:10] if messages else ""
    subject = messages[0]["subject"] if messages else "(thread)"

    meta = {
        "source": "zkm-eml",
        "thread_id": thread_id,
        "participants": participants,
        "first_date": first_date,
        "last_date": last_date,
        "message_count": len(messages),
    }

    rows = []
    for msg in messages:
        rel = "../messages/" + Path(msg["path"]).name
        rows.append(f"| {msg['date'][:16]} | {_md_escape(msg['from'])} | [{_md_escape(msg['subject'])}]({rel}) |")

    body = f"# Thread: {subject}\n\n"
    body += "| Date | From | Subject |\n|------|------|------|\n"
    body += "\n".join(rows)

    post = frontmatter.Post(body, **meta)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


def _all_participants_for_msg(md_path: Path) -> list[str]:
    try:
        post = frontmatter.load(md_path)
        return list(post.metadata.get("participants") or [])
    except Exception:
        return []


def _md_escape(s: str) -> str:
    return s.replace("|", "\\|")
