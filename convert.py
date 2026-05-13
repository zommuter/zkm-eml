"""zkm-eml — convert .eml files to markdown with thread modeling.

Plugin entry point. See CLAUDE.md for architecture notes.
"""

from __future__ import annotations

import sys
from pathlib import Path

_plugin_root = Path(__file__).parent
# Allow running from the plugin directory directly during development
sys.path.insert(0, str(_plugin_root / "src"))
# Inject plugin-local venv so plugin-specific deps (ftfy, charset-normalizer) are
# importable when the plugin is loaded via importlib into the main zkm process.
_venv_site = list((_plugin_root / ".venv").glob("lib/python*/site-packages"))
if _venv_site:
    sys.path.insert(0, str(_venv_site[0]))

from zkm_eml.frontmatter import write_message_md
from zkm_eml.naming import date_shard, message_slug, slugify, thread_stub, unique_path
from zkm.cas import write_object
from zkm.inbox import build_canonical_index, symlink_with_sidecar
from zkm_eml.originals import find_git_root, git_head, resolve_source_meta, write_original
from zkm_eml.parse import parse_eml
from zkm_eml.render import ParentInfo, html_to_markdown, render_body, split_body_sections
from zkm_eml.source import default_exclude_folders, iter_messages, iter_messages_since
from zkm_eml.state import get_last_commit, set_last_commit
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
    quote_strip = config.get("EML_QUOTE_STRIP", "true").lower() not in ("false", "0", "no")

    limit_recent = int(config.get("EML_LIMIT_RECENT", "0") or "0")

    messages_dir = store_path / "mail" / "messages"
    for d in ["mail/messages", "mail/threads", "mail/_objects", "originals/mail", "inbox"]:
        (store_path / d).mkdir(parents=True, exist_ok=True)

    existing_ids, thread_membership, parent_index = build_thread_membership(messages_dir)
    inbox_canonical = build_canonical_index(store_path, "inbox/mail")
    created: list[Path] = []
    touched_threads: set[str] = set()

    # Resolve source git state once per run
    source_repo, source_repo_commit, _ = resolve_source_meta(src, b"")

    # Git-commit watermark: enumerate only messages touched since last run.
    # Falls back to full scan when the source isn't a git repo or watermark is absent/invalid.
    _src_repo = find_git_root(src)
    _since = get_last_commit(store_path, _src_repo) if _src_repo else None
    _fast_path_used = False
    if _src_repo and _since:
        all_paths, _fast_path_used = iter_messages_since(src, exclude_folders, _src_repo, _since)
    else:
        all_paths = list(iter_messages(src, exclude_folders))

    if limit_recent:
        all_paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    total = len(all_paths)

    lookup = _make_parent_lookup(store_path, parent_index) if quote_strip else None

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

            # Resolve git blob from raw bytes (cheap, no subprocess)
            from zkm.hashing import git_blob_sha1_bytes
            source_blob = git_blob_sha1_bytes(raw)

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
                    att_YYYY, att_MM = date_shard(msg.date)
                    link_dir = store_path / "inbox" / "mail" / att_YYYY / att_MM
                    for att, _ in attachment_pairs:
                        try:
                            symlink_with_sidecar(
                                cas_object=write_object(store_path, "mail", att.payload),
                                link_dir=link_dir,
                                link_name=att.filename,
                                producer={"plugin": "eml", "message": msg_md_path, "sha256": msg.sha256},
                                canonical_index=inbox_canonical,
                            )
                        except Exception as e:
                            print(f"WARN: inbox symlink failed for {att.filename}: {e}", file=sys.stderr)

            body = render_body(msg, parent_lookup=lookup, dest=dest)
            salutation_block, signature_block = split_body_sections(body)

            write_message_md(
                dest,
                msg,
                tid,
                thread_path,
                body,
                original_rel,
                attachment_meta=attachment_meta,
                source_path_rel_home=src_rel_home,
                source_repo_commit=source_repo_commit,
                source_blob=source_blob,
                signature_block=signature_block,
                salutation_block=salutation_block,
            )

            # Register in parent index so later messages in this run can look up this one
            if lookup is not None:
                parent_index[msg.message_id] = (dest, original_rel)

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

    # Advance watermark so the next run only diffs from this commit forward.
    # Only written on success (exceptions propagate past this point).
    if _src_repo and source_repo_commit:
        set_last_commit(store_path, _src_repo, source_repo_commit)

    return created


def reprocess(store_path: Path, config: dict, existing: list[Path], *, progress=None) -> list[Path]:
    """Re-derive markdown from stored originals. Called by zkm convert --reprocess."""
    originals_dir = store_path / "originals" / "mail"
    if not originals_dir.exists():
        return []

    import frontmatter as fm

    quote_strip = config.get("EML_QUOTE_STRIP", "true").lower() not in ("false", "0", "no")

    messages_dir = store_path / "mail" / "messages"
    _, thread_membership, parent_index = build_thread_membership(messages_dir)

    lookup = _make_parent_lookup(store_path, parent_index) if quote_strip else None

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

            body = render_body(msg, parent_lookup=lookup, dest=md_path)

            write_message_md(
                md_path,
                msg,
                tid,
                thread_path,
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
# Parent lookup factory for quote stripping
# ---------------------------------------------------------------------------

def _make_parent_lookup(
    store_path: Path,
    parent_index: dict[str, tuple[Path, str | None]],
):
    """Return a closure that resolves a message_id to ParentInfo for quote stripping."""
    cache: dict[str, ParentInfo | None] = {}
    _warned_no_originals = False

    def lookup(message_id: str) -> ParentInfo | None:
        nonlocal _warned_no_originals
        if message_id in cache:
            return cache[message_id]

        entry = parent_index.get(message_id)
        if entry is None:
            cache[message_id] = None
            return None

        md_path, original_rel = entry
        plain_body = ""
        subject = ""

        if original_rel:
            orig_path = store_path / original_rel
            if orig_path.exists():
                try:
                    pmsg = parse_eml(orig_path)
                    plain_body = pmsg.plain_body or html_to_markdown(pmsg.html_body)
                    subject = pmsg.subject
                except Exception:
                    pass

        if not plain_body:
            # Fallback: read rendered .md body (may already be stripped on re-runs)
            if not _warned_no_originals:
                print(
                    "WARN: quote-strip parent lookup falling back to rendered .md body "
                    "(set EML_KEEP_ORIGINALS=true for accurate matching)",
                    file=sys.stderr,
                )
                _warned_no_originals = True
            try:
                import frontmatter as fm
                post = fm.load(md_path)
                plain_body = post.content or ""
                subject = str(post.metadata.get("subject", ""))
            except Exception:
                pass

        if not plain_body:
            cache[message_id] = None
            return None

        info = ParentInfo(md_path=md_path, plain_body=plain_body, subject=subject)
        cache[message_id] = info
        return info

    return lookup
