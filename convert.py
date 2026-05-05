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
from zkm_eml.naming import date_shard, message_slug, slugify, thread_stub, unique_path
from zkm_eml.originals import build_inbox_canonical_index, resolve_source_meta, symlink_inbox, write_original
from zkm_eml.parse import parse_eml
from zkm_eml.render import render_body
from zkm_eml.source import default_exclude_folders, iter_messages
from zkm_eml.thread_index import ThreadMember, build_thread_membership, write_thread_index
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

    limit_recent = int(config.get("EML_LIMIT_RECENT", "0") or "0")

    messages_dir = store_path / "mail" / "messages"
    for d in ["mail/messages", "mail/threads", "mail/_objects", "originals/mail", "inbox"]:
        (store_path / d).mkdir(parents=True, exist_ok=True)

    existing_ids, thread_membership = build_thread_membership(messages_dir)
    inbox_canonical = build_inbox_canonical_index(store_path)
    created: list[Path] = []
    touched_threads: set[str] = set()

    # Resolve source git state once per run
    source_repo, source_repo_commit, _ = resolve_source_meta(src, b"")

    # Pre-pass for progress total (cheap directory walk, no file reads)
    all_paths = list(iter_messages(src, exclude_folders))
    if limit_recent:
        all_paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
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
            t8 = thread_stub(tid)
            YYYY, MM = date_shard(msg.date)
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

            # Build sharded message path; resolve collision suffix once and reuse for originals.
            thread_dir = messages_dir / YYYY / MM
            thread_dir.mkdir(parents=True, exist_ok=True)
            stem = f"{msg.date.strftime('%Y-%m-%d-%H%M')}-{t8}-{message_slug(msg.subject, msg.from_addr)}"
            dest = unique_path(thread_dir, stem)
            msg_stem = dest.stem

            # Compute thread index path from earliest-known member for this thread.
            existing_members = thread_membership.get(tid, [])
            if existing_members:
                anchor = min(existing_members, key=lambda m: m.date)
                anchor_date = anchor.date[:10]
                t_slug = slugify(anchor.subject) or "thread"
            else:
                anchor_date = msg.date.strftime("%Y-%m-%d")
                t_slug = slugify(msg.subject) or "thread"
            t_YYYY, t_MM = anchor_date[:4], anchor_date[5:7]
            thread_path = f"mail/threads/{t_YYYY}/{t_MM}/{anchor_date}-{t8}-{t_slug}.md"

            original_rel: str | None = None
            attachment_meta = None

            if keep_originals:
                original_rel, attachment_pairs = write_original(
                    store_path,
                    msg,
                    raw,
                    msg_stem,
                    source_repo,
                    source_repo_commit,
                    source_blob,
                )
                attachment_meta = attachment_pairs if attachment_pairs else None

                if attachment_inbox and attachment_pairs:
                    msg_md_path = str(dest.relative_to(store_path))
                    for att, _ in attachment_pairs:
                        try:
                            symlink_inbox(
                                store_path, att, msg.date,
                                msg_md_path=msg_md_path,
                                msg_sha256=msg.sha256,
                                plugin_name="eml",
                                canonical_index=inbox_canonical,
                            )
                        except Exception as e:
                            print(f"WARN: inbox symlink failed for {att.filename}: {e}", file=sys.stderr)

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
            thread_membership.setdefault(tid, []).append(
                ThreadMember(
                    path=dest,
                    date=msg.date.isoformat(),
                    subject=msg.subject,
                    participants=[msg.from_addr] + list(msg.to_addrs) + list(msg.cc_addrs),
                )
            )
            if progress:
                progress(i, total, eml_path.name)
            if limit_recent and len(created) >= limit_recent:
                break
    finally:
        # Write thread indexes from in-memory state — O(T), not O(T*N).
        for tid in touched_threads:
            write_thread_index(store_path, tid, thread_membership.get(tid, []))

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

    messages_dir = store_path / "mail" / "messages"
    _, thread_membership = build_thread_membership(messages_dir)

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
            t8 = thread_stub(tid)
            direction = _direction(msg.from_addr, owner_addrs)
            body = render_body(msg)

            existing_members = thread_membership.get(tid, [])
            if existing_members:
                anchor = min(existing_members, key=lambda m: m.date)
                anchor_date = anchor.date[:10]
                t_slug = slugify(anchor.subject) or "thread"
            else:
                anchor_date = msg.date.strftime("%Y-%m-%d")
                t_slug = slugify(msg.subject) or "thread"
            t_YYYY, t_MM = anchor_date[:4], anchor_date[5:7]
            thread_path = f"mail/threads/{t_YYYY}/{t_MM}/{anchor_date}-{t8}-{t_slug}.md"

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
            thread_membership.setdefault(tid, []).append(
                ThreadMember(
                    path=md_path,
                    date=msg.date.isoformat(),
                    subject=msg.subject,
                    participants=[msg.from_addr] + list(msg.to_addrs) + list(msg.cc_addrs),
                )
            )
            if progress:
                progress(i, total, md_path.name)
    finally:
        # Write thread indexes from in-memory state — O(T), not O(T*N).
        for tid in touched_threads:
            write_thread_index(store_path, tid, thread_membership.get(tid, []))

    return updated


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _direction(from_addr: str, owner_addrs: set[str]) -> str:
    if not owner_addrs:
        return "unknown"
    m = re.search(r"<([^>]+)>", from_addr)
    addr = m.group(1).lower() if m else from_addr.lower()
    return "outgoing" if addr in owner_addrs else "incoming"
