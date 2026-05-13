"""Tests for render.split_body_sections (N9g-pre)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from zkm_eml.render import split_body_sections


# ---------------------------------------------------------------------------
# Signature detection
# ---------------------------------------------------------------------------

def test_rfc3676_hard_separator():
    body = "Hello.\n\n-- \nAlice Smith\nalice@example.com"
    sal, sig = split_body_sections(body)
    assert sig is not None
    assert "alice@example.com" in sig
    assert sal is None


def test_double_dash_no_space():
    body = "Thanks for your email.\n\n--\nBob Jones\nbob@corp.com"
    _, sig = split_body_sections(body)
    assert sig is not None
    assert "bob@corp.com" in sig


def test_triple_dash_separator():
    body = "See attached.\n\n---\nCarol\n+41 79 000 00 00"
    _, sig = split_body_sections(body)
    assert sig is not None
    assert "+41 79 000 00 00" in sig


def test_english_signoff_regards():
    body = "Please review and confirm.\n\nBest regards,\nDave\ndave@example.com"
    _, sig = split_body_sections(body)
    assert sig is not None
    assert "Dave" in sig


def test_german_signoff():
    body = "Vielen Dank für Ihre Nachricht.\n\nFreundliche Grüsse\nErika Muster\n+41 44 000 00 00"
    _, sig = split_body_sections(body)
    assert sig is not None
    assert "Erika Muster" in sig


def test_no_signature_returns_none():
    body = "This is a short transactional message with no sign-off."
    _, sig = split_body_sections(body)
    assert sig is None


def test_separator_in_first_half_ignored():
    """A -- separator in the first 50% of the body should not be treated as a sig delimiter."""
    body = "\n".join(["Line " + str(i) for i in range(20)])
    # Insert separator at line 5 (well within first 50%)
    lines = body.splitlines()
    lines.insert(5, "--")
    body = "\n".join(lines)
    _, sig = split_body_sections(body)
    # Should not detect a signature from a separator deep in the first half
    # (the separator is at position 5 of 21 lines ≈ 24%, below 50% threshold)
    assert sig is None or "Line" not in sig[:10]


def test_empty_body():
    sal, sig = split_body_sections("")
    assert sal is None
    assert sig is None


def test_blank_after_separator_no_sig():
    """Signature block must be non-empty after stripping; blank content → None."""
    body = "Short message.\n\n-- \n   \n  "
    _, sig = split_body_sections(body)
    assert sig is None


# ---------------------------------------------------------------------------
# Salutation detection
# ---------------------------------------------------------------------------

def test_english_dear_salutation():
    body = "Dear John Doe,\n\nPlease find the document attached."
    sal, _ = split_body_sections(body)
    assert sal is not None
    assert "John Doe" in sal


def test_german_hallo_salutation():
    body = "Hallo Frau Müller,\n\nvielen Dank für Ihre Rückmeldung."
    sal, _ = split_body_sections(body)
    assert sal is not None
    assert "Frau Müller" in sal


def test_german_sehr_geehrte():
    body = "Sehr geehrter Herr Kienzler,\n\nanbei die gewünschten Unterlagen."
    sal, _ = split_body_sections(body)
    assert sal is not None
    assert "Herr Kienzler" in sal


def test_hi_salutation():
    body = "Hi Alice,\n\nLet me know if you need anything."
    sal, _ = split_body_sections(body)
    assert sal is not None
    assert "Alice" in sal


def test_no_salutation_when_body_starts_with_content():
    body = "The invoice for order #12345 is due next week."
    sal, _ = split_body_sections(body)
    assert sal is None


def test_salutation_capped_at_three_lines():
    body = "Dear Alice,\nThank you for your message.\nWe will process your request.\n\nRegards,\nBob"
    sal, _ = split_body_sections(body)
    assert sal is not None
    assert sal.count("\n") <= 2  # at most 3 lines


# ---------------------------------------------------------------------------
# Both sections present
# ---------------------------------------------------------------------------

def test_salutation_and_signature_detected_together():
    body = (
        "Dear Bob,\n\n"
        "Your subscription has been renewed.\n\n"
        "Best regards,\n"
        "Alice Smith\n"
        "alice@corp.com\n"
        "+41 44 123 45 67"
    )
    sal, sig = split_body_sections(body)
    assert sal is not None and "Bob" in sal
    assert sig is not None and "alice@corp.com" in sig
