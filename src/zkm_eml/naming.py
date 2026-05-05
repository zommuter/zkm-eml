"""Naming helpers shared between convert.py and originals.py."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


def slugify(s: str) -> str:
    s = re.sub(r"^(re|aw|fwd|fw):\s*", "", s.lower().strip())
    s = re.sub(r"[^\w\- ]+", "", s)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s[:60]


def message_slug(subject: str, from_addr: str) -> str:
    """Return a human-readable slug for a message.

    Falls back to the sender's local-part when subject is empty.
    """
    slug = slugify(subject)
    if slug:
        return slug
    m = re.search(r"<([^>@]+)@", from_addr) or re.search(r"^([^@\s<]+)@", from_addr.strip())
    local = slugify(m.group(1)) if m else ""
    return (f"from-{local}" if local else "from-unknown")[:60]


def date_shard(date: datetime) -> tuple[str, str]:
    """Return (YYYY, MM) strings for year/month directory sharding."""
    return date.strftime("%Y"), date.strftime("%m")


def thread_stub(thread_id: str) -> str:
    """Return the first 8 hex chars of thread_id for use in filenames."""
    return thread_id[:8]


def msgid_slug(message_id: str) -> str:
    slug = re.sub(r"[^\w@.\-]+", "_", message_id)
    return slug[:120]


def unique_path(directory: Path, stem: str, suffix: str = ".md") -> Path:
    candidate = directory / f"{stem}{suffix}"
    i = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{i}{suffix}"
        i += 1
    return candidate


def sanitize_filename(name: str, fallback: str = "attachment") -> str:
    name = re.sub(r"[/\\]", "_", name)
    name = re.sub(r"[\x00-\x1f]", "", name)
    name = name.lstrip(".")
    name = name.strip()
    return (name or fallback)[:120]
