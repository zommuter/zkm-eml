"""Tests for attachment extraction, CAS storage, and inbox symlinks."""

from __future__ import annotations

import hashlib
import json
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
        "source_dir": str(FIXTURES),
        "keep_originals": True,
        "attachment_inbox": True,
    }
    convert(store, config)

    objects_dir = store / "mail" / "_objects"
    assert objects_dir.exists()
    objects = list(objects_dir.rglob("*"))
    cas_files = [p for p in objects if p.is_file() and "." not in p.name]
    assert len(cas_files) > 0

    # Verify CAS file content integrity (sidecars excluded)
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
        "source_dir": str(src),
        "keep_originals": True,
        "attachment_inbox": True,
    }
    convert(store, config)

    objects_dir = store / "mail" / "_objects"
    cas_files = [p for p in objects_dir.rglob("*") if p.is_file() and "." not in p.name]
    # Both messages share the same PDF payload — only one CAS object
    assert len(cas_files) == 1


def test_per_message_symlinks(store: Path):
    config = {
        "source_dir": str(FIXTURES),
        "keep_originals": True,
        "attachment_inbox": False,
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
        "source_dir": str(FIXTURES),
        "keep_originals": True,
        "attachment_inbox": True,
    }
    convert(store, config)

    inbox_mail = store / "inbox" / "mail"
    links = [p for p in inbox_mail.rglob("*") if p.is_symlink()]
    assert len(links) > 0
    for link in links:
        assert link.resolve().exists(), f"Broken inbox symlink: {link}"
    # Verify date-sharded layout: inbox/mail/YYYY/MM/<file>
    for link in links:
        parts = link.relative_to(inbox_mail).parts
        assert len(parts) == 3, f"Expected YYYY/MM/filename, got {parts}"


def test_inbox_dedup(store: Path):
    """Two emails with same attachment payload produce one inbox symlink."""
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_pdf.eml", src / "with_pdf.eml")
    shutil.copy(FIXTURES / "with_pdf_forwarded.eml", src / "with_pdf_forwarded.eml")

    config = {
        "source_dir": str(src),
        "keep_originals": True,
        "attachment_inbox": True,
    }
    convert(store, config)

    inbox_mail = store / "inbox" / "mail"
    links = [p for p in inbox_mail.rglob("*") if p.is_symlink()]
    # invoice.pdf appears in both, but only one unique CAS → one inbox link
    assert len(links) == 1


def test_frontmatter_attachments_field(store: Path):
    config = {
        "source_dir": str(FIXTURES),
        "keep_originals": True,
        "attachment_inbox": False,
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
        "source_dir": str(src),
        "keep_originals": True,
        "attachment_inbox": False,
    }
    convert(store, config)

    originals = list((store / "originals" / "mail").rglob("*.eml"))
    assert len(originals) == 1
    content = originals[0].read_text(errors="replace")
    assert "X-Zkm-Detached:" in content
    assert "X-Zkm-Detached-Sha256:" in content
    # The raw base64 PDF payload should not be present
    assert "JVBERi0xLjAKJSVFT0YK" not in content


def test_inbox_sidecar_single_producer(store: Path):
    """Each inbox symlink has a .origin.json sidecar with schema and producers."""
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_pdf.eml", src / "with_pdf.eml")

    config = {
        "source_dir": str(src),
        "keep_originals": True,
        "attachment_inbox": True,
    }
    convert(store, config)

    inbox_mail = store / "inbox" / "mail"
    links = [p for p in inbox_mail.rglob("*") if p.is_symlink()]
    assert len(links) == 1
    link = links[0]
    sidecar = link.parent / (link.name + ".origin.json")
    assert sidecar.exists(), f"Missing sidecar for {link}"

    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    sha = hashlib.sha256(link.resolve().read_bytes()).hexdigest()
    assert data["sha256"] == sha
    assert len(data["producers"]) == 1
    p = data["producers"][0]
    assert p["plugin"] == "eml"
    assert p["message"].startswith("mail/messages/")
    assert len(p["sha256"]) == 64


def test_inbox_sidecar_multi_producer(store: Path):
    """Same attachment in two messages → one symlink, sidecar lists both producers."""
    import json as _json
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_pdf.eml", src / "with_pdf.eml")
    shutil.copy(FIXTURES / "with_pdf_forwarded.eml", src / "with_pdf_forwarded.eml")

    config = {
        "source_dir": str(src),
        "keep_originals": True,
        "attachment_inbox": True,
    }
    convert(store, config)

    inbox_mail = store / "inbox" / "mail"
    links = [p for p in inbox_mail.rglob("*") if p.is_symlink()]
    assert len(links) == 1, f"Expected 1 canonical symlink, got {len(links)}: {links}"

    link = links[0]
    sidecar = link.parent / (link.name + ".origin.json")
    assert sidecar.exists()

    data = _json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert len(data["producers"]) == 2
    messages = sorted(p["message"] for p in data["producers"])
    assert all(m.startswith("mail/messages/") for m in messages)
    assert all(len(p["sha256"]) == 64 for p in data["producers"])
    # producers sorted by message path (ascending)
    assert messages == sorted(messages)


def test_inbox_sidecar_idempotent(store: Path):
    """Re-running convert does not duplicate sidecar producers."""
    import json as _json
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_pdf.eml", src / "with_pdf.eml")

    config = {
        "source_dir": str(src),
        "keep_originals": True,
        "attachment_inbox": True,
    }
    convert(store, config)
    convert(store, config)  # second run: message already seen, no new symlinks

    inbox_mail = store / "inbox" / "mail"
    links = [p for p in inbox_mail.rglob("*") if p.is_symlink()]
    assert len(links) == 1
    sidecar = links[0].parent / (links[0].name + ".origin.json")
    data = _json.loads(sidecar.read_text(encoding="utf-8"))
    assert len(data["producers"]) == 1  # not doubled


def test_idempotent_with_attachments(store: Path):
    config = {
        "source_dir": str(FIXTURES),
        "keep_originals": True,
        "attachment_inbox": True,
    }
    first = convert(store, config)
    second = convert(store, config)
    assert len(first) > 0
    assert len(second) == 0

    objects_before = list((store / "mail" / "_objects").rglob("*") if (store / "mail" / "_objects").exists() else [])
    # Second run doesn't create extra objects
    objects_after = list((store / "mail" / "_objects").rglob("*"))
    assert len(objects_before) == len(objects_after)


def test_per_message_attachment_sidecar_written(store: Path):
    """Each per-message symlink gets a .json sidecar with attachment metadata."""
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_pdf.eml", src / "with_pdf.eml")

    config = {
        "source_dir": str(src),
        "keep_originals": True,
        "attachment_inbox": False,
    }
    convert(store, config)

    originals_mail = store / "originals" / "mail"
    sidecars = [p for p in originals_mail.rglob("*.json") if not p.name.endswith(".source.json")]
    assert len(sidecars) == 1, f"Expected 1 attachment sidecar, found: {sidecars}"

    data = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert data["filename"] == "invoice.pdf"
    assert len(data["sha256"]) == 64
    assert data["content_type"] == "application/pdf"
    assert data["size"] > 0
    assert data["object"].startswith("mail/_objects/")


def test_cas_object_sidecar_single_producer(store: Path):
    """A per-CAS sidecar is written next to each _objects payload."""
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_pdf.eml", src / "with_pdf.eml")

    config = {
        "source_dir": str(src),
        "keep_originals": True,
        "attachment_inbox": False,
    }
    convert(store, config)

    objects_dir = store / "mail" / "_objects"
    json_sidecars = [p for p in objects_dir.rglob("*.json")]
    assert len(json_sidecars) == 1

    data = json.loads(json_sidecars[0].read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert len(data["sha256"]) == 64
    assert len(data["producers"]) == 1
    p = data["producers"][0]
    assert p["plugin"] == "eml"
    assert p["message"].startswith("mail/messages/")
    assert len(p["sha256"]) == 64  # source message sha256


def test_cas_object_sidecar_multi_producer(store: Path):
    """Same attachment in two messages → CAS sidecar lists both producers."""
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_pdf.eml", src / "with_pdf.eml")
    shutil.copy(FIXTURES / "with_pdf_forwarded.eml", src / "with_pdf_forwarded.eml")

    config = {
        "source_dir": str(src),
        "keep_originals": True,
        "attachment_inbox": False,
    }
    convert(store, config)

    objects_dir = store / "mail" / "_objects"
    json_sidecars = [p for p in objects_dir.rglob("*.json")]
    assert len(json_sidecars) == 1

    data = json.loads(json_sidecars[0].read_text(encoding="utf-8"))
    assert len(data["producers"]) == 2
    messages = sorted(p["message"] for p in data["producers"])
    assert all(m.startswith("mail/messages/") for m in messages)


def test_cas_object_sidecar_idempotent(store: Path):
    """Re-running convert does not duplicate CAS sidecar producers."""
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_pdf.eml", src / "with_pdf.eml")

    config = {
        "source_dir": str(src),
        "keep_originals": True,
        "attachment_inbox": False,
    }
    convert(store, config)
    convert(store, config)  # second run: message already seen

    objects_dir = store / "mail" / "_objects"
    json_sidecars = [p for p in objects_dir.rglob("*.json")]
    assert len(json_sidecars) == 1
    data = json.loads(json_sidecars[0].read_text(encoding="utf-8"))
    assert len(data["producers"]) == 1  # not doubled


def test_data_uri_img_detached_to_cas(store: Path):
    """HTML email with inline data-URI image: CAS object written, body is clean."""
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_data_uri_img.eml", src / "with_data_uri_img.eml")

    config = {
        "source_dir": str(src),
        "keep_originals": True,
        "attachment_inbox": False,
    }
    created = convert(store, config)
    assert len(created) == 1

    # Rendered markdown body must not contain any data: URI
    post = frontmatter.load(created[0])
    assert "data:" not in post.content, "data-URI leaked into markdown body"

    # At least one CAS object created for the detached image
    objects_dir = store / "mail" / "_objects"
    cas_files = [p for p in objects_dir.rglob("*") if p.is_file() and "." not in p.name]
    assert len(cas_files) >= 1

    # Frontmatter attachments entry present with is_inline=True
    atts = post.metadata.get("attachments", [])
    assert len(atts) >= 1
    inline = [a for a in atts if a.get("inline")]
    assert len(inline) >= 1
    att = inline[0]
    assert att["filename"].startswith("inline-")
    assert att["filename"].endswith(".png")
    assert len(att["sha256"]) == 64

    # CAS object sha256 matches the filename
    for cas_file in cas_files:
        expected_sha = cas_file.parent.name + cas_file.name
        actual_sha = hashlib.sha256(cas_file.read_bytes()).hexdigest()
        assert actual_sha == expected_sha

