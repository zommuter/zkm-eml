"""Naming helpers shared between convert.py and originals.py."""

from __future__ import annotations

import re
from pathlib import Path


def slugify(s: str) -> str:
    s = re.sub(r"^(re|aw|fwd|fw):\s*", "", s.lower().strip())
    s = re.sub(r"[^\w\- ]+", "", s)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return (s or "no-subject")[:60]


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
