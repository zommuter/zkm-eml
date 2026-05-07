"""Tests for source.py: Maildir + .eml iteration with folder pruning."""

from __future__ import annotations

import subprocess
from pathlib import Path

from zkm_eml.source import default_exclude_folders, iter_messages, iter_messages_since

FIXTURES = Path(__file__).parent / "fixtures"
MAILDIR = FIXTURES / "maildir"


def test_maildir_messages_found():
    msgs = list(iter_messages(MAILDIR, default_exclude_folders()))
    names = [p.name for p in msgs]
    assert "1746000000.M0P0.testhost" in names


def test_trash_excluded_by_default():
    msgs = list(iter_messages(MAILDIR, default_exclude_folders()))
    # Trash message must not appear
    assert not any("Trash" in str(p) for p in msgs)


def test_trash_included_when_no_exclusion():
    msgs = list(iter_messages(MAILDIR, []))
    assert any("Trash" in str(p) for p in msgs)


def test_tmp_always_skipped():
    # Write a file in tmp/ and confirm it is never yielded
    tmp_file = MAILDIR / "account1" / "INBOX" / "tmp" / "partial.msg"
    tmp_file.write_text("From: x\nSubject: y\n\nBody")
    try:
        msgs = list(iter_messages(MAILDIR, []))
        assert tmp_file not in msgs
    finally:
        tmp_file.unlink(missing_ok=True)


def test_flat_eml_files_found():
    msgs = list(iter_messages(FIXTURES, default_exclude_folders()))
    eml_names = [p.name for p in msgs if p.suffix == ".eml"]
    assert "simple.eml" in eml_names
    assert "with_pdf.eml" in eml_names


def test_no_dotfiles_yielded():
    msgs = list(iter_messages(FIXTURES, []))
    assert not any(p.name.startswith(".") for p in msgs)


# ---------------------------------------------------------------------------
# iter_messages_since (git-commit watermark)
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _commit_all(repo: Path, msg: str = "test commit") -> str:
    _git(["add", "-A"], repo)
    _git(["commit", "--allow-empty", "-m", msg], repo)
    return _git(["rev-parse", "HEAD"], repo)


def _make_src_repo(tmp_path: Path) -> Path:
    """Create a bare git repo in tmp_path to act as an EML source."""
    src = tmp_path / "src"
    src.mkdir()
    _git(["init"], src)
    _git(["config", "user.email", "test@test.com"], src)
    _git(["config", "user.name", "Test"], src)
    return src


def _write_eml(src: Path, name: str = "msg.eml") -> Path:
    p = src / name
    p.write_bytes(b"From: a@b.com\r\nTo: c@d.com\r\nSubject: Test\r\n\r\nBody")
    return p


def test_iter_messages_since_full_fallback_when_no_git(tmp_path: Path) -> None:
    """When source is not a git repo, falls back to iter_messages (fast_path=False)."""
    src = tmp_path / "plain_dir"
    src.mkdir()
    # Create an inbox .eml
    (src / "a.eml").write_bytes(b"From: a@b\r\nSubject: Hi\r\n\r\nHi")

    paths, fast = iter_messages_since(src, [], src, "deadbeef" * 5)
    assert fast is False
    assert any(p.name == "a.eml" for p in paths)


def test_iter_messages_since_fast_path_picks_up_new_eml(tmp_path: Path) -> None:
    """New .eml committed after watermark is returned by fast path."""
    src = _make_src_repo(tmp_path)
    sha1 = _commit_all(src, "init")

    _write_eml(src, "new.eml")
    _commit_all(src, "add eml")

    paths, fast = iter_messages_since(src, [], src, sha1)
    assert fast is True
    assert any(p.name == "new.eml" for p in paths)


def test_iter_messages_since_fast_path_empty_when_no_change(tmp_path: Path) -> None:
    """When watermark == HEAD, no new files are returned."""
    src = _make_src_repo(tmp_path)
    _write_eml(src, "old.eml")
    sha1 = _commit_all(src, "add old eml")

    paths, fast = iter_messages_since(src, [], src, sha1)
    assert fast is True
    assert len(paths) == 0


def test_iter_messages_since_includes_dirty_working_tree(tmp_path: Path) -> None:
    """Uncommitted (dirty) .eml file is included via git status."""
    src = _make_src_repo(tmp_path)
    sha1 = _commit_all(src, "init")

    _write_eml(src, "dirty.eml")  # NOT committed

    paths, fast = iter_messages_since(src, [], src, sha1)
    assert fast is True
    assert any(p.name == "dirty.eml" for p in paths)


def test_iter_messages_since_unreachable_watermark_falls_back(tmp_path: Path) -> None:
    """Bogus watermark SHA causes full-scan fallback."""
    src = _make_src_repo(tmp_path)
    _write_eml(src, "a.eml")
    _commit_all(src, "add a")

    paths, fast = iter_messages_since(src, [], src, "badc0de" * 5)
    assert fast is False
    assert any(p.name == "a.eml" for p in paths)
