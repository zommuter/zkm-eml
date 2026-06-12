"""Reprocess-path specs: data-URI detach and frontmatter preservation.

Red tests for roadmap id:9bf0 (reprocess must detach data-URIs like convert does)
and roadmap id:9255 (reprocess must not drop foreign frontmatter keys or the
attachments[] list).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import frontmatter
import pytest

from convert import convert, reprocess

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def store(tmp_path: Path) -> Path:
    sdir = tmp_path / "store"
    sdir.mkdir()
    (sdir / ".git").mkdir()  # minimal fake git repo for path checks
    for d in ["mail/messages", "mail/threads", "originals/mail"]:
        (sdir / d).mkdir(parents=True)
    return sdir


def _convert_one(store: Path, fixture: str) -> tuple[Path, dict]:
    src = store.parent / "eml_src"
    src.mkdir(exist_ok=True)
    shutil.copy(FIXTURES / fixture, src / fixture)
    config = {
        "source_dir": str(src),
        "keep_originals": True,
        "attachment_inbox": False,
    }
    created = convert(store, config)
    assert len(created) == 1
    return created[0], config


def test_reprocess_detaches_data_uris(store: Path):
    """The stored original keeps data-URIs verbatim (round-trip guarantee), so
    reprocess must re-apply the detach step or the URIs leak into the body."""
    # roadmap:9bf0
    md_path, config = _convert_one(store, "with_data_uri_img.eml")

    post = frontmatter.load(md_path)
    assert "data:" not in post.content  # convert path is already clean

    updated = reprocess(store, config, [md_path])
    assert len(updated) == 1

    post = frontmatter.load(md_path)
    assert "data:" not in post.content, (
        "data-URI leaked back into the markdown body on --reprocess"
    )

    # The detached payload must (still) exist as a CAS object
    objects_dir = store / "mail" / "_objects"
    cas_files = [p for p in objects_dir.rglob("*") if p.is_file() and "." not in p.name]
    assert len(cas_files) >= 1


def test_reprocess_preserves_foreign_frontmatter_keys(store: Path):
    """Frontmatter is multi-producer (amendment contract): keys written by other
    producers — e.g. NER's entities[] — must survive a reprocess rewrite."""
    # roadmap:9255
    md_path, config = _convert_one(store, "simple.eml")

    post = frontmatter.load(md_path)
    post.metadata["entities"] = [{"type": "person", "value": "Erika Musterfrau"}]
    md_path.write_text(frontmatter.dumps(post), encoding="utf-8")

    updated = reprocess(store, config, [md_path])
    assert len(updated) == 1

    post = frontmatter.load(md_path)
    assert post.metadata.get("entities") == [
        {"type": "person", "value": "Erika Musterfrau"}
    ], "amender-written entities[] dropped by reprocess"


def test_reprocess_preserves_attachments_meta(store: Path):
    """attachments[] can only be computed on the convert path (the stored original
    is payload-stripped) — reprocess must carry it over, not drop it."""
    # roadmap:9255
    md_path, config = _convert_one(store, "with_pdf.eml")

    atts_before = frontmatter.load(md_path).metadata.get("attachments", [])
    assert len(atts_before) == 1  # sanity: convert recorded the PDF

    updated = reprocess(store, config, [md_path])
    assert len(updated) == 1

    atts_after = frontmatter.load(md_path).metadata.get("attachments", [])
    assert atts_after == atts_before, "attachments[] frontmatter lost on reprocess"
