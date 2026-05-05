"""zkm-eml — convert .eml files to markdown with thread modeling.

Plugin entry point. See CLAUDE.md for architecture notes.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Allow running from the plugin directory directly during development
sys.path.insert(0, str(Path(__file__).parent / "src"))

from zkm_eml.frontmatter import write_message_md
from zkm_eml.parse import parse_eml
from zkm_eml.render import render_body
from zkm_eml.thread_index import regenerate_thread_index
from zkm_eml.threading import thread_id_for


def convert(store_path: Path, config: dict) -> list[Path]:
    src = Path(config["EML_SOURCE_DIR"]).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"EML_SOURCE_DIR does not exist: {src}")

    keep_originals = config.get("EML_KEEP_ORIGINALS", "true").lower() not in ("false", "0", "no")
    owner_addrs = {
        a.strip().lower()
        for a in config.get("EML_OWNER_ADDRESSES", "").split(",")
        if a.strip()
    }

    messages_dir = store_path / "mail" / "messages"
    originals_dir = store_path / "originals" / "mail"

    existing_ids = _scan_existing_message_ids(messages_dir)
    created: list[Path] = []
    touched_threads: set[str] = set()

    for eml_path in sorted(src.rglob("*.eml")):
        if not eml_path.is_file():
            continue
        try:
            msg = parse_eml(eml_path)
        except Exception as e:
            print(f"WARN: skipping {eml_path}: {e}", file=sys.stderr)
            continue

        if msg.message_id in existing_ids:
            continue

        tid = thread_id_for(msg.message_id, msg.references)
        thread_path = f"mail/threads/{tid}.md"
        direction = _direction(msg.from_addr, owner_addrs)
        body = render_body(msg)

        original_rel: str | None = None
        if keep_originals:
            slug = _msgid_slug(msg.message_id)
            orig_dest = originals_dir / f"{slug}.eml"
            orig_dest.parent.mkdir(parents=True, exist_ok=True)
            orig_dest.write_bytes(eml_path.read_bytes())
            original_rel = str(orig_dest.relative_to(store_path))

        dest = _unique_path(messages_dir, msg.date.strftime("%Y-%m-%d"), _slugify(msg.subject))
        write_message_md(dest, msg, tid, thread_path, direction, body, original_rel)

        created.append(dest)
        existing_ids.add(msg.message_id)
        touched_threads.add(tid)

    for tid in touched_threads:
        regenerate_thread_index(store_path, tid)

    return created


def reprocess(store_path: Path, config: dict, existing: list[Path]) -> list[Path]:
    """Re-derive markdown from stored originals. Called by zkm convert --reprocess."""
    originals_dir = store_path / "originals" / "mail"
    if not originals_dir.exists():
        return []

    import frontmatter as fm

    owner_addrs = {
        a.strip().lower()
        for a in config.get("EML_OWNER_ADDRESSES", "").split(",")
        if a.strip()
    }

    updated: list[Path] = []
    touched_threads: set[str] = set()

    for md_path in existing:
        try:
            post = fm.load(md_path)
        except Exception:
            continue

        original_rel = post.metadata.get("original")
        if not original_rel:
            continue
        orig_path = store_path / original_rel
        if not orig_path.exists():
            continue

        try:
            msg = parse_eml(orig_path)
        except Exception as e:
            print(f"WARN: reprocess skipping {orig_path}: {e}", file=sys.stderr)
            continue

        tid = thread_id_for(msg.message_id, msg.references)
        thread_path = f"mail/threads/{tid}.md"
        direction = _direction(msg.from_addr, owner_addrs)
        body = render_body(msg)

        write_message_md(md_path, msg, tid, thread_path, direction, body, original_rel)
        updated.append(md_path)
        touched_threads.add(tid)

    for tid in touched_threads:
        regenerate_thread_index(store_path, tid)

    return updated


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scan_existing_message_ids(messages_dir: Path) -> set[str]:
    if not messages_dir.exists():
        return set()
    import frontmatter as fm

    ids: set[str] = set()
    for md in messages_dir.rglob("*.md"):
        try:
            post = fm.load(md)
            mid = post.metadata.get("message_id", "")
            if mid:
                # Store without angle brackets for consistent comparison
                ids.add(mid.strip("<>").strip())
        except Exception:
            continue
    return ids


def _direction(from_addr: str, owner_addrs: set[str]) -> str:
    if not owner_addrs:
        return "unknown"
    # Extract the bare address from "Name <addr>"
    m = re.search(r"<([^>]+)>", from_addr)
    addr = m.group(1).lower() if m else from_addr.lower()
    return "outgoing" if addr in owner_addrs else "incoming"


def _slugify(s: str) -> str:
    s = re.sub(r"^(re|fwd|fw):\s*", "", s.lower().strip())
    s = re.sub(r"[^\w\- ]+", "", s)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return (s or "no-subject")[:60]


def _msgid_slug(message_id: str) -> str:
    """Convert a message_id to a filesystem-safe slug for originals/."""
    slug = re.sub(r"[^\w@.\-]+", "_", message_id)
    return slug[:120]


def _unique_path(directory: Path, date_prefix: str, slug: str) -> Path:
    candidate = directory / f"{date_prefix}_{slug}.md"
    i = 1
    while candidate.exists():
        candidate = directory / f"{date_prefix}_{slug}_{i}.md"
        i += 1
    return candidate
