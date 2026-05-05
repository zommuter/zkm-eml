"""Iterate mail source: Maildir tree or flat .eml dump."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

_ALWAYS_SKIP = frozenset({".git", ".notmuch", ".snapshots", "tmp"})


def iter_messages(src: Path, exclude_folders: list[str]) -> Iterator[Path]:
    """
    Yield every mail file under *src*, read-only.

    Recognizes two layouts:
      - Maildir: files inside ``cur/`` or ``new/`` sub-directories (no extension required).
      - Flat .eml dump: files named ``*.eml`` anywhere in the tree.

    Never yields dotfiles or entries in excluded or always-skipped folders.
    """
    exclude_lower = [p.lower() for p in exclude_folders if p.strip()]

    for root_str, dirs, files in os.walk(src, followlinks=False):
        root = Path(root_str)
        rel = root.relative_to(src)

        # Prune metadata dirs
        dirs[:] = [
            d for d in sorted(dirs)
            if d not in _ALWAYS_SKIP and not d.startswith(".")
            and not _is_excluded(rel / d, exclude_lower)
        ]

        is_maildir_leaf = root.name in ("cur", "new")
        for fname in sorted(files):
            if fname.startswith("."):
                continue
            path = root / fname
            if is_maildir_leaf:
                yield path
            elif fname.endswith(".eml"):
                yield path


def _is_excluded(rel: Path, exclude_lower: list[str]) -> bool:
    """Return True if any part of *rel* matches an exclusion pattern."""
    parts_lower = [p.lower() for p in rel.parts]
    for pattern in exclude_lower:
        pattern_parts = [p.lower() for p in Path(pattern).parts]
        n = len(pattern_parts)
        # Match if the last n parts of rel equal the pattern parts
        if len(parts_lower) >= n and parts_lower[-n:] == pattern_parts:
            return True
    return False


def default_exclude_folders() -> list[str]:
    return [
        "Trash",
        "Junk",
        "Spam",
        "Spamverdacht",
        "Virusverdacht",
        "Gelöscht",
        "[Google Mail]/Trash",
        "[Google Mail]/Spam",
        "Drafts",
        "Entwürfe",
    ]
