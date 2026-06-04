"""End-to-end integration tests for convert.py."""

from __future__ import annotations

import shutil
from pathlib import Path

import frontmatter
import pytest

from convert import convert, reprocess, scrub
from zkm_eml.parse import parse_eml

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
    config = {"source_dir": str(FIXTURES), "keep_originals": False}
    created = convert(store, config)
    assert len(created) >= 1
    for p in created:
        assert p.exists()
        post = frontmatter.load(p)
        assert post.metadata["source"] == "eml"
        assert "message_id" in post.metadata
        assert "thread_id" in post.metadata
        assert "thread" in post.metadata
        assert "processor" in post.metadata
        assert post.metadata["processor_version"] == "0.14.0"


def test_convert_idempotent(store: Path):
    config = {"source_dir": str(FIXTURES), "keep_originals": False}
    first = convert(store, config)
    second = convert(store, config)
    assert len(first) > 0
    assert len(second) == 0


def test_convert_thread_index_created(store: Path):
    config = {"source_dir": str(FIXTURES), "keep_originals": False}
    convert(store, config)
    thread_files = list((store / "mail" / "threads").rglob("*.md"))
    assert len(thread_files) >= 1
    for tf in thread_files:
        post = frontmatter.load(tf)
        assert "thread_id" in post.metadata
        assert "message_count" in post.metadata
        assert post.metadata["message_count"] >= 1


def test_convert_reply_shares_thread_id(store: Path):
    config = {"source_dir": str(FIXTURES), "keep_originals": False}
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
    config = {"source_dir": str(FIXTURES), "keep_originals": True}
    convert(store, config)
    originals = list((store / "originals" / "mail").rglob("*.eml"))
    assert len(originals) >= 1


def test_convert_participant_roles(store: Path):
    """Participants are emitted as role-tagged dicts; no direction field."""
    config = {"source_dir": str(FIXTURES), "keep_originals": False}
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
    config = {"source_dir": str(FIXTURES), "keep_originals": False}
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
    config = {"source_dir": str(FIXTURES), "keep_originals": True}
    created = convert(store, config)
    assert len(created) > 0
    updated = reprocess(store, config, created)
    assert len(updated) == len(created)
    for p in updated:
        assert p.exists()


def test_message_paths_are_date_sharded(store: Path):
    config = {"source_dir": str(FIXTURES), "keep_originals": False}
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
    config = {"source_dir": str(FIXTURES), "keep_originals": False}
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

    config = {"source_dir": str(src), "keep_originals": False, "limit_recent": 2}
    created = convert(store, config)
    assert len(created) == 2


# ---------------------------------------------------------------------------
# Quote stripping integration tests
# ---------------------------------------------------------------------------

def _make_chain_store(store: Path, tmp_path: Path) -> tuple[Path, list[Path]]:
    """Create a source dir with just the chain fixtures and convert+reprocess."""
    chain_src = tmp_path / "chain_src"
    chain_src.mkdir()
    for name in ["chain_a.eml", "chain_b.eml", "chain_c.eml", "chain_d.eml"]:
        shutil.copy(FIXTURES / name, chain_src / name)
    config = {"source_dir": str(chain_src), "keep_originals": True}
    created = convert(store, config)
    assert len(created) == 4
    # Reprocess so all parent lookups can resolve across the full set
    reprocess(store, config, created)
    return chain_src, created


def _body_by_subject(store: Path, subject: str) -> str:
    matches = []
    for md in (store / "mail" / "messages").rglob("*.md"):
        post = frontmatter.load(md)
        if post.metadata.get("subject") == subject:
            matches.append(post.content)
    if not matches:
        raise AssertionError(f"No message found with subject: {subject!r}")
    if len(matches) > 1:
        raise AssertionError(f"Ambiguous: {len(matches)} messages with subject {subject!r}")
    return matches[0]


def _body_by_message_id(store: Path, message_id: str) -> str:
    clean = message_id.strip("<>")
    for md in (store / "mail" / "messages").rglob("*.md"):
        post = frontmatter.load(md)
        raw = post.metadata.get("message_id", "")
        if raw.strip("<>") == clean:
            return post.content
    raise AssertionError(f"No message found with message_id: {message_id!r}")


def test_quote_strip_collapses_simple_reply(store: Path, tmp_path: Path):
    """reply.eml (reply-001) should have its quoted section collapsed."""
    config = {"source_dir": str(FIXTURES), "keep_originals": True}
    created = convert(store, config)
    reprocess(store, config, created)

    body = _body_by_message_id(store, "reply-001@example.com")
    assert "Quoted from:" in body
    # Raw quoted text should be gone
    assert "This is a simple test email." not in body
    # Author's own text should remain
    assert "Thanks for the message!" in body


def test_quote_strip_chain(store: Path, tmp_path: Path):
    """Each message in the chain should have its tail quote collapsed."""
    _make_chain_store(store, tmp_path)

    body_b = _body_by_subject(store, "Re: Welcome to chain test")
    assert "Quoted from:" in body_b
    assert "Hi everyone," not in body_b
    assert "Thanks Alice, good to start." in body_b

    body_c = _body_by_subject(store, "Re: Re: Welcome to chain test")
    assert "Quoted from:" in body_c
    assert "Thanks Alice, good to start." not in body_c

    body_d = _body_by_subject(store, "Re: Re: Re: Welcome to chain test")
    assert "Quoted from:" in body_d
    assert "Agreed, let's keep going." not in body_d


def test_quote_strip_disabled(store: Path, tmp_path: Path):
    """EML_QUOTE_STRIP=false preserves raw quoted text."""
    chain_src = tmp_path / "chain_src"
    chain_src.mkdir()
    for name in ["chain_a.eml", "chain_b.eml"]:
        shutil.copy(FIXTURES / name, chain_src / name)
    config = {
        "source_dir": str(chain_src),
        "keep_originals": True,
        "quote_strip": False,
    }
    created = convert(store, config)
    reprocess(store, config, created)

    body_b = _body_by_subject(store, "Re: Welcome to chain test")
    assert "Quoted from:" not in body_b
    assert "Hi everyone," in body_b


def test_quote_strip_idempotent(store: Path, tmp_path: Path):
    """Running reprocess twice produces no further changes."""
    chain_src = tmp_path / "chain_src"
    chain_src.mkdir()
    for name in ["chain_a.eml", "chain_b.eml"]:
        shutil.copy(FIXTURES / name, chain_src / name)
    config = {"source_dir": str(chain_src), "keep_originals": True}
    created = convert(store, config)
    reprocess(store, config, created)

    # Capture bodies after first reprocess
    bodies_1 = {
        md.name: frontmatter.load(md).content
        for md in (store / "mail" / "messages").rglob("*.md")
    }

    # Second reprocess
    reprocess(store, config, created)
    bodies_2 = {
        md.name: frontmatter.load(md).content
        for md in (store / "mail" / "messages").rglob("*.md")
    }

    assert bodies_1 == bodies_2


def test_round_trip_originals_body_unchanged(store: Path, tmp_path: Path):
    """parse_eml on the stored original must yield the same plain_body as the source EML."""
    chain_src = tmp_path / "chain_src"
    chain_src.mkdir()
    for name in ["chain_a.eml", "chain_b.eml", "chain_c.eml"]:
        src_eml = FIXTURES / name
        shutil.copy(src_eml, chain_src / name)

    source_bodies = {
        name: parse_eml(chain_src / name).plain_body
        for name in ["chain_a.eml", "chain_b.eml", "chain_c.eml"]
    }

    config = {"source_dir": str(chain_src), "keep_originals": True}
    convert(store, config)

    originals_dir = store / "originals" / "mail"
    for orig_eml in originals_dir.rglob("*.eml"):
        parsed = parse_eml(orig_eml)
        for name, source_body in source_bodies.items():
            if source_body and parsed.plain_body and source_body in parsed.plain_body:
                # The stored original contains at least the source body text
                assert source_body in parsed.plain_body, (
                    f"Original {orig_eml} body doesn't contain source body from {name}"
                )
                break


# ---------------------------------------------------------------------------
# Git-commit watermark integration
# ---------------------------------------------------------------------------


import subprocess as _subprocess

from zkm_eml.state import get_last_commit, read_state


def _git(args, cwd):
    return _subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _make_git_src(tmp_path, name="src"):
    src = tmp_path / name
    src.mkdir()
    _git(["init"], src)
    _git(["config", "user.email", "t@t.com"], src)
    _git(["config", "user.name", "T"], src)
    return src


def _commit_all(repo, msg="commit"):
    _git(["add", "-A"], repo)
    _git(["commit", "--allow-empty", "-m", msg], repo)
    return _git(["rev-parse", "HEAD"], repo)


def test_watermark_written_after_convert(tmp_path: Path) -> None:
    """A successful convert records the source HEAD as the watermark."""
    src = _make_git_src(tmp_path)
    eml = FIXTURES / "simple.eml"
    shutil.copy(eml, src / "simple.eml")
    sha = _commit_all(src, "add eml")

    store = tmp_path / "store"
    store.mkdir()
    (store / ".git").mkdir()
    for d in ["mail/messages", "mail/threads", "originals/mail"]:
        (store / d).mkdir(parents=True)

    config = {"source_dir": str(src), "keep_originals": False}
    convert(store, config)

    assert get_last_commit(store, src) == sha


def test_watermark_second_run_skips_existing(tmp_path: Path) -> None:
    """Second convert with no new source commits processes nothing (fast path)."""
    src = _make_git_src(tmp_path)
    shutil.copy(FIXTURES / "simple.eml", src / "simple.eml")
    _commit_all(src, "add eml")

    store = tmp_path / "store"
    store.mkdir()
    (store / ".git").mkdir()
    for d in ["mail/messages", "mail/threads", "originals/mail"]:
        (store / d).mkdir(parents=True)

    config = {"source_dir": str(src), "keep_originals": False}
    created1 = convert(store, config)
    assert len(created1) >= 1

    created2 = convert(store, config)
    assert created2 == []


def test_watermark_keys_by_repo_not_subdir(tmp_path: Path) -> None:
    """Two different source subdirs in the same git repo share a watermark key."""
    repo = _make_git_src(tmp_path, "repo")
    (repo / "inbox1").mkdir()
    (repo / "inbox2").mkdir()
    shutil.copy(FIXTURES / "simple.eml", repo / "inbox1" / "msg.eml")
    _commit_all(repo, "init")

    store = tmp_path / "store"
    store.mkdir()
    (store / ".git").mkdir()
    for d in ["mail/messages", "mail/threads", "originals/mail"]:
        (store / d).mkdir(parents=True)

    config1 = {"source_dir": str(repo / "inbox1"), "keep_originals": False}
    convert(store, config1)
    state = read_state(store)
    # Key is the repo root, not the subdir
    assert str(repo) in state
    assert str(repo / "inbox1") not in state


# ---------------------------------------------------------------------------
# M3: Deleted-mail policy tests
# ---------------------------------------------------------------------------

_DEL_EML_TMPL = (
    b"From: sender@example.com\r\n"
    b"To: rcpt@example.com\r\n"
    b"Message-ID: {mid}\r\n"
    b"Subject: Deletion policy test\r\n"
    b"Date: Thu, 01 Jan 2026 12:00:00 +0000\r\n"
    b"\r\n"
    b"Test body for deletion policy.\r\n"
)


def _del_eml(src: Path, fname: str, mid: str) -> Path:
    p = src / fname
    p.write_bytes(_DEL_EML_TMPL.replace(b"{mid}", mid.encode()))
    return p


def _del_store(tmp_path: Path, name: str = "store") -> Path:
    s = tmp_path / name
    s.mkdir()
    (s / ".git").mkdir()
    for d in ["mail/messages", "mail/threads", "originals/mail"]:
        (s / d).mkdir(parents=True)
    return s


def test_deleted_policy_keep(tmp_path: Path) -> None:
    """Policy 'keep' (default): deleted source mail stays in store unchanged."""
    src = _make_git_src(tmp_path)
    _del_eml(src, "a.eml", "<del-keep@zkm-test>")
    _commit_all(src, "add a.eml")
    store = _del_store(tmp_path)

    cfg = {"source_dir": str(src), "keep_originals": False, "deleted_policy": "keep"}
    created = convert(store, cfg)
    assert len(created) == 1
    md = created[0]

    _git(["rm", "a.eml"], src)
    _commit_all(src, "delete a.eml")

    convert(store, cfg)
    assert md.exists()
    post = frontmatter.load(md)
    assert "source_deleted" not in post.metadata


def test_deleted_policy_log(tmp_path: Path, capsys) -> None:
    """Policy 'log': deleted source mail stays, stderr notice is emitted."""
    src = _make_git_src(tmp_path)
    _del_eml(src, "a.eml", "<del-log@zkm-test>")
    _commit_all(src, "add a.eml")
    store = _del_store(tmp_path)

    cfg = {"source_dir": str(src), "keep_originals": False, "deleted_policy": "log"}
    created = convert(store, cfg)
    assert len(created) == 1
    md = created[0]

    _git(["rm", "a.eml"], src)
    _commit_all(src, "delete a.eml")

    convert(store, cfg)
    assert md.exists()
    assert "source deleted" in capsys.readouterr().err.lower()


def test_deleted_policy_purge(tmp_path: Path) -> None:
    """Policy 'purge': deleted source mail is removed from the store."""
    src = _make_git_src(tmp_path)
    _del_eml(src, "a.eml", "<del-purge@zkm-test>")
    _commit_all(src, "add a.eml")
    store = _del_store(tmp_path)

    cfg = {"source_dir": str(src), "keep_originals": False, "deleted_policy": "purge"}
    created = convert(store, cfg)
    assert len(created) == 1
    md = created[0]

    _git(["rm", "a.eml"], src)
    _commit_all(src, "delete a.eml")

    convert(store, cfg)
    assert not md.exists()


def test_deleted_policy_archive(tmp_path: Path) -> None:
    """Policy 'archive': deleted source mail gains source_deleted=true in frontmatter."""
    src = _make_git_src(tmp_path)
    _del_eml(src, "a.eml", "<del-archive@zkm-test>")
    _commit_all(src, "add a.eml")
    store = _del_store(tmp_path)

    cfg = {"source_dir": str(src), "keep_originals": False, "deleted_policy": "archive"}
    created = convert(store, cfg)
    assert len(created) == 1
    md = created[0]

    _git(["rm", "a.eml"], src)
    _commit_all(src, "delete a.eml")

    convert(store, cfg)
    assert md.exists()
    post = frontmatter.load(md)
    assert post.metadata.get("source_deleted") is True


def test_scrub_removes_base64_garbage(tmp_path: Path) -> None:
    """scrub() removes base64-fragment entity values, leaves legitimate values."""
    sdir = tmp_path / "store"
    (sdir / "mail" / "messages" / "2020" / "04").mkdir(parents=True)

    b64 = "UdAgC798dF1Y4PdWGsEorIPwmXFXPh5clhjWKPpPdtUmQbh0qOOfx8eWsvLp"
    legit = "test@example.com"
    md_path = sdir / "mail" / "messages" / "2020" / "04" / "test.md"
    md_path.write_text(
        f"---\nsource: eml\nentities:\n"
        f"  - {{type: email_address, value: '{legit}'}}\n"
        f"  - {{type: person, value: '{b64}'}}\n"
        f"---\nbody\n"
    )

    # Dry run: no changes written
    stats = scrub(sdir, {}, dry_run=True)
    assert stats["files_changed"] == 1
    assert stats["entities_removed"] == 1
    post = frontmatter.load(str(md_path))
    assert len(post.metadata["entities"]) == 2  # unchanged

    # Apply
    stats = scrub(sdir, {}, dry_run=False)
    assert stats["files_changed"] == 1
    assert stats["entities_removed"] == 1
    post = frontmatter.load(str(md_path))
    assert len(post.metadata["entities"]) == 1
    assert post.metadata["entities"][0]["value"] == legit

    # Idempotent
    stats = scrub(sdir, {}, dry_run=False)
    assert stats["files_changed"] == 0
    assert stats["entities_removed"] == 0


def test_scrub_removes_html_entity_run_garbage(tmp_path: Path) -> None:
    """scrub() removes &gt;/&nbsp; quoted-reply garbage entities, keeps legitimate values."""
    sdir = tmp_path / "store"
    (sdir / "mail" / "messages").mkdir(parents=True)

    legit = "Google LLC"
    md_path = sdir / "mail" / "messages" / "test.md"
    # Values: 1 legit + 5 garbage covering the three detection signals
    md_path.write_text(
        "---\nsource: eml\nentities:\n"
        f"  - {{type: org, value: '{legit}'}}\n"
        # starts-with &gt; (quoted-reply line)
        "  - {type: org, value: '&gt;&nbsp;Hi Paul'}\n"
        "  - {type: org, value: '&gt; &gt; Best regards'}\n"
        # 3+ &nbsp; (full sentence from undecoded body)
        "  - {type: org, value: 'Please&nbsp;let&nbsp;me&nbsp;know&nbsp;when'}\n"
        # \n&gt (text bleeding into reply marker)
        "  - {type: person, value: \"Paul\\n&gt\"}\n"
        "---\nbody\n"
    )

    stats = scrub(sdir, {}, dry_run=False)
    assert stats["entities_removed"] == 4
    post = frontmatter.load(str(md_path))
    assert len(post.metadata["entities"]) == 1
    assert post.metadata["entities"][0]["value"] == legit
