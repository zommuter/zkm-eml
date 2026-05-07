"""Tests for originals.py: git_blob_sha1 correctness."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from zkm.hashing import git_blob_sha1_bytes


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
