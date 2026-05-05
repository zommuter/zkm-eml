"""Strip+detach originals writer with content-addressed attachment storage."""

from __future__ import annotations

import email
import email.policy
import hashlib
import json
import os
import subprocess
import tempfile
from email.message import EmailMessage
from pathlib import Path

from .naming import date_shard
from .parse import ParsedAttachment, ParsedMessage


def git_blob_sha1(data: bytes) -> str:
    """Compute the git blob hash (SHA-1) for *data* without invoking git."""
    h = hashlib.sha1()
    h.update(f"blob {len(data)}\0".encode())
    h.update(data)
    return h.hexdigest()


def resolve_source_meta(
    source_path: Path,
    raw_eml: bytes,
) -> tuple[str | None, str | None, str]:
    """
    Return (source_repo_root, head_commit, blob_sha1).

    Tries to find a .git directory in source_path's ancestry. blob_sha1 is
    always computed locally from the raw bytes.
    """
    blob = git_blob_sha1(raw_eml)
    repo = _find_git_root(source_path)
    if repo is None:
        return None, None, blob
    commit = _git_head(repo)
    return str(repo), commit, blob


def write_original(
    store_path: Path,
    msg: ParsedMessage,
    raw_eml: bytes,
    msg_stem: str,
    source_repo: str | None,
    source_repo_commit: str | None,
    source_blob: str,
) -> tuple[str, list[tuple[ParsedAttachment, str]]]:
    """
    Write stripped .eml + CAS attachments + sidecar JSON.

    Returns (relative_eml_path, [(attachment, relative_symlink_path), ...]).
    All paths are relative to store_path.
    """
    originals_dir = store_path / "originals" / "mail"
    objects_dir = store_path / "mail" / "_objects"
    YYYY, MM = date_shard(msg.date)
    msg_orig_dir = originals_dir / YYYY / MM
    msg_orig_dir.mkdir(parents=True, exist_ok=True)
    msg_dir = msg_orig_dir / msg_stem

    # --- Write CAS objects and per-message symlinks ---
    attachment_pairs: list[tuple[ParsedAttachment, str]] = []
    if msg.attachments:
        msg_dir.mkdir(exist_ok=True)
        seen_names: set[str] = set()
        for att in msg.attachments:
            obj_rel = _write_cas_object(objects_dir, att)
            link_name = _unique_filename_set(att.filename, seen_names)
            seen_names.add(link_name)
            link_path = msg_dir / link_name
            # msg_dir = originals/mail/YYYY/MM/<stem>/
            # objects_dir = mail/_objects/
            # relative: ../../../../.. then mail/_objects/<obj_rel>
            rel_target = Path("../../../../..") / "mail" / "_objects" / obj_rel
            if not link_path.exists():
                link_path.symlink_to(rel_target)
            symlink_rel = str((msg_dir / link_name).relative_to(store_path))
            attachment_pairs.append((att, symlink_rel))

    # --- Write stripped .eml ---
    stripped = _strip_eml(raw_eml, msg.attachments, msg_stem)
    eml_path = msg_orig_dir / f"{msg_stem}.eml"
    eml_path.write_bytes(stripped)
    eml_rel = str(eml_path.relative_to(store_path))

    # --- Write sidecar JSON ---
    home = Path.home()
    try:
        src_rel_home = str(msg.source_path.relative_to(home))
    except ValueError:
        src_rel_home = str(msg.source_path)

    sidecar = {
        "source_path": str(msg.source_path),
        "source_path_rel_home": src_rel_home,
        "source_repo": source_repo,
        "source_repo_commit": source_repo_commit,
        "source_blob": source_blob,
        "raw_sha256": msg.sha256,
        "raw_size": len(raw_eml),
    }
    json_path = msg_orig_dir / f"{msg_stem}.source.json"
    json_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    return eml_rel, attachment_pairs


def _write_cas_object(objects_dir: Path, att: ParsedAttachment) -> str:
    """Write payload to _objects/<aa>/<rest>. Returns relative path aa/<rest>."""
    sha = att.sha256
    shard_dir = objects_dir / sha[:2]
    shard_dir.mkdir(parents=True, exist_ok=True)
    obj_path = shard_dir / sha[2:]
    if not obj_path.exists():
        # Atomic write via temp file in same directory
        fd, tmp = tempfile.mkstemp(dir=shard_dir)
        try:
            os.write(fd, att.payload)
        finally:
            os.close(fd)
        os.replace(tmp, obj_path)
    return f"{sha[:2]}/{sha[2:]}"


def _strip_eml(raw_eml: bytes, attachments: list[ParsedAttachment], msg_slug: str) -> bytes:
    """Return a MIME message with attachment payloads replaced by stubs."""
    if not attachments:
        return raw_eml

    msg: EmailMessage = email.message_from_bytes(raw_eml, policy=email.policy.default)  # type: ignore[assignment]
    att_by_index = {att.part_index: att for att in attachments}

    for idx, part in enumerate(msg.walk()):
        att = att_by_index.get(idx)
        if att is None:
            continue
        stub = "[zkm-eml: payload detached - see X-Zkm-Detached]"
        part["X-Zkm-Detached"] = f"{msg_slug}/{att.filename}"
        part["X-Zkm-Detached-Sha256"] = att.sha256
        part["X-Zkm-Detached-Size"] = str(att.size)
        part.set_payload(stub)
        if "Content-Transfer-Encoding" in part:
            del part["Content-Transfer-Encoding"]

    return msg.as_bytes(policy=email.policy.SMTP)


def _unique_filename_set(name: str, seen: set[str]) -> str:
    if name not in seen:
        return name
    stem, _, ext = name.rpartition(".")
    if not stem:
        stem, ext = name, ""
    else:
        ext = f".{ext}"
    i = 1
    while True:
        candidate = f"{stem}_{i}{ext}"
        if candidate not in seen:
            return candidate
        i += 1


def _find_git_root(path: Path) -> Path | None:
    current = path if path.is_dir() else path.parent
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def _git_head(repo: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def symlink_inbox(
    store_path: Path,
    att: ParsedAttachment,
    msg_date,
) -> None:
    """Create a deduplicated inbox/mail/YYYY/MM/ symlink for *att* pointing at its CAS object."""
    from .naming import date_shard as _date_shard
    YYYY, MM = _date_shard(msg_date)
    inbox_dir = store_path / "inbox" / "mail" / YYYY / MM
    inbox_dir.mkdir(parents=True, exist_ok=True)

    sha = att.sha256
    # Relative target from inbox/mail/YYYY/MM/ to mail/_objects/<aa>/<rest>
    # up 4 levels (MM/ → YYYY/ → mail/ → inbox/) then mail/_objects/...
    rel_target = Path("../../../..") / "mail" / "_objects" / sha[:2] / sha[2:]

    link_name = att.filename
    link_path = inbox_dir / link_name

    if link_path.is_symlink():
        existing = os.readlink(link_path)
        if Path(existing) == rel_target:
            return  # already correct, dedup
        # Different object with same name — suffix with sha prefix
        stem, _, ext = link_name.rpartition(".")
        if not stem:
            stem, ext = link_name, ""
        else:
            ext = f".{ext}"
        link_name = f"{stem}_{sha[:8]}{ext}"
        link_path = inbox_dir / link_name
        if link_path.is_symlink():
            return  # already there

    if not link_path.exists():
        link_path.symlink_to(rel_target)
