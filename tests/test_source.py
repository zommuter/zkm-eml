"""Tests for source.py: Maildir + .eml iteration with folder pruning."""

from __future__ import annotations

from pathlib import Path

from zkm_eml.source import default_exclude_folders, iter_messages

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
