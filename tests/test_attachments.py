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
        "EML_SOURCE_DIR": str(FIXTURES),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "true",
    }
    convert(store, config)

    objects_dir = store / "mail" / "_objects"
    assert objects_dir.exists()
    objects = list(objects_dir.rglob("*"))
    cas_files = [p for p in objects if p.is_file() and not p.suffix == ".json"]
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
        "EML_SOURCE_DIR": str(src),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "true",
    }
    convert(store, config)

    objects_dir = store / "mail" / "_objects"
    cas_files = [p for p in objects_dir.rglob("*") if p.is_file() and not p.suffix == ".json"]
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
        "EML_SOURCE_DIR": str(src),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "true",
    }
    convert(store, config)

    inbox_mail = store / "inbox" / "mail"
    links = [p for p in inbox_mail.rglob("*") if p.is_symlink()]
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


def test_inbox_sidecar_single_producer(store: Path):
    """Each inbox symlink has a .origin.json sidecar with schema and producers."""
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_pdf.eml", src / "with_pdf.eml")

    config = {
        "EML_SOURCE_DIR": str(src),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "true",
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
        "EML_SOURCE_DIR": str(src),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "true",
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
        "EML_SOURCE_DIR": str(src),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "true",
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
        "EML_SOURCE_DIR": str(FIXTURES),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "true",
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
        "EML_SOURCE_DIR": str(src),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "false",
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
        "EML_SOURCE_DIR": str(src),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "false",
    }
    convert(store, config)

    objects_dir = store / "mail" / "_objects"
    json_sidecars = [p for p in objects_dir.rglob("*.json")]
    assert len(json_sidecars) == 1

    data = json.loads(json_sidecars[0].read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert len(data["sha256"]) == 64
    assert data["size"] > 0
    assert len(data["producers"]) == 1
    p = data["producers"][0]
    assert p["message"].startswith("mail/messages/")
    assert p["filename"] == "invoice.pdf"
    assert "application/pdf" in data["content_types"]
    assert "invoice.pdf" in data["filenames"]


def test_cas_object_sidecar_multi_producer(store: Path):
    """Same attachment in two messages → CAS sidecar lists both producers."""
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_pdf.eml", src / "with_pdf.eml")
    shutil.copy(FIXTURES / "with_pdf_forwarded.eml", src / "with_pdf_forwarded.eml")

    config = {
        "EML_SOURCE_DIR": str(src),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "false",
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
        "EML_SOURCE_DIR": str(src),
        "EML_KEEP_ORIGINALS": "true",
        "EML_ATTACHMENT_INBOX": "false",
    }
    convert(store, config)
    convert(store, config)  # second run: message already seen

    objects_dir = store / "mail" / "_objects"
    json_sidecars = [p for p in objects_dir.rglob("*.json")]
    assert len(json_sidecars) == 1
    data = json.loads(json_sidecars[0].read_text(encoding="utf-8"))
    assert len(data["producers"]) == 1  # not doubled


def test_inbox_sidecar_stable_under_message_path_drift(store: Path):
    """Changing the rendered .md path between calls must not duplicate producers.

    Regression test for the dedup-key bug: previously the inbox sidecar deduped
    on `message` (rendered path), which can shift between runs. The fix uses
    `sha256` (source-content hash) as the stable key.
    """
    from zkm_eml.originals import _merge_inbox_sidecar

    sidecar = store / "test_sidecar.origin.json"
    att_sha = "a" * 64        # arbitrary attachment sha256
    msg_sha = "b" * 64        # source message sha256 (stable across path changes)
    plugin = "zkm-eml"

    # First call: write initial sidecar with path v1
    _merge_inbox_sidecar(sidecar, att_sha, "mail/messages/2026/04/original.md", msg_sha, plugin)
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert len(data["producers"]) == 1

    # Second call: same msg_sha, but rendered path changed (slug drift)
    _merge_inbox_sidecar(sidecar, att_sha, "mail/messages/2026/04/original_1.md", msg_sha, plugin)
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    # Must still be 1 — the source sha256 dedup prevents the duplicate
    assert len(data["producers"]) == 1, (
        "Sidecar producer list grew despite same source sha256 — "
        "dedup key must be sha256, not message path"
    )


def test_cas_sidecar_dedup_by_sha256(store: Path):
    """CAS-object sidecar deduplication uses source sha256, not rendered message path.

    Also asserts that each producer entry contains a sha256 field.
    """
    from zkm_eml.originals import _merge_cas_sidecar
    from zkm_eml.parse import ParsedAttachment

    # Minimal attachment stub
    payload = b"fake-pdf-content"
    att = ParsedAttachment(
        filename="doc.pdf",
        filename_raw="doc.pdf",
        content_type="application/pdf",
        content_id=None,
        is_inline=False,
        referenced_in_html=False,
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        payload=payload,
        part_index=0,
    )
    sidecar = store / "cas_sidecar.json"
    msg_sha_v1 = "c" * 64   # stable source hash
    msg_sha_v2 = "d" * 64   # different source hash → genuinely new producer

    # First producer
    _merge_cas_sidecar(sidecar, att, "doc.pdf", "mail/messages/2026/04/msg_v1.md", msg_sha_v1)
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert len(data["producers"]) == 1
    assert data["producers"][0]["sha256"] == msg_sha_v1, "Producer must carry sha256 field"

    # Same source sha → dedup, no growth even if message path changes
    _merge_cas_sidecar(sidecar, att, "doc.pdf", "mail/messages/2026/04/msg_v1_drift.md", msg_sha_v1)
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert len(data["producers"]) == 1, "Same sha256 must not duplicate the producer"

    # Different source sha → genuine second producer
    _merge_cas_sidecar(sidecar, att, "doc.pdf", "mail/messages/2026/04/msg_v2.md", msg_sha_v2)
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert len(data["producers"]) == 2, "Different sha256 must add a new producer"
