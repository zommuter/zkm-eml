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
from zkm_eml.naming import slugify, unique_path
from zkm_eml.originals import resolve_source_meta, symlink_inbox, write_original
from zkm_eml.parse import parse_eml
from zkm_eml.render import render_body
from zkm_eml.source import default_exclude_folders, iter_messages
from zkm_eml.thread_index import regenerate_thread_index
from zkm_eml.threading import thread_id_for


def convert(store_path: Path, config: dict, *, progress=None) -> list[Path]:
    src_raw = config.get("EML_SOURCE_DIR", "").strip()
    src = Path(src_raw).expanduser().resolve() if src_raw else Path.home() / "mail"
    if not src.exists():
        raise FileNotFoundError(f"EML_SOURCE_DIR does not exist: {src}")

    exclude_raw = config.get("EML_FOLDERS_EXCLUDE", "")
    if exclude_raw.strip():
        exclude_folders = [p.strip() for p in exclude_raw.split(",") if p.strip()]
    else:
        exclude_folders = default_exclude_folders()

    keep_originals = config.get("EML_KEEP_ORIGINALS", "true").lower() not in ("false", "0", "no")
    attachment_inbox = config.get("EML_ATTACHMENT_INBOX", "true").lower() not in ("false", "0", "no")
    owner_addrs = {
        a.strip().lower()
        for a in config.get("EML_OWNER_ADDRESSES", "").split(",")
        if a.strip()
    }

    messages_dir = store_path / "mail" / "messages"
    for d in ["mail/messages", "mail/threads", "originals/mail", "inbox"]:
        (store_path / d).mkdir(parents=True, exist_ok=True)

    existing_ids = _scan_existing_message_ids(messages_dir)
    created: list[Path] = []
    touched_threads: set[str] = set()

    # Resolve source git state once per run
    source_repo, source_repo_commit, _ = resolve_source_meta(src, b"")

    # Pre-pass for progress total (cheap directory walk, no file reads)
    all_paths = list(iter_messages(src, exclude_folders))
    total = len(all_paths)

    try:
        for i, eml_path in enumerate(all_paths, 1):
            if not eml_path.is_file():
                if progress:
                    progress(i, total, eml_path.name)
                continue
            try:
                raw = eml_path.read_bytes()
                msg = parse_eml(eml_path)
            except Exception as e:
                print(f"WARN: skipping {eml_path}: {e}", file=sys.stderr)
                if progress:
                    progress(i, total, eml_path.name)
                continue

            if msg.message_id in existing_ids:
                if progress:
                    progress(i, total, eml_path.name)
                continue

            tid = thread_id_for(msg.message_id, msg.references)
            thread_path = f"mail/threads/{tid}.md"
            direction = _direction(msg.from_addr, owner_addrs)
            body = render_body(msg)

            # Resolve git blob from raw bytes (cheap, no subprocess)
            from zkm_eml.originals import git_blob_sha1
            source_blob = git_blob_sha1(raw)

            home = Path.home()
            try:
                src_rel_home = str(eml_path.relative_to(home))
            except ValueError:
                src_rel_home = None

            original_rel: str | None = None
            attachment_meta = None

            if keep_originals:
                msg_slug = _resolve_orig_slug(store_path, msg)
                original_rel, attachment_pairs = write_original(
                    store_path,
                    msg,
                    raw,
                    msg_slug,
                    source_repo,
                    source_repo_commit,
                    source_blob,
                )
                attachment_meta = attachment_pairs if attachment_pairs else None

                if attachment_inbox and attachment_pairs:
                    for att, _ in attachment_pairs:
                        try:
                            symlink_inbox(store_path, att)
                        except Exception as e:
                            print(f"WARN: inbox symlink failed for {att.filename}: {e}", file=sys.stderr)

            dest = unique_path(messages_dir, f"{msg.date.strftime('%Y-%m-%d')}_{slugify(msg.subject)}")
            write_message_md(
                dest,
                msg,
                tid,
                thread_path,
                direction,
                body,
                original_rel,
                attachment_meta=attachment_meta,
                source_path_rel_home=src_rel_home,
                source_repo_commit=source_repo_commit,
                source_blob=source_blob,
            )

            created.append(dest)
            existing_ids.add(msg.message_id)
            touched_threads.add(tid)
            if progress:
                progress(i, total, eml_path.name)
    finally:
        # Regenerate indexes for every thread touched so far, even on cancel.
        for tid in touched_threads:
            regenerate_thread_index(store_path, tid)

    return created


def reprocess(store_path: Path, config: dict, existing: list[Path], *, progress=None) -> list[Path]:
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

    total = len(existing)
    updated: list[Path] = []
    touched_threads: set[str] = set()

    try:
        for i, md_path in enumerate(existing, 1):
            try:
                post = fm.load(md_path)
            except Exception:
                if progress:
                    progress(i, total, md_path.name)
                continue

            original_rel = post.metadata.get("original")
            if not original_rel:
                if progress:
                    progress(i, total, md_path.name)
                continue
            orig_path = store_path / original_rel
            if not orig_path.exists():
                if progress:
                    progress(i, total, md_path.name)
                continue

            try:
                msg = parse_eml(orig_path)
            except Exception as e:
                print(f"WARN: reprocess skipping {orig_path}: {e}", file=sys.stderr)
                if progress:
                    progress(i, total, md_path.name)
                continue

            tid = thread_id_for(msg.message_id, msg.references)
            thread_path = f"mail/threads/{tid}.md"
            direction = _direction(msg.from_addr, owner_addrs)
            body = render_body(msg)

            source_blob = post.metadata.get("source_blob")
            source_repo_commit = post.metadata.get("source_repo_commit")
            source_path_rel_home = post.metadata.get("source_path")

            write_message_md(
                md_path,
                msg,
                tid,
                thread_path,
                direction,
                body,
                original_rel,
                source_path_rel_home=source_path_rel_home,
                source_repo_commit=source_repo_commit,
                source_blob=source_blob,
            )
            updated.append(md_path)
            touched_threads.add(tid)
            if progress:
                progress(i, total, md_path.name)
    finally:
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
                ids.add(mid.strip("<>").strip())
        except Exception:
            continue
    return ids


def _direction(from_addr: str, owner_addrs: set[str]) -> str:
    if not owner_addrs:
        return "unknown"
    m = re.search(r"<([^>]+)>", from_addr)
    addr = m.group(1).lower() if m else from_addr.lower()
    return "outgoing" if addr in owner_addrs else "incoming"


def _resolve_orig_slug(store_path: Path, msg) -> str:
    """Compute a human-readable, collision-free slug for the original files."""
    originals_dir = store_path / "originals" / "mail"
    base = f"{msg.date.strftime('%Y-%m-%d')}_{slugify(msg.subject)}"
    # Avoid collision with existing .eml originals
    candidate = base
    i = 1
    while (originals_dir / f"{candidate}.eml").exists():
        candidate = f"{base}_{i}"
        i += 1
    return candidate
