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


# ---------------------------------------------------------------------------
# Encoding / non-ASCII tests
# ---------------------------------------------------------------------------


def test_subject_rfc2047_decoded():
    msg = parse_eml(FIXTURES / "umlaut_subject.eml")
    assert msg.subject == "Grüße aus Berlin"
    assert "=?" not in msg.subject


def test_display_name_encoded_decoded():
    msg = parse_eml(FIXTURES / "umlaut_subject.eml")
    # From: =?UTF-8?Q?M=C3=BCller=2C_Hans?= <hans@example.com>
    assert "Müller, Hans" in msg.from_addr
    assert "=?" not in msg.from_addr


def test_display_name_with_comma_preserved():
    msg = parse_eml(FIXTURES / "display_name_with_comma.eml")
    # From: "Müller, Hans" <hans.mueller@example.com>
    assert "Müller, Hans" in msg.from_addr
    assert msg.from_addr.count("@") == 1  # single address, not split


def test_display_name_encoded_in_from():
    msg = parse_eml(FIXTURES / "display_name_encoded.eml")
    # From: =?UTF-8?Q?M=C3=BCller=2C_Hans?= <hans.mueller@example.com>
    assert "Müller" in msg.from_addr
    assert "=?" not in msg.from_addr


def test_body_latin1_decoded():
    msg = parse_eml(FIXTURES / "latin1_body.eml")
    assert "ü" in msg.plain_body
    assert "Ü" in msg.plain_body
    assert "�" not in msg.plain_body


def test_body_windows1252_decoded():
    msg = parse_eml(FIXTURES / "windows1252_body.eml")
    assert "ä" in msg.plain_body
    assert "ü" in msg.plain_body
    assert "�" not in msg.plain_body


def test_attachment_filename_rfc2231():
    msg = parse_eml(FIXTURES / "rfc2231_filename.eml")
    assert len(msg.attachments) == 1
    att = msg.attachments[0]
    assert att.filename == "Bewährung.pdf"
    assert "=?" not in att.filename


def test_attachment_filename_rfc2047():
    msg = parse_eml(FIXTURES / "rfc2047_filename.eml")
    assert len(msg.attachments) == 1
    att = msg.attachments[0]
    assert att.filename == "Bewährung.pdf"
    assert "=?" not in att.filename


def test_attachment_filename_raw_preserved():
    """filename_raw holds the pre-decode value from get_filename()."""
    msg = parse_eml(FIXTURES / "with_pdf.eml")
    att = msg.attachments[0]
    assert att.filename == "invoice.pdf"
    # For plain ASCII, filename_raw matches filename
    assert att.filename_raw == "invoice.pdf"
