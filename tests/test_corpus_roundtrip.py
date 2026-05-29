"""Convert-faithfulness roundtrip test for the synthetic corpus.

Two contracts:
1. Byte-stability: regenerating the .eml fixtures produces byte-identical output.
2. Drift sentinel: convert() on those fixtures emits the expected frontmatter schema.
   A rename of 'subject' → 'title' in frontmatter.py turns this test red.
"""

from __future__ import annotations

import sys
from pathlib import Path

import frontmatter
import pytest

# Add scripts/ to sys.path so we can import the generator module directly.
_scripts = Path(__file__).parent.parent / "scripts"
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))

from convert import convert
from generate_corpus import MESSAGES, generate
from zkm_eml.frontmatter import PLUGIN_VERSION

CORPUS_FIXTURES = Path(__file__).parent / "fixtures" / "corpus"


@pytest.fixture()
def store(tmp_path: Path) -> Path:
    sdir = tmp_path / "store"
    sdir.mkdir()
    (sdir / ".git").mkdir()
    for d in ("mail/messages", "mail/threads", "originals/mail"):
        (sdir / d).mkdir(parents=True)
    return sdir


# ---------------------------------------------------------------------------
# Byte-stability
# ---------------------------------------------------------------------------


def test_generator_byte_stable(tmp_path: Path) -> None:
    """Re-running the generator produces byte-identical .eml files."""
    generate(tmp_path)
    for name, _ in MESSAGES:
        committed = CORPUS_FIXTURES / name
        assert committed.exists(), f"Committed fixture missing: {name} — run generate_corpus.py"
        assert committed.read_bytes() == (tmp_path / name).read_bytes(), (
            f"{name}: generator output changed — regenerate fixtures and recommit"
        )


# ---------------------------------------------------------------------------
# Drift sentinel
# ---------------------------------------------------------------------------


def test_convert_subject_not_title(store: Path) -> None:
    """The converter writes 'subject' in frontmatter, never 'title'."""
    created = convert(store, {
        "source_dir": str(CORPUS_FIXTURES),
        "keep_originals": False,
        "quote_strip": False,
    })
    assert len(created) == 5
    for p in created:
        post = frontmatter.load(p)
        assert "subject" in post.metadata, f"{p.name}: missing 'subject' key"
        assert "title" not in post.metadata, (
            f"{p.name}: unexpected 'title' key — converter drift! "
            f"index.py:65 and embed.py:479 read 'title', converter must write 'subject'."
        )


def test_convert_frontmatter_schema(store: Path) -> None:
    """Assert core frontmatter fields for each corpus message."""
    created = convert(store, {
        "source_dir": str(CORPUS_FIXTURES),
        "keep_originals": False,
        "quote_strip": False,
    })

    # Index by message_id for convenient per-message assertions.
    by_mid: dict[str, frontmatter.Post] = {}
    for p in created:
        post = frontmatter.load(p)
        by_mid[post.metadata["message_id"]] = post

    assert set(by_mid) == {
        "<corpus-standalone@example.com>",
        "<corpus-thread-root@example.org>",
        "<corpus-thread-reply1@example.org>",
        "<corpus-thread-reply2@example.org>",
        "<corpus-multi-addr@example.net>",
    }

    # All messages: required schema fields
    for mid, post in by_mid.items():
        m = post.metadata
        assert m["source"] == "eml", f"{mid}: source mismatch"
        assert m["processor"] == "eml", f"{mid}: processor mismatch"
        assert m["processor_version"] == PLUGIN_VERSION, f"{mid}: processor_version mismatch"
        assert isinstance(m["tags"], list), f"{mid}: tags not a list"
        assert isinstance(m["participants"], list), f"{mid}: participants not a list"
        assert "subject" in m, f"{mid}: missing subject"
        assert "title" not in m, f"{mid}: unexpected title — drift!"

    # Standalone
    s = by_mid["<corpus-standalone@example.com>"].metadata
    assert s["subject"] == "Invoice for March services"
    assert s["date"] == "2026-04-01T09:00:00+00:00"
    assert "in_reply_to" not in s
    assert "references" not in s
    addrs = {p["address"] for p in s["participants"]}
    assert addrs == {"alice@example.com", "bob@example.com"}
    roles = {p["address"]: p["role"] for p in s["participants"]}
    assert roles["alice@example.com"] == "from"
    assert roles["bob@example.com"] == "to"

    # Thread: root
    r = by_mid["<corpus-thread-root@example.org>"].metadata
    assert r["subject"] == "Project update for Q2"
    assert r["date"] == "2026-04-07T14:00:00+00:00"
    assert "in_reply_to" not in r
    assert "references" not in r

    # Thread: reply1
    r1 = by_mid["<corpus-thread-reply1@example.org>"].metadata
    assert r1["subject"] == "Re: Project update for Q2"
    assert r1["date"] == "2026-04-07T15:30:00+00:00"
    assert r1["in_reply_to"] == "<corpus-thread-root@example.org>"
    assert r1["references"] == ["<corpus-thread-root@example.org>"]

    # Thread: reply2
    r2 = by_mid["<corpus-thread-reply2@example.org>"].metadata
    assert r2["date"] == "2026-04-07T16:00:00+00:00"
    assert r2["in_reply_to"] == "<corpus-thread-reply1@example.org>"
    assert r2["references"] == [
        "<corpus-thread-root@example.org>",
        "<corpus-thread-reply1@example.org>",
    ]

    # Multi-recipient
    multi = by_mid["<corpus-multi-addr@example.net>"].metadata
    assert multi["subject"] == "Welcome to the team"
    assert multi["date"] == "2026-04-08T08:00:00+00:00"
    addrs = {p["address"] for p in multi["participants"]}
    assert addrs == {
        "frank@example.net", "alice@example.com", "bob@example.com", "carol@example.org"
    }


def test_convert_thread_ids_consistent(store: Path) -> None:
    """All three messages in the reply chain share the same thread_id."""
    created = convert(store, {
        "source_dir": str(CORPUS_FIXTURES),
        "keep_originals": False,
        "quote_strip": False,
    })

    by_mid: dict[str, frontmatter.Post] = {}
    for p in created:
        post = frontmatter.load(p)
        by_mid[post.metadata["message_id"]] = post

    root_tid = by_mid["<corpus-thread-root@example.org>"].metadata["thread_id"]
    r1_tid = by_mid["<corpus-thread-reply1@example.org>"].metadata["thread_id"]
    r2_tid = by_mid["<corpus-thread-reply2@example.org>"].metadata["thread_id"]
    assert root_tid == r1_tid == r2_tid, "Thread chain has inconsistent thread_id"

    # Standalone and multi-addr must have different thread_ids
    s_tid = by_mid["<corpus-standalone@example.com>"].metadata["thread_id"]
    m_tid = by_mid["<corpus-multi-addr@example.net>"].metadata["thread_id"]
    assert len({root_tid, s_tid, m_tid}) == 3, "Unexpected thread_id collision"
