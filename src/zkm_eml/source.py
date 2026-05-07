"""Iterate mail source: Maildir tree or flat .eml dump."""

from __future__ import annotations

import os
import subprocess
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


def _git_changed_paths(repo: Path, since_commit: str) -> set[Path] | None:
    """Return absolute paths touched since *since_commit* in *repo*, or None on failure.

    Includes committed changes (git diff) and working-tree changes (git status).
    Returns None when *since_commit* is not an ancestor of HEAD or any git call fails.
    """
    try:
        r = subprocess.run(
            ["git", "merge-base", "--is-ancestor", since_commit, "HEAD"],
            cwd=repo, capture_output=True, timeout=10,
        )
        if r.returncode != 0:
            return None

        diff_out = subprocess.run(
            ["git", "diff", "--name-only", since_commit, "HEAD"],
            cwd=repo, check=True, capture_output=True, text=True, timeout=30,
        ).stdout
        paths: set[Path] = set()
        for rel in diff_out.splitlines():
            if rel:
                paths.add((repo / rel).resolve())

        status_out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo, check=True, capture_output=True, text=True, timeout=10,
        ).stdout
        for line in status_out.splitlines():
            if len(line) < 4:
                continue
            path = line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            paths.add((repo / path).resolve())

        return paths
    except Exception:
        return None


def iter_messages_since(
    src: Path,
    exclude_folders: list[str],
    repo: Path,
    since_commit: str,
) -> tuple[list[Path], bool]:
    """Enumerate mail files changed since *since_commit* in *repo*.

    Returns ``(paths, fast_path_used)``.
    - When the fast path succeeds, *paths* is the subset of ``iter_messages``
      results whose absolute paths appear in the git diff / working-tree diff.
    - When the fast path fails (watermark unreachable, git error), falls back to
      ``iter_messages`` and returns ``fast_path_used=False``.

    The ``message_id``-based dedup in ``convert.py`` remains the authoritative
    dedup mechanism; this is purely an enumeration optimisation.
    """
    changed = _git_changed_paths(repo, since_commit)
    all_paths = list(iter_messages(src, exclude_folders))
    if changed is None:
        return all_paths, False
    fast = [p for p in all_paths if p.resolve() in changed]
    return fast, True
