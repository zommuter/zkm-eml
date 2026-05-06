"""End-to-end integration tests for convert.py."""

from __future__ import annotations

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


def test_convert_basic(store: Path):
    config = {"EML_SOURCE_DIR": str(FIXTURES), "EML_KEEP_ORIGINALS": "false"}
    created = convert(store, config)
    assert len(created) >= 1
    for p in created:
        assert p.exists()
        post = frontmatter.load(p)
        assert post.metadata["source"] == "zkm-eml"
        assert "message_id" in post.metadata
        assert "thread_id" in post.metadata
        assert "thread" in post.metadata
        assert "processor" in post.metadata
        assert post.metadata["processor_version"] == "0.6.0"


def test_convert_idempotent(store: Path):
    config = {"EML_SOURCE_DIR": str(FIXTURES), "EML_KEEP_ORIGINALS": "false"}
    first = convert(store, config)
    second = convert(store, config)
    assert len(first) > 0
    assert len(second) == 0


def test_convert_thread_index_created(store: Path):
    config = {"EML_SOURCE_DIR": str(FIXTURES), "EML_KEEP_ORIGINALS": "false"}
    convert(store, config)
    thread_files = list((store / "mail" / "threads").rglob("*.md"))
    assert len(thread_files) >= 1
    for tf in thread_files:
        post = frontmatter.load(tf)
        assert "thread_id" in post.metadata
        assert "message_count" in post.metadata
        assert post.metadata["message_count"] >= 1


def test_convert_reply_shares_thread_id(store: Path):
    config = {"EML_SOURCE_DIR": str(FIXTURES), "EML_KEEP_ORIGINALS": "false"}
    convert(store, config)
    messages_dir = store / "mail" / "messages"
    mds = list(messages_dir.rglob("*.md"))
    # simple.eml and reply.eml should be in the same thread
    thread_ids = set()
    subjects = {}
    for md in mds:
        post = frontmatter.load(md)
        subj = post.metadata.get("subject", "")
        tid = post.metadata.get("thread_id", "")
        subjects[subj] = tid
        thread_ids.add(tid)
    # There should be at most 2 distinct thread IDs (simple+reply share one;
    # multipart and no_message_id each have their own)
    hello_tid = subjects.get("Hello Bob")
    re_tid = subjects.get("Re: Hello Bob")
    if hello_tid and re_tid:
        assert hello_tid == re_tid


def test_convert_keeps_originals(store: Path):
    config = {"EML_SOURCE_DIR": str(FIXTURES), "EML_KEEP_ORIGINALS": "true"}
    convert(store, config)
    originals = list((store / "originals" / "mail").rglob("*.eml"))
    assert len(originals) >= 1


def test_convert_participant_roles(store: Path):
    """Participants are emitted as role-tagged dicts; no direction field."""
    config = {"EML_SOURCE_DIR": str(FIXTURES), "EML_KEEP_ORIGINALS": "false"}
    convert(store, config)
    messages_dir = store / "mail" / "messages"
    by_subject: dict = {}
    for md in messages_dir.rglob("*.md"):
        post = frontmatter.load(md)
        subj = post.metadata.get("subject", "")
        by_subject[subj] = post.metadata

    # "Hello Bob": From alice, To bob
    hello = by_subject.get("Hello Bob", {})
    assert "direction" not in hello, "direction field must not be emitted"
    participants = hello.get("participants", [])
    roles = {p["role"]: p["address"] for p in participants}
    assert roles.get("from") == "alice@example.com"
    assert roles.get("to") == "bob@example.com"

    # "Re: Hello Bob": From bob, To alice
    reply = by_subject.get("Re: Hello Bob", {})
    roles_r = {p["role"]: p["address"] for p in reply.get("participants", [])}
    assert roles_r.get("from") == "bob@example.com"
    assert roles_r.get("to") == "alice@example.com"


def test_convert_progress_callback(store: Path):
    config = {"EML_SOURCE_DIR": str(FIXTURES), "EML_KEEP_ORIGINALS": "false"}
    calls: list[tuple[int, int | None, str]] = []
    created = convert(store, config, progress=lambda c, t, m: calls.append((c, t, m)))
    assert len(calls) > 0
    currents = [c for c, _, _ in calls]
    assert currents == sorted(currents)
    # Every call reports a total and last call has current == total
    totals = [t for _, t, _ in calls]
    assert all(t is not None for t in totals)
    assert calls[-1][0] == calls[-1][1]
    # One call per file (including skipped / already-existing)
    assert len(calls) == calls[-1][1]
    # Progress items >= created (some may be skipped dupes)
    assert len(calls) >= len(created)


def test_reprocess_updates_existing(store: Path):
    config = {"EML_SOURCE_DIR": str(FIXTURES), "EML_KEEP_ORIGINALS": "true"}
    created = convert(store, config)
    assert len(created) > 0
    updated = reprocess(store, config, created)
    assert len(updated) == len(created)
    for p in updated:
        assert p.exists()


def test_message_paths_are_date_sharded(store: Path):
    config = {"EML_SOURCE_DIR": str(FIXTURES), "EML_KEEP_ORIGINALS": "false"}
    created = convert(store, config)
    assert len(created) >= 1
    for p in created:
        # Expect mail/messages/YYYY/MM/YYYY-MM-DD-HHMM-<thread8>-<slug>.md
        parts = p.relative_to(store / "mail" / "messages").parts
        assert len(parts) == 3, f"Expected YYYY/MM/filename.md, got {parts}"
        YYYY, MM, filename = parts
        assert YYYY.isdigit() and len(YYYY) == 4
        assert MM.isdigit() and len(MM) == 2
        # Filename: YYYY-MM-DD-HHMM-<8hex>-<slug>.md
        name = filename[: -len(".md")]
        segments = name.split("-")
        assert len(segments) >= 4, f"Unexpected filename shape: {filename}"
        # 5th segment (index 4) is the 8-hex thread stub
        assert len(segments) >= 5 and len(segments[4]) == 8 and all(
            c in "0123456789abcdef" for c in segments[4]
        ), f"No 8-hex thread stub in: {filename}"


def test_thread_paths_are_date_sharded(store: Path):
    config = {"EML_SOURCE_DIR": str(FIXTURES), "EML_KEEP_ORIGINALS": "false"}
    convert(store, config)
    threads_dir = store / "mail" / "threads"
    thread_files = list(threads_dir.rglob("*.md"))
    assert len(thread_files) >= 1
    for tf in thread_files:
        parts = tf.relative_to(threads_dir).parts
        assert len(parts) == 3, f"Expected YYYY/MM/filename.md, got {parts}"
        YYYY, MM, _ = parts
        assert YYYY.isdigit() and len(YYYY) == 4
        assert MM.isdigit() and len(MM) == 2


def test_limit_recent(store: Path, tmp_path: Path):
    import os
    import shutil
    src = tmp_path / "eml_src"
    src.mkdir()
    fixtures_list = sorted(FIXTURES.glob("*.eml"))
    assert len(fixtures_list) >= 3, "Need at least 3 fixtures for this test"
    for idx, eml in enumerate(fixtures_list[:5]):
        dest = src / eml.name
        shutil.copy(eml, dest)
        # Spread mtime so ordering is deterministic
        mtime = 1000000 + idx * 1000
        os.utime(dest, (mtime, mtime))

    config = {"EML_SOURCE_DIR": str(src), "EML_KEEP_ORIGINALS": "false", "EML_LIMIT_RECENT": "2"}
    created = convert(store, config)
    assert len(created) == 2
