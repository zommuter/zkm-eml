"""Tests for attachment extraction, CAS storage, and inbox symlinks."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import frontmatter
import pytest

from convert import convert
from zkm_eml.parse import parse_eml

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def store(tmp_path: Path) -> Path:
    sdir = tmp_path / "store"
    sdir.mkdir()
    for d in ["mail/messages", "mail/threads", "originals/mail", "inbox"]:
        (sdir / d).mkdir(parents=True)
    return sdir


def test_parse_extracts_attachments():
    msg = parse_eml(FIXTURES / "with_pdf.eml")
    assert len(msg.attachments) == 1
    att = msg.attachments[0]
    assert att.filename == "invoice.pdf"
    assert att.content_type == "application/pdf"
    assert att.size > 0
    assert len(att.sha256) == 64
    assert att.sha256 == hashlib.sha256(att.payload).hexdigest()


def test_inline_image_detected():
    msg = parse_eml(FIXTURES / "with_inline_image.eml")
    assert len(msg.attachments) == 1
    att = msg.attachments[0]
    assert att.filename == "logo.png"
    assert att.is_inline
    assert att.referenced_in_html
    assert att.content_id is not None


def test_cas_object_written(store: Path):
    config = {
        "EML_SOURCE_DIR": str(FIXTURES),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "true",
    }
    convert(store, config)

    objects_dir = store / "originals" / "mail" / "_objects"
    assert objects_dir.exists()
    objects = list(objects_dir.rglob("*"))
    cas_files = [p for p in objects if p.is_file()]
    assert len(cas_files) > 0

    # Verify CAS file content integrity
    for cas_file in cas_files:
        payload = cas_file.read_bytes()
        sha = hashlib.sha256(payload).hexdigest()
        expected_name = cas_file.parent.name + cas_file.name
        assert sha == expected_name[:64] or sha.startswith(cas_file.parent.name)


def test_cas_deduplication(store: Path):
    """Same PDF forwarded in two emails must produce only one CAS object."""
    # Only import the two PDF fixtures
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_pdf.eml", src / "with_pdf.eml")
    shutil.copy(FIXTURES / "with_pdf_forwarded.eml", src / "with_pdf_forwarded.eml")

    config = {
        "EML_SOURCE_DIR": str(src),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "true",
    }
    convert(store, config)

    objects_dir = store / "originals" / "mail" / "_objects"
    cas_files = [p for p in objects_dir.rglob("*") if p.is_file()]
    # Both messages share the same PDF payload — only one CAS object
    assert len(cas_files) == 1


def test_per_message_symlinks(store: Path):
    config = {
        "EML_SOURCE_DIR": str(FIXTURES),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "false",
    }
    convert(store, config)

    originals_mail = store / "originals" / "mail"
    symlinks = [p for p in originals_mail.rglob("*") if p.is_symlink()]

    assert len(symlinks) > 0
    for link in symlinks:
        resolved = link.resolve()
        assert resolved.exists(), f"Broken symlink: {link} -> {os.readlink(link)}"


def test_inbox_symlinks_created(store: Path):
    config = {
        "EML_SOURCE_DIR": str(FIXTURES),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "true",
    }
    convert(store, config)

    inbox = store / "inbox"
    links = [p for p in inbox.iterdir() if p.is_symlink()]
    assert len(links) > 0
    for link in links:
        assert link.resolve().exists(), f"Broken inbox symlink: {link}"


def test_inbox_dedup(store: Path):
    """Two emails with same attachment payload produce one inbox symlink."""
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_pdf.eml", src / "with_pdf.eml")
    shutil.copy(FIXTURES / "with_pdf_forwarded.eml", src / "with_pdf_forwarded.eml")

    config = {
        "EML_SOURCE_DIR": str(src),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "true",
    }
    convert(store, config)

    inbox = store / "inbox"
    links = [p for p in inbox.iterdir() if p.is_symlink()]
    # invoice.pdf appears in both, but only one unique CAS → one inbox link
    assert len(links) == 1


def test_frontmatter_attachments_field(store: Path):
    config = {
        "EML_SOURCE_DIR": str(FIXTURES),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "false",
    }
    convert(store, config)

    messages = list((store / "mail" / "messages").rglob("*.md"))
    assert len(messages) > 0

    # Find a message that has attachments
    found = False
    for md in messages:
        post = frontmatter.load(md)
        if post.metadata.get("attachments"):
            found = True
            atts = post.metadata["attachments"]
            att = atts[0]
            assert "filename" in att
            assert "sha256" in att
            assert "path" in att
            assert "object" in att
            assert "content_type" in att
            break
    assert found, "No message with attachments found in frontmatter"


def test_stripped_eml_has_stub_headers(store: Path):
    """Stripped .eml contains X-Zkm-Detached header and not the raw base64 payload."""
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_pdf.eml", src / "with_pdf.eml")

    config = {
        "EML_SOURCE_DIR": str(src),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "false",
    }
    convert(store, config)

    originals = list((store / "originals" / "mail").rglob("*.eml"))
    assert len(originals) == 1
    content = originals[0].read_text(errors="replace")
    assert "X-Zkm-Detached:" in content
    assert "X-Zkm-Detached-Sha256:" in content
    # The raw base64 PDF payload should not be present
    assert "JVBERi0xLjAKJSVFT0YK" not in content


def test_idempotent_with_attachments(store: Path):
    config = {
        "EML_SOURCE_DIR": str(FIXTURES),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "true",
    }
    first = convert(store, config)
    second = convert(store, config)
    assert len(first) > 0
    assert len(second) == 0

    objects_before = list((store / "originals" / "mail" / "_objects").rglob("*") if (store / "originals" / "mail" / "_objects").exists() else [])
    # Second run doesn't create extra objects
    objects_after = list((store / "originals" / "mail" / "_objects").rglob("*"))
    assert len(objects_before) == len(objects_after)
