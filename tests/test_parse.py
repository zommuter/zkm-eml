"""Tests for parse.py — EML parsing."""

from __future__ import annotations

from datetime import timezone
from pathlib import Path

from zkm_eml.parse import parse_eml

FIXTURES = Path(__file__).parent / "fixtures"


def test_simple_parse():
    msg = parse_eml(FIXTURES / "simple.eml")
    assert msg.message_id == "hello-001@example.com"
    assert msg.raw_message_id == "<hello-001@example.com>"
    assert msg.in_reply_to is None
    assert msg.references == []
    assert msg.subject == "Hello Bob"
    assert "alice@example.com" in msg.from_addr
    assert any("bob@example.com" in a for a in msg.to_addrs)
    assert "Hi Bob" in msg.plain_body
    assert msg.has_attachments is False
    assert len(msg.sha256) == 64


def test_reply_parse():
    msg = parse_eml(FIXTURES / "reply.eml")
    assert msg.message_id == "reply-001@example.com"
    assert msg.in_reply_to == "hello-001@example.com"
    assert msg.references == ["hello-001@example.com"]
    assert "Thanks for the message" in msg.plain_body


def test_multipart_prefers_plaintext():
    msg = parse_eml(FIXTURES / "multipart.eml")
    assert msg.plain_body.strip() == "This is the plain text version."
    assert "html" in msg.html_body.lower()


def test_no_message_id_synthesizes():
    msg = parse_eml(FIXTURES / "no_message_id.eml")
    assert msg.message_id.startswith("synthetic-")
    assert len(msg.message_id) > 10


def test_date_is_utc():
    msg = parse_eml(FIXTURES / "simple.eml")
    assert msg.date.tzinfo == timezone.utc
    assert msg.date.year == 2026


def test_sha256_is_stable():
    msg1 = parse_eml(FIXTURES / "simple.eml")
    msg2 = parse_eml(FIXTURES / "simple.eml")
    assert msg1.sha256 == msg2.sha256
