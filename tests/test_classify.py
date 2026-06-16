"""M1 (id:ff0f) — decoration vs inline-photo attachment classification, census mode.

The classifier labels every attachment ``decoration | content | unknown`` and
threads that label into frontmatter + sidecars. It is census-FIRST: the
``decoration`` inbox-fan-out gate defaults to ON (unchanged behaviour), so the
labels are gathered for distribution evidence before any default flips.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import frontmatter
import pytest

from convert import convert
from zkm_eml.classify import classify_attachment
from zkm_eml.parse import ParsedAttachment

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def store(tmp_path: Path) -> Path:
    sdir = tmp_path / "store"
    sdir.mkdir()
    for d in ["mail/messages", "mail/threads", "originals/mail", "inbox"]:
        (sdir / d).mkdir(parents=True)
    return sdir


def _att(**over) -> ParsedAttachment:
    base = ParsedAttachment(
        filename="x.bin",
        filename_raw="x.bin",
        content_type="application/octet-stream",
        content_id=None,
        is_inline=False,
        referenced_in_html=False,
        size=10_000,
        sha256="0" * 64,
        payload=b"x" * 10_000,
        part_index=0,
    )
    return replace(base, **over)


# --- pure classifier --------------------------------------------------------

def test_small_inline_cid_image_is_decoration():  # roadmap:ff0f
    att = _att(content_type="image/png", is_inline=True, referenced_in_html=True, size=3_000)
    assert classify_attachment(att) == "decoration"


def test_tracking_pixel_is_decoration_even_if_not_inline():  # roadmap:ff0f
    att = _att(content_type="image/gif", is_inline=False, referenced_in_html=False, size=43)
    assert classify_attachment(att) == "decoration"


def test_pdf_is_content():  # roadmap:ff0f
    att = _att(content_type="application/pdf", size=200_000)
    assert classify_attachment(att) == "content"


def test_large_standalone_image_is_content():  # roadmap:ff0f
    att = _att(content_type="image/jpeg", is_inline=False, referenced_in_html=False, size=2_000_000)
    assert classify_attachment(att) == "content"


def test_midsize_inline_image_is_unknown():  # roadmap:ff0f
    # Above the decoration ceiling but inline+cid — ambiguous, census observes it.
    att = _att(content_type="image/png", is_inline=True, referenced_in_html=True, size=120_000)
    assert classify_attachment(att) == "unknown"


def test_classification_value_is_always_valid():  # roadmap:ff0f
    for ct, sz, inl, ref in [
        ("image/png", 0, True, True),
        ("application/pdf", 0, False, False),
        ("image/png", 70_000, False, False),
    ]:
        att = _att(content_type=ct, size=sz, is_inline=inl, referenced_in_html=ref)
        assert classify_attachment(att) in ("decoration", "content", "unknown")


# --- frontmatter + sidecar census fields ------------------------------------

def test_frontmatter_attachment_has_classification(store: Path):  # roadmap:ff0f
    config = {"source_dir": str(FIXTURES), "keep_originals": True, "attachment_inbox": False}
    convert(store, config)

    found = False
    for md in (store / "mail" / "messages").rglob("*.md"):
        post = frontmatter.load(md)
        for att in post.metadata.get("attachments", []) or []:
            assert att.get("classification") in ("decoration", "content", "unknown")
            found = True
    assert found, "no attachment with a classification field found"


def test_logo_classified_decoration_in_frontmatter(store: Path):  # roadmap:ff0f
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_inline_image.eml", src / "with_inline_image.eml")
    config = {"source_dir": str(src), "keep_originals": True, "attachment_inbox": False}
    convert(store, config)

    md = next((store / "mail" / "messages").rglob("*.md"))
    post = frontmatter.load(md)
    atts = post.metadata["attachments"]
    assert len(atts) == 1
    assert atts[0]["filename"] == "logo.png"
    assert atts[0]["classification"] == "decoration"


def test_pdf_classified_content_in_frontmatter(store: Path):  # roadmap:ff0f
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_pdf.eml", src / "with_pdf.eml")
    config = {"source_dir": str(src), "keep_originals": True, "attachment_inbox": False}
    convert(store, config)

    md = next((store / "mail" / "messages").rglob("*.md"))
    post = frontmatter.load(md)
    atts = post.metadata["attachments"]
    assert atts[0]["filename"] == "invoice.pdf"
    assert atts[0]["classification"] == "content"


def test_per_message_sidecar_has_classification(store: Path):  # roadmap:ff0f
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_inline_image.eml", src / "with_inline_image.eml")
    config = {"source_dir": str(src), "keep_originals": True, "attachment_inbox": False}
    convert(store, config)

    originals_mail = store / "originals" / "mail"
    sidecars = [p for p in originals_mail.rglob("*.json") if not p.name.endswith(".source.json")]
    assert len(sidecars) == 1
    data = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert data["classification"] == "decoration"


# --- config-gated fan-out, census default = unchanged -----------------------

def test_decoration_fans_out_by_default(store: Path):  # roadmap:ff0f
    """Census mode: decoration still fans out to inbox by default (no behaviour flip)."""
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_inline_image.eml", src / "with_inline_image.eml")
    config = {"source_dir": str(src), "keep_originals": True, "attachment_inbox": True}
    convert(store, config)

    links = [p for p in (store / "inbox" / "mail").rglob("*") if p.is_symlink()]
    assert len(links) == 1  # the logo IS fanned out — default unchanged


def test_decoration_fanout_can_be_gated_off(store: Path):  # roadmap:ff0f
    """When decoration_fanout=False, decoration attachments are kept in CAS but not inboxed."""
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_inline_image.eml", src / "with_inline_image.eml")
    config = {
        "source_dir": str(src),
        "keep_originals": True,
        "attachment_inbox": True,
        "decoration_fanout": False,
    }
    convert(store, config)

    # No inbox symlink for the decoration logo …
    links = [p for p in (store / "inbox" / "mail").rglob("*") if p.is_symlink()]
    assert len(links) == 0
    # … but the CAS object is still preserved (never lost).
    cas = [p for p in (store / "mail" / "_objects").rglob("*") if p.is_file() and "." not in p.name]
    assert len(cas) >= 1


def test_content_still_fans_out_when_decoration_gated(store: Path):  # roadmap:ff0f
    """Gating decoration must not suppress real content (pdf) fan-out."""
    import shutil
    src = store.parent / "eml_src"
    src.mkdir()
    shutil.copy(FIXTURES / "with_pdf.eml", src / "with_pdf.eml")
    config = {
        "source_dir": str(src),
        "keep_originals": True,
        "attachment_inbox": True,
        "decoration_fanout": False,
    }
    convert(store, config)

    links = [p for p in (store / "inbox" / "mail").rglob("*") if p.is_symlink()]
    assert len(links) == 1  # the pdf (content) still fans out
