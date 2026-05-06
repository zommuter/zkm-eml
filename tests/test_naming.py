"""Tests for naming helpers."""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone

from zkm_eml.naming import date_shard, message_slug, slugify, thread_stub


def test_slugify_normal():
    assert slugify("Hello Bob") == "hello-bob"


def test_slugify_strips_re():
    assert slugify("Re: Hello Bob") == "hello-bob"
    assert slugify("Aw: Hello Bob") == "hello-bob"
    assert slugify("Fwd: Hello Bob") == "hello-bob"


def test_slugify_empty_returns_empty():
    assert slugify("") == ""
    assert slugify("   ") == ""


def test_slugify_max_length():
    long = "a" * 80
    assert len(slugify(long)) == 60


def test_message_slug_uses_subject():
    assert message_slug("Hello Bob", "alice@example.com") == "hello-bob"


def test_message_slug_empty_subject_uses_sender_localpart():
    slug = message_slug("", "Alice <alice@example.com>")
    assert slug == "from-alice"


def test_message_slug_empty_subject_bare_addr():
    slug = message_slug("", "billing@acme.com")
    assert slug == "from-billing"


def test_message_slug_empty_subject_unparseable_addr():
    slug = message_slug("", "not-an-email")
    assert slug == "from-unknown"


def test_message_slug_re_subject_uses_stripped():
    assert message_slug("Re: Hello Bob", "x@y.com") == "hello-bob"


def test_date_shard_returns_year_month():
    dt = datetime(2026, 5, 7, 14, 30, tzinfo=timezone.utc)
    assert date_shard(dt) == ("2026", "05")


def test_date_shard_pads_month():
    dt = datetime(2024, 1, 15, 9, 0, tzinfo=timezone.utc)
    assert date_shard(dt) == ("2024", "01")


def test_thread_stub_first_eight():
    assert thread_stub("a3f9b1c2d3e4f5a6") == "a3f9b1c2"


def test_thread_stub_short_id():
    assert thread_stub("abcd") == "abcd"


def test_slugify_nfc_normalize():
    # NFD-encoded ü (u + combining diaeresis) should be NFC-normalized and kept
    nfd_u_umlaut = "über"  # u + combining diaeresis + ber
    result = slugify(nfd_u_umlaut)
    assert result == "über"


def test_slugify_keeps_unicode_by_default():
    assert slugify("Grüße aus Berlin") == "grüße-aus-berlin"


def test_slugify_ascii_fold_when_env_set(monkeypatch):
    monkeypatch.setenv("EML_SLUG_ASCII", "true")
    # Reload naming module so the env var is picked up
    import zkm_eml.naming as naming_mod
    importlib.reload(naming_mod)
    try:
        result = naming_mod.slugify("Grüße aus Berlin")
        assert "ü" not in result
        assert "ß" not in result
        # NFKD: ü → u+combining-diaeresis → "u"; ß has no ASCII form → dropped
        assert "grue" in result
    finally:
        monkeypatch.delenv("EML_SLUG_ASCII", raising=False)
        importlib.reload(naming_mod)
