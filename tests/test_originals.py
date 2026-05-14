"""Tests for originals.py: git blob hashing, object-format detection, and GC."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from zkm.hashing import git_blob_hash_bytes, git_blob_sha1_bytes
from zkm_eml.originals import detect_git_object_format, gc_mail_objects


def test_blob_sha1_matches_git():
    data = b"Hello, world!\n"
    computed = git_blob_sha1_bytes(data)

    # Use git as oracle
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(data)
        tmp = f.name
    result = subprocess.run(
        ["git", "hash-object", tmp],
        capture_output=True,
        text=True,
    )
    git_hash = result.stdout.strip()
    Path(tmp).unlink()

    assert computed == git_hash


def test_blob_sha1_empty():
    data = b""
    computed = git_blob_sha1_bytes(data)

    with tempfile.NamedTemporaryFile(delete=False) as f:
        tmp = f.name
    result = subprocess.run(
        ["git", "hash-object", tmp],
        capture_output=True,
        text=True,
    )
    git_hash = result.stdout.strip()
    Path(tmp).unlink()

    assert computed == git_hash


def test_blob_sha1_eml_file():
    fixtures = Path(__file__).parent / "fixtures"
    for eml in fixtures.glob("*.eml"):
        data = eml.read_bytes()
        computed = git_blob_sha1_bytes(data)
        result = subprocess.run(
            ["git", "hash-object", str(eml)],
            capture_output=True,
            text=True,
        )
        git_hash = result.stdout.strip()
        assert computed == git_hash, f"Mismatch for {eml.name}"


# ---------------------------------------------------------------------------
# M6 — git_blob_hash_bytes + detect_git_object_format
# ---------------------------------------------------------------------------

def test_git_blob_hash_bytes_sha1_matches_sha1_bytes():
    data = b"test content\n"
    assert git_blob_hash_bytes(data, "sha1") == git_blob_sha1_bytes(data)


def test_git_blob_hash_bytes_sha1_default():
    data = b"abc"
    assert git_blob_hash_bytes(data) == git_blob_sha1_bytes(data)


def test_git_blob_hash_bytes_sha256():
    data = b"test content\n"
    prefix = f"blob {len(data)}\0".encode()
    expected = hashlib.sha256(prefix + data).hexdigest()
    assert git_blob_hash_bytes(data, "sha256") == expected


def test_git_blob_hash_bytes_sha256_empty():
    data = b""
    prefix = b"blob 0\0"
    expected = hashlib.sha256(prefix + data).hexdigest()
    assert git_blob_hash_bytes(data, "sha256") == expected


def test_detect_git_object_format_sha1_repo(tmp_path: Path):
    """A freshly inited git repo defaults to sha1."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    fmt = detect_git_object_format(tmp_path)
    assert fmt in ("sha1", "sha256")  # sha1 on most systems


def test_detect_git_object_format_not_git_returns_sha1(tmp_path: Path):
    fmt = detect_git_object_format(tmp_path)
    assert fmt == "sha1"


def test_detect_git_object_format_subprocess_error_returns_sha1(tmp_path: Path):
    with patch("subprocess.run", side_effect=OSError("no git")):
        fmt = detect_git_object_format(tmp_path)
    assert fmt == "sha1"


# ---------------------------------------------------------------------------
# M5 — gc_mail_objects
# ---------------------------------------------------------------------------

def _make_sidecar(path: Path, sha: str, producers: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"sha256": sha, "producers": producers}
    path.write_text(json.dumps(data))


def _make_obj(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"payload")


def test_gc_mail_objects_empty_dir(tmp_path: Path):
    result = gc_mail_objects(tmp_path)
    assert result == {"orphaned": 0, "deleted": 0, "errors": 0, "objects": []}


def test_gc_mail_objects_no_objects_dir(tmp_path: Path):
    result = gc_mail_objects(tmp_path)
    assert result["orphaned"] == 0


def test_gc_mail_objects_healthy_producer(tmp_path: Path):
    """Sidecar whose producer message exists — not orphaned."""
    # Create the referenced message
    msg_path = tmp_path / "mail" / "messages" / "2024" / "01" / "msg.md"
    msg_path.parent.mkdir(parents=True, exist_ok=True)
    msg_path.write_text("content")

    sha = "ab" + "0" * 62
    obj_path = tmp_path / "mail" / "_objects" / sha[:2] / sha[2:]
    sidecar_path = obj_path.with_name(obj_path.name + ".json")
    _make_obj(obj_path)
    _make_sidecar(sidecar_path, sha, [{"plugin": "eml", "message": "mail/messages/2024/01/msg.md"}])

    result = gc_mail_objects(tmp_path)
    assert result["orphaned"] == 0
    assert obj_path.exists()


def test_gc_mail_objects_orphaned_dry_run(tmp_path: Path):
    """Sidecar whose producer message is gone — orphaned, but dry_run keeps files."""
    sha = "cd" + "0" * 62
    obj_path = tmp_path / "mail" / "_objects" / sha[:2] / sha[2:]
    sidecar_path = obj_path.with_name(obj_path.name + ".json")
    _make_obj(obj_path)
    _make_sidecar(sidecar_path, sha, [{"plugin": "eml", "message": "mail/messages/gone.md"}])

    result = gc_mail_objects(tmp_path, dry_run=True)
    assert result["orphaned"] == 1
    assert result["deleted"] == 0
    assert obj_path.exists()
    assert sidecar_path.exists()


def test_gc_mail_objects_orphaned_apply(tmp_path: Path):
    """Apply mode removes orphaned CAS object and sidecar."""
    sha = "ef" + "0" * 62
    obj_path = tmp_path / "mail" / "_objects" / sha[:2] / sha[2:]
    sidecar_path = obj_path.with_name(obj_path.name + ".json")
    _make_obj(obj_path)
    _make_sidecar(sidecar_path, sha, [{"plugin": "eml", "message": "mail/messages/gone.md"}])

    result = gc_mail_objects(tmp_path, dry_run=False)
    assert result["orphaned"] == 1
    assert result["deleted"] == 2
    assert not obj_path.exists()
    assert not sidecar_path.exists()


def test_gc_mail_objects_skips_inbox_referenced(tmp_path: Path):
    """Orphaned by message but still referenced by inbox symlink — not removed."""
    sha = "12" + "0" * 62
    obj_path = tmp_path / "mail" / "_objects" / sha[:2] / sha[2:]
    sidecar_path = obj_path.with_name(obj_path.name + ".json")
    _make_obj(obj_path)
    _make_sidecar(sidecar_path, sha, [{"plugin": "eml", "message": "mail/messages/gone.md"}])

    # Create an inbox symlink pointing at the CAS object
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    link = inbox_dir / "attachment.pdf"
    link.symlink_to(obj_path)

    result = gc_mail_objects(tmp_path, dry_run=False)
    assert result["orphaned"] == 0
    assert obj_path.exists()


def test_gc_mail_objects_empty_producers(tmp_path: Path):
    """Sidecar with empty producers list is also orphaned."""
    sha = "34" + "0" * 62
    obj_path = tmp_path / "mail" / "_objects" / sha[:2] / sha[2:]
    sidecar_path = obj_path.with_name(obj_path.name + ".json")
    _make_obj(obj_path)
    _make_sidecar(sidecar_path, sha, [])

    result = gc_mail_objects(tmp_path, dry_run=False)
    assert result["orphaned"] == 1
    assert not obj_path.exists()


def test_gc_mail_objects_corrupt_sidecar(tmp_path: Path):
    """Corrupt JSON sidecar increments errors counter and is not deleted."""
    obj_dir = tmp_path / "mail" / "_objects" / "ab"
    obj_dir.mkdir(parents=True)
    sidecar_path = obj_dir / "baddata.json"
    sidecar_path.write_text("not json{{{")

    result = gc_mail_objects(tmp_path)
    assert result["errors"] == 1
    assert result["orphaned"] == 0
