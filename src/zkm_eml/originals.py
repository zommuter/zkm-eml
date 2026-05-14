"""Strip+detach originals writer with content-addressed attachment storage."""

from __future__ import annotations

import email
import email.policy
import json
import os
import subprocess
from email.message import EmailMessage
from pathlib import Path

from zkm.atomic import write_atomic
from zkm.cas import write_object
from zkm.hashing import git_blob_sha1_bytes
from zkm.sidecar import merge_producer

from .naming import date_shard
from .parse import ParsedAttachment, ParsedMessage


def resolve_source_meta(
    source_path: Path,
    raw_eml: bytes,
) -> tuple[str | None, str | None, str]:
    """
    Return (source_repo_root, head_commit, blob_sha1).

    Tries to find a .git directory in source_path's ancestry. blob_sha1 is
    always computed locally from the raw bytes.
    """
    blob = git_blob_sha1_bytes(raw_eml)
    repo = find_git_root(source_path)
    if repo is None:
        return None, None, blob
    commit = git_head(repo)
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
            obj_path = write_object(store_path, "mail", att.payload)
            obj_rel = f"{att.sha256[:2]}/{att.sha256[2:]}"
            link_name = _unique_filename_set(att.filename, seen_names)
            seen_names.add(link_name)
            link_path = msg_dir / link_name
            rel_target = Path(os.path.relpath(obj_path, msg_dir))
            if not link_path.exists():
                link_path.symlink_to(rel_target)
            symlink_rel = str((msg_dir / link_name).relative_to(store_path))
            attachment_pairs.append((att, symlink_rel))

            # Per-message-attachment sidecar
            att_sidecar_path = msg_dir / f"{link_name}.json"
            _write_att_sidecar(att_sidecar_path, att, link_name, obj_rel)

            # Per-CAS-object sidecar (spec v1)
            merge_producer(
                obj_path.with_name(obj_path.name + ".json"),
                sha256=att.sha256,
                producer={"plugin": "eml", "message": msg_md_rel, "sha256": msg.sha256},
            )

    # --- Write stripped .eml ---
    stripped = _strip_eml(raw_eml, msg.attachments, msg_stem)
    eml_path = msg_orig_dir / f"{msg_stem}.eml"
    write_atomic(eml_path, stripped)
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
    write_atomic(json_path, json.dumps(sidecar, indent=2))

    return eml_rel, attachment_pairs


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
    write_atomic(sidecar_path, json.dumps(data, indent=2))


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


def find_git_root(path: Path) -> Path | None:
    current = path if path.is_dir() else path.parent
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def git_head(repo: Path) -> str | None:
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


def detect_git_object_format(repo: Path) -> str:
    """Return ``'sha256'`` or ``'sha1'`` for the object format of *repo*.

    Falls back to ``'sha1'`` on any error or when the command is unavailable
    (git < 2.29 does not support ``--show-object-format``).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-object-format"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            fmt = result.stdout.strip()
            if fmt in ("sha1", "sha256"):
                return fmt
    except Exception:
        pass
    return "sha1"


def gc_mail_objects(
    store_path: Path,
    *,
    dry_run: bool = True,
) -> dict:
    """Remove orphaned mail CAS objects (all producers reference deleted messages).

    Skips any CAS object that is still referenced by an inbox/ symlink so the
    core ``zkm gc`` keeps ownership of those.  Returns stats dict with keys
    ``orphaned``, ``deleted``, ``errors``, ``objects`` (list of candidate paths).
    """
    objects_dir = store_path / "mail" / "_objects"
    if not objects_dir.exists():
        return {"orphaned": 0, "deleted": 0, "errors": 0, "objects": []}

    # Build set of resolved CAS object paths still referenced by inbox symlinks
    inbox_targets: set[str] = set()
    inbox_dir = store_path / "inbox"
    if inbox_dir.exists():
        for link in inbox_dir.rglob("*"):
            if link.is_symlink():
                try:
                    inbox_targets.add(str(link.resolve()))
                except OSError:
                    pass

    orphaned_pairs: list[tuple[Path, Path]] = []
    errors = 0

    for sidecar_path in sorted(objects_dir.rglob("*.json")):
        obj_path = sidecar_path.with_suffix("")
        try:
            data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except Exception:
            errors += 1
            continue

        producers = data.get("producers", [])
        if producers:
            # Orphaned if every producer's message no longer exists in the store
            all_gone = all(
                not (store_path / p["message"]).exists()
                for p in producers
                if p.get("message")
            )
            if not all_gone:
                continue

        # Skip objects still referenced by an active inbox symlink
        if str(obj_path.resolve()) in inbox_targets:
            continue

        orphaned_pairs.append((obj_path, sidecar_path))

    deleted = 0
    if not dry_run:
        for obj_path, sidecar_path in orphaned_pairs:
            for p in (sidecar_path, obj_path):
                try:
                    p.unlink()
                    deleted += 1
                except FileNotFoundError:
                    pass

    return {
        "orphaned": len(orphaned_pairs),
        "deleted": deleted,
        "errors": errors,
        "objects": [str(op) for op, _ in orphaned_pairs],
    }


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
            merge_producer(
                cas_sidecar,
                sha256=sha,
                producer={"plugin": "eml", "message": msg_md_rel, "sha256": msg.sha256},
            )
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
