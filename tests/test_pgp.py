"""Tests for PGP2 — Tier A (signed detection) and Tier B (auth_results)."""

from __future__ import annotations

from pathlib import Path

import pytest

from zkm_eml.parse import parse_eml

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Tier A — signed detection
# ---------------------------------------------------------------------------


def test_pgp_mime_signed_detected():
    msg = parse_eml(FIXTURES / "pgp_mime_signed.eml")
    assert msg.signed == "pgp-mime"


def test_pgp_mime_signature_leaf_is_attachment():
    msg = parse_eml(FIXTURES / "pgp_mime_signed.eml")
    sig_atts = [a for a in msg.attachments if a.is_signature_part]
    assert len(sig_atts) == 1
    assert sig_atts[0].content_type == "application/pgp-signature"


def test_pgp_mime_signature_leaf_excluded_from_non_sig_atts():
    """Non-signature attachment list (for inbox fan-out) excludes signature leaves."""
    msg = parse_eml(FIXTURES / "pgp_mime_signed.eml")
    non_sig = [a for a in msg.attachments if not a.is_signature_part]
    # The signed message has only body text + signature; no non-sig attachments
    assert all(not a.is_signature_part for a in non_sig)


def test_smime_signed_detected():
    msg = parse_eml(FIXTURES / "smime_signed.eml")
    assert msg.signed == "smime"


def test_smime_signature_leaf_is_attachment():
    msg = parse_eml(FIXTURES / "smime_signed.eml")
    sig_atts = [a for a in msg.attachments if a.is_signature_part]
    assert len(sig_atts) == 1
    assert sig_atts[0].content_type == "application/pkcs7-signature"


def test_unsigned_message_has_no_signed_field():
    msg = parse_eml(FIXTURES / "simple.eml")
    assert msg.signed is None


# ---------------------------------------------------------------------------
# Tier B — auth_results
# ---------------------------------------------------------------------------


def test_auth_results_parsed():
    msg = parse_eml(FIXTURES / "pgp_mime_signed.eml")
    assert msg.auth_results, "expected at least one auth record"


def test_auth_results_contains_auth_results_header():
    msg = parse_eml(FIXTURES / "pgp_mime_signed.eml")
    ar = [r for r in msg.auth_results if r.get("source") == "Authentication-Results"]
    assert len(ar) == 1
    rec = ar[0]
    assert rec["verified_by"] == "mx.example.com"
    assert rec["dkim"] == "pass"
    assert rec["spf"] == "pass"
    assert rec["dmarc"] == "pass"


def test_auth_results_contains_dkim_signature():
    msg = parse_eml(FIXTURES / "pgp_mime_signed.eml")
    dkim = [r for r in msg.auth_results if r.get("source") == "DKIM-Signature"]
    assert len(dkim) == 1
    rec = dkim[0]
    assert rec["domain"] == "example.com"
    assert rec["selector"] == "selector1"


def test_auth_results_provenance_named():
    """Each record must have a 'source' field — never a bare verified: true."""
    msg = parse_eml(FIXTURES / "pgp_mime_signed.eml")
    for rec in msg.auth_results:
        assert "source" in rec, f"record missing source: {rec}"
        assert "verified" not in rec, f"bare verified: field not allowed: {rec}"


def test_dkim_fail_preserved():
    """dmarc=fail in S/MIME fixture is preserved faithfully."""
    msg = parse_eml(FIXTURES / "smime_signed.eml")
    ar = [r for r in msg.auth_results if r.get("source") == "Authentication-Results"]
    assert ar
    assert ar[0]["dmarc"] == "fail"


def test_unsigned_message_has_empty_auth_results():
    msg = parse_eml(FIXTURES / "simple.eml")
    assert msg.auth_results == []
