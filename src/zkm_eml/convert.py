"""zkm-eml — convert .eml files to markdown with thread modeling.

Plugin implementation. Loaded by core via entry-point discovery (installed wheel)
or via the filesystem-shim convert.py (dev-symlink path).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from zkm_eml.frontmatter import write_message_md
from zkm_eml.naming import date_shard, message_slug, slugify, thread_stub, unique_path
from zkm.cas import write_object
from zkm.inbox import build_canonical_index, symlink_with_sidecar
from zkm.hashing import git_blob_hash_bytes
from zkm_eml.originals import detect_git_object_format, find_git_root, resolve_source_meta, write_original
from zkm_eml.parse import parse_eml
from zkm_eml.render import ParentInfo, detach_html_data_uris, html_to_markdown, render_body, split_body_sections
from zkm_eml.source import default_exclude_folders, iter_messages, iter_messages_since
from zkm_eml.state import get_last_commit, set_last_commit
from zkm_eml.thread_index import ThreadMember, build_thread_membership, write_thread_index
from zkm_eml.threading import thread_id_for


def convert(store_path: Path, config: dict, *, progress=None) -> list[Path]:
    src_raw = str(config.get("source_dir", "")).strip()
    src = Path(src_raw).expanduser().resolve() if src_raw else Path.home() / "mail"
    if not src.exists():
        raise FileNotFoundError(f"source_dir does not exist: {src}")

    excl_raw = config.get("folders_exclude", "")
    if isinstance(excl_raw, list):
        exclude_folders = [s for s in excl_raw if s] or default_exclude_folders()
    else:
        raw_str = str(excl_raw).strip()
        exclude_folders = [p.strip() for p in raw_str.split(",") if p.strip()] if raw_str else default_exclude_folders()

    keep_originals = bool(config.get("keep_originals", True))
    attachment_inbox = bool(config.get("attachment_inbox", True))
    quote_strip = bool(config.get("quote_strip", True))
    slug_ascii = bool(config.get("slug_ascii", False))

    limit_recent = int(config.get("limit_recent", 0) or 0)

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
    _src_fmt = detect_git_object_format(_src_repo) if _src_repo else "sha1"
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

            # Detach inline data-URI images from HTML body before CAS storage
            if msg.html_body:
                cleaned_html, inline_atts = detach_html_data_uris(msg.html_body)
                if inline_atts:
                    msg.html_body = cleaned_html
                    msg.attachments.extend(inline_atts)
                    msg.has_attachments = True

            tid = thread_id_for(msg.message_id, msg.references)
            t8 = thread_stub(tid)
            YYYY, MM = date_shard(msg.date)

            source_blob = git_blob_hash_bytes(raw, _src_fmt)

            home = Path.home()
            try:
                src_rel_home = str(eml_path.relative_to(home))
            except ValueError:
                src_rel_home = None

            # Build sharded message path; resolve collision suffix once and reuse for originals.
            thread_dir = messages_dir / YYYY / MM
            thread_dir.mkdir(parents=True, exist_ok=True)
            stem = f"{msg.date.strftime('%Y-%m-%d-%H%M')}-{t8}-{message_slug(msg.subject, msg.from_addr, slug_ascii=slug_ascii)}"
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
                        if att.is_signature_part:
                            continue  # signature leaves are CAS-preserved but never fan-out to inbox
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
                signed=msg.signed,
                auth_results=msg.auth_results or None,
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

    # M3: handle source-mail deletions (git-backed sources + fast-path only)
    deleted_policy = str(config.get("deleted_policy", "keep")).strip().lower()
    if deleted_policy != "keep" and _fast_path_used and _src_repo and _since and source_repo_commit:
        _deleted = _get_deleted_blobs(_src_repo, _since, source_repo_commit)
        if _deleted:
            _apply_deleted_policy(store_path, messages_dir, _deleted, deleted_policy)

    return created


def reprocess(store_path: Path, config: dict, existing: list[Path], *, progress=None) -> list[Path]:
    """Re-derive markdown from stored originals. Called by zkm convert --reprocess."""
    originals_dir = store_path / "originals" / "mail"
    if not originals_dir.exists():
        return []

    import frontmatter as fm

    quote_strip = bool(config.get("quote_strip", True))

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

def _get_deleted_blobs(src_repo: Path, since: str, until: str) -> list[tuple[str, str]]:
    """Return (blob_sha, repo-relative-path) for files deleted between *since* and *until*."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "diff", "--raw", "--no-abbrev", "--diff-filter=D", since, until],
            cwd=str(src_repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    pairs: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.startswith(":"):
            continue
        try:
            meta_part, path = line.split("\t", 1)
        except ValueError:
            continue
        fields = meta_part.split()
        if len(fields) < 3:
            continue
        pairs.append((fields[2], path))
    return pairs


def _build_source_blob_index(messages_dir: Path) -> dict[str, Path]:
    """Scan all .md files under *messages_dir* and return {source_blob: md_path}."""
    import frontmatter as fm
    index: dict[str, Path] = {}
    for md_path in messages_dir.rglob("*.md"):
        try:
            post = fm.load(md_path)
            blob = post.metadata.get("source_blob")
            if blob:
                index[str(blob)] = md_path
        except Exception:
            pass
    return index


def _mark_source_deleted(md_path: Path) -> None:
    """Insert ``source_deleted: true`` into the YAML frontmatter block in-place."""
    import re
    text = md_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return
    new_text = re.sub(r"\n---\n", "\nsource_deleted: true\n---\n", text, count=1)
    if new_text == text:
        return
    from zkm.atomic import write_atomic
    write_atomic(md_path, new_text)


def _apply_deleted_policy(
    store_path: Path,
    messages_dir: Path,
    deleted_blobs: list[tuple[str, str]],
    policy: str,
) -> int:
    """Apply *policy* to .md files whose source blob was deleted. Returns count of affected files."""
    if not deleted_blobs:
        return 0
    blob_index = _build_source_blob_index(messages_dir)
    count = 0
    for blob_sha, src_rel in deleted_blobs:
        md_path = blob_index.get(blob_sha)
        if md_path is None or not md_path.exists():
            continue
        rel = md_path.relative_to(store_path)
        if policy == "log":
            print(f"INFO: source deleted: {src_rel} → {rel}", file=sys.stderr)
        elif policy == "purge":
            md_path.unlink()
            print(
                f"INFO: purged (source deleted): {rel}"
                " — run 'zkm gc' to clean originals",
                file=sys.stderr,
            )
        elif policy == "archive":
            _mark_source_deleted(md_path)
            print(f"INFO: archived (source_deleted=true): {rel}", file=sys.stderr)
        else:
            continue
        count += 1
    return count


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


# Base64 content fragment: 40+ chars of pure base64 alphabet (no spaces, no hyphens).
_BASE64_FRAGMENT_RE = re.compile(r"^[A-Za-z0-9+/=]{40,}$")

def _is_scrub_garbage(value: str) -> bool:
    """Detect NER entity values that are undecoded-HTML body noise, not real entities."""
    if _BASE64_FRAGMENT_RE.match(value):
        return True
    if value.startswith("&gt;"):
        return True
    if value.count("&nbsp;") >= 3:
        return True
    if "\n&gt" in value:
        return True
    return False


def scrub(
    store_path: Path,
    config: dict,
    *,
    dry_run: bool = True,
    verbose: bool = False,
    progress=None,
) -> dict[str, int]:
    """Remove entity garbage from entities[] in mail/messages files."""
    import frontmatter as fm
    from zkm.atomic import write_atomic

    messages_dir = store_path / "mail" / "messages"
    if not messages_dir.exists():
        return {"files_scanned": 0, "files_changed": 0, "entities_removed": 0}

    files_scanned = files_changed = entities_removed = 0

    md_files = sorted(
        p for p in messages_dir.rglob("*.md")
        if not any(part.startswith(".") for part in p.relative_to(store_path).parts[:-1])
    )
    total = len(md_files)

    for i, md_path in enumerate(md_files):
        if progress is not None:
            progress(i, total, str(md_path.relative_to(store_path)))

        try:
            post = fm.load(str(md_path))
        except Exception:
            continue

        files_scanned += 1
        entities = post.metadata.get("entities") or []
        clean = [e for e in entities if not _is_scrub_garbage(str(e.get("value", "")))]
        removed = len(entities) - len(clean)

        if removed:
            if verbose:
                print(f"  {md_path.relative_to(store_path)}: -{removed} entity fragments")
            if not dry_run:
                post.metadata["entities"] = clean
                write_atomic(md_path, fm.dumps(post))
            entities_removed += removed
            files_changed += 1

    if progress is not None:
        progress(total, total, "done")

    return {
        "files_scanned": files_scanned,
        "files_changed": files_changed,
        "entities_removed": entities_removed,
    }
