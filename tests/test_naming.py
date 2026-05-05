"""Tests for naming helpers."""

from __future__ import annotations

from zkm_eml.naming import message_slug, shard_path, slugify


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


def test_shard_path_splits_correctly():
    assert shard_path("a3f9b1c2d3e4f5a6") == ("a3", "f9b1c2d3e4f5a6")


def test_shard_path_first_two_chars():
    tid = "0" * 16
    aa, rest = shard_path(tid)
    assert aa == "00"
    assert rest == "0" * 14
