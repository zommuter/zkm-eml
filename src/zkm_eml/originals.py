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
    msg_md_rel = f"mail/messages/{YYYY}/{MM}/{msg_stem}.md"
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

            # Per-message-attachment sidecar
            att_sidecar_path = msg_dir / f"{link_name}.json"
            _write_att_sidecar(att_sidecar_path, att, link_name, obj_rel)

            # Per-CAS-object sidecar
            cas_sidecar_path = objects_dir / f"{att.sha256[:2]}/{att.sha256[2:]}.json"
            _merge_cas_sidecar(cas_sidecar_path, att, link_name, msg_md_rel, msg.sha256)

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


def _write_att_sidecar(
    sidecar_path: Path,
    att: ParsedAttachment,
    link_name: str,
    obj_rel: str,
) -> None:
    """Write per-message-attachment sidecar next to the per-message symlink."""
    data = {
        "schema": 1,
        "filename": link_name,
        "filename_raw": att.filename_raw,
        "content_type": att.content_type,
        "content_id": att.content_id,
        "is_inline": att.is_inline,
        "cid_referenced_in_html": att.referenced_in_html,
        "part_index": att.part_index,
        "size": att.size,
        "sha256": att.sha256,
        "object": f"mail/_objects/{obj_rel}",
    }
    _atomic_write_json(sidecar_path, data)


def _merge_cas_sidecar(
    sidecar_path: Path,
    att: ParsedAttachment,
    link_name: str,
    msg_md_rel: str,
    msg_sha256: str,
) -> None:
    """Write or update the per-CAS-object sidecar listing all producing messages."""
    new_producer = {"message": msg_md_rel, "filename": link_name, "sha256": msg_sha256}
    if sidecar_path.exists():
        try:
            data = json.loads(sidecar_path.read_text(encoding="utf-8"))
            producers = data.get("producers", [])
            # Dedup by source-content sha256, not rendered path (which can shift between runs)
            if not any(p.get("sha256") == msg_sha256 for p in producers):
                producers.append(new_producer)
                producers.sort(key=lambda p: p.get("message", ""))
            data["producers"] = producers
            filenames: list[str] = data.get("filenames", [])
            if link_name not in filenames:
                filenames.append(link_name)
            data["filenames"] = filenames
            content_types: list[str] = data.get("content_types", [])
            if att.content_type not in content_types:
                content_types.append(att.content_type)
            data["content_types"] = content_types
        except (OSError, json.JSONDecodeError):
            data = _new_cas_sidecar(att, link_name, new_producer)
    else:
        data = _new_cas_sidecar(att, link_name, new_producer)
    _atomic_write_json(sidecar_path, data)


def _new_cas_sidecar(att: ParsedAttachment, link_name: str, producer: dict) -> dict:
    return {
        "schema": 1,
        "sha256": att.sha256,
        "size": att.size,
        "content_types": [att.content_type],
        "filenames": [link_name],
        "producers": [producer],
    }


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


def build_inbox_canonical_index(store_path: Path) -> dict[str, Path]:
    """Scan existing inbox/mail symlinks to build sha256 -> canonical symlink path index."""
    index: dict[str, Path] = {}
    inbox_dir = store_path / "inbox" / "mail"
    if not inbox_dir.exists():
        return index
    for link in inbox_dir.rglob("*"):
        if not link.is_symlink() or link.name.endswith(".origin.json"):
            continue
        try:
            parts = Path(os.readlink(link)).parts
            if len(parts) >= 2:
                sha = parts[-2] + parts[-1]
                if len(sha) == 64 and sha not in index:
                    index[sha] = link
        except Exception:
            pass
    return index


def symlink_inbox(
    store_path: Path,
    att: ParsedAttachment,
    msg_date,
    msg_md_path: str,
    msg_sha256: str,
    plugin_name: str,
    canonical_index: dict[str, Path],
) -> None:
    """Create or update the canonical inbox/mail symlink and .origin.json sidecar for *att*."""
    from .naming import date_shard as _date_shard

    sha = att.sha256
    rel_target = Path("../../../..") / "mail" / "_objects" / sha[:2] / sha[2:]
    _SIDECAR_SUFFIX = ".origin.json"

    if sha in canonical_index:
        canonical_link = canonical_index[sha]
        sidecar_path = canonical_link.parent / (canonical_link.name + _SIDECAR_SUFFIX)
        _merge_inbox_sidecar(sidecar_path, sha, msg_md_path, msg_sha256, plugin_name)
        return

    YYYY, MM = _date_shard(msg_date)
    inbox_dir = store_path / "inbox" / "mail" / YYYY / MM
    inbox_dir.mkdir(parents=True, exist_ok=True)

    link_name = att.filename
    link_path = inbox_dir / link_name

    if link_path.is_symlink():
        existing = Path(os.readlink(link_path))
        if existing == rel_target:
            canonical_index[sha] = link_path
            sidecar_path = link_path.parent / (link_path.name + _SIDECAR_SUFFIX)
            _merge_inbox_sidecar(sidecar_path, sha, msg_md_path, msg_sha256, plugin_name)
            return
        # Name collision with different content — suffix with sha prefix.
        stem, _, ext = link_name.rpartition(".")
        if not stem:
            stem, ext = link_name, ""
        else:
            ext = f".{ext}"
        link_name = f"{stem}_{sha[:8]}{ext}"
        link_path = inbox_dir / link_name
        if link_path.is_symlink():
            canonical_index[sha] = link_path
            sidecar_path = link_path.parent / (link_path.name + _SIDECAR_SUFFIX)
            _merge_inbox_sidecar(sidecar_path, sha, msg_md_path, msg_sha256, plugin_name)
            return

    link_path.symlink_to(rel_target)
    canonical_index[sha] = link_path
    sidecar_path = link_path.parent / (link_path.name + _SIDECAR_SUFFIX)
    _write_inbox_sidecar(sidecar_path, sha, msg_md_path, msg_sha256, plugin_name)


def _write_inbox_sidecar(
    sidecar_path: Path,
    sha: str,
    msg_md_path: str,
    msg_sha256: str,
    plugin_name: str,
) -> None:
    data = {
        "schema": 1,
        "sha256": sha,
        "producers": [{"plugin": plugin_name, "message": msg_md_path, "sha256": msg_sha256}],
    }
    _atomic_write_json(sidecar_path, data)


def _merge_inbox_sidecar(
    sidecar_path: Path,
    sha: str,
    msg_md_path: str,
    msg_sha256: str,
    plugin_name: str,
) -> None:
    new_producer = {"plugin": plugin_name, "message": msg_md_path, "sha256": msg_sha256}
    if sidecar_path.exists():
        try:
            data = json.loads(sidecar_path.read_text(encoding="utf-8"))
            producers = data.get("producers", [])
            # Dedup by source-content sha256, not rendered path (which can shift between runs)
            if not any(p.get("sha256") == msg_sha256 for p in producers):
                producers.append(new_producer)
                producers.sort(key=lambda p: p.get("message", ""))
            data["producers"] = producers
        except (OSError, json.JSONDecodeError):
            data = {"schema": 1, "sha256": sha, "producers": [new_producer]}
    else:
        data = {"schema": 1, "sha256": sha, "producers": [new_producer]}
    _atomic_write_json(sidecar_path, data)


def _atomic_write_json(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.write(fd, json.dumps(data, indent=2).encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, path)


def backfill_sidecars(store_path: Path) -> tuple[int, int]:
    """Backfill per-attachment and per-CAS sidecars for existing originals.

    Walks originals/mail/*/*/<stem>/ symlink dirs, re-parses each source EML,
    matches attachments by sha256, and writes any missing sidecar files.

    Returns (att_sidecars_written, cas_sidecars_merged).
    """
    from .parse import parse_eml

    originals_dir = store_path / "originals" / "mail"
    objects_dir = store_path / "mail" / "_objects"
    att_written = 0
    cas_merged = 0

    for source_json in sorted(originals_dir.rglob("*.source.json")):
        stem = source_json.name[: -len(".source.json")]
        msg_dir = source_json.parent / stem
        if not msg_dir.is_dir():
            continue  # no attachments for this message

        try:
            source_data = json.loads(source_json.read_text(encoding="utf-8"))
        except Exception:
            continue

        eml_path = _resolve_source(source_data)
        if eml_path is None:
            continue

        try:
            msg = parse_eml(eml_path)
        except Exception as e:
            print(f"WARN: cannot parse {eml_path}: {e}", flush=True)
            continue

        att_by_sha = {att.sha256: att for att in msg.attachments}

        # Derive mail/messages/YYYY/MM/<stem>.md relative path
        rel_parts = msg_dir.relative_to(originals_dir).parts  # (YYYY, MM, stem)
        if len(rel_parts) != 3:
            continue
        YYYY, MM, stem_name = rel_parts
        msg_md_rel = f"mail/messages/{YYYY}/{MM}/{stem_name}.md"

        for link in sorted(msg_dir.iterdir()):
            if not link.is_symlink() or link.name.endswith(".json"):
                continue

            # Recover sha256 from symlink target: .../mail/_objects/<aa>/<rest>
            try:
                target_parts = Path(os.readlink(link)).parts
                sha = target_parts[-2] + target_parts[-1]
                if len(sha) != 64:
                    continue
            except Exception:
                continue

            att = att_by_sha.get(sha)
            if att is None:
                continue

            link_name = link.name
            obj_rel = f"{sha[:2]}/{sha[2:]}"

            att_sidecar = msg_dir / f"{link_name}.json"
            if not att_sidecar.exists():
                _write_att_sidecar(att_sidecar, att, link_name, obj_rel)
                att_written += 1

            cas_sidecar = objects_dir / f"{sha[:2]}/{sha[2:]}.json"
            _merge_cas_sidecar(cas_sidecar, att, link_name, msg_md_rel, msg.sha256)
            cas_merged += 1

    return att_written, cas_merged


def _resolve_source(source_data: dict) -> Path | None:
    """Return the source EML path from a .source.json dict, or None if inaccessible."""
    for key in ("source_path", "source_path_rel_home"):
        raw = source_data.get(key)
        if not raw:
            continue
        p = Path(raw) if key == "source_path" else Path.home() / raw
        if p.exists():
            return p
    return None
