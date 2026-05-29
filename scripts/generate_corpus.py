#!/usr/bin/env python3
"""Generate a small deterministic synthetic .eml corpus.

Run from the plugins/zkm-eml directory:
    uv run python scripts/generate_corpus.py

Writes byte-stable .eml files to tests/fixtures/corpus/ by default.
No random(), no datetime.now() — output is always identical.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Corpus definition — fixed headers, bodies, dates
# ---------------------------------------------------------------------------
#
# Design notes:
# - All Date: headers are explicit and RFC 5322-valid (prevents parse.py fallback
#   to datetime.now() at parse.py:150/157).
# - Message-IDs are explicit and readable.
# - Bodies contain distinct searchable tokens for BM25 ranking tests.
# - Thread chain wires In-Reply-To + References so thread_id / in_reply_to
#   / references frontmatter fields are exercised.
# - Multi-recipient message exercises participants[] with varied roles.

MESSAGES: list[tuple[str, str]] = [
    (
        "corpus_standalone.eml",
        "From: Alice <alice@example.com>\r\n"
        "To: Bob <bob@example.com>\r\n"
        "Subject: Invoice for March services\r\n"
        "Date: Wed, 01 Apr 2026 09:00:00 +0000\r\n"
        "Message-ID: <corpus-standalone@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Dear Bob,\r\n"
        "\r\n"
        "Please find the invoice for March services totalling CHF 1250.\r\n"
        "Payment due within 30 days.\r\n"
        "\r\n"
        "Best regards,\r\n"
        "Alice\r\n",
    ),
    (
        "corpus_thread_root.eml",
        "From: Carol <carol@example.org>\r\n"
        "To: Dave <dave@example.org>, Eve <eve@example.org>\r\n"
        "Subject: Project update for Q2\r\n"
        "Date: Tue, 07 Apr 2026 14:00:00 +0000\r\n"
        "Message-ID: <corpus-thread-root@example.org>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Hi team,\r\n"
        "\r\n"
        "The Q2 project milestone is on track.\r\n"
        "Next meeting Thursday at 10:00.\r\n"
        "\r\n"
        "Carol\r\n",
    ),
    (
        "corpus_thread_reply1.eml",
        "From: Dave <dave@example.org>\r\n"
        "To: Carol <carol@example.org>\r\n"
        "Cc: Eve <eve@example.org>\r\n"
        "Subject: Re: Project update for Q2\r\n"
        "Date: Tue, 07 Apr 2026 15:30:00 +0000\r\n"
        "Message-ID: <corpus-thread-reply1@example.org>\r\n"
        "In-Reply-To: <corpus-thread-root@example.org>\r\n"
        "References: <corpus-thread-root@example.org>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Thanks Carol, confirmed for Thursday.\r\n"
        "\r\n"
        "Dave\r\n",
    ),
    (
        "corpus_thread_reply2.eml",
        "From: Eve <eve@example.org>\r\n"
        "To: Carol <carol@example.org>\r\n"
        "Cc: Dave <dave@example.org>\r\n"
        "Subject: Re: Project update for Q2\r\n"
        "Date: Tue, 07 Apr 2026 16:00:00 +0000\r\n"
        "Message-ID: <corpus-thread-reply2@example.org>\r\n"
        "In-Reply-To: <corpus-thread-reply1@example.org>\r\n"
        "References: <corpus-thread-root@example.org> <corpus-thread-reply1@example.org>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Same here, see you Thursday.\r\n"
        "\r\n"
        "Eve\r\n",
    ),
    (
        "corpus_multi_addr.eml",
        "From: Frank <frank@example.net>\r\n"
        "To: Alice <alice@example.com>, Bob <bob@example.com>\r\n"
        "Cc: Carol <carol@example.org>\r\n"
        "Subject: Welcome to the team\r\n"
        "Date: Wed, 08 Apr 2026 08:00:00 +0000\r\n"
        "Message-ID: <corpus-multi-addr@example.net>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Hello everyone,\r\n"
        "\r\n"
        "Welcome aboard. Looking forward to working with you all.\r\n"
        "\r\n"
        "Frank\r\n",
    ),
    (
        # NER probe fixture: body has spaced IBAN + CHF amount.
        # compact canonical DE44500105175407324931 is absent from body,
        # so BM25 can only match it via entities[].canonical (E8 regression).
        "corpus_iban_invoice.eml",
        "From: Alice <alice@example.com>\r\n"
        "To: Bob <bob@example.com>\r\n"
        "Subject: Payment request with IBAN\r\n"
        "Date: Thu, 09 Apr 2026 11:00:00 +0000\r\n"
        "Message-ID: <corpus-iban-invoice@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Dear Bob,\r\n"
        "\r\n"
        "Please transfer the outstanding amount for the March invoice.\r\n"
        "\r\n"
        "Amount due: CHF 1250\r\n"
        "Bank: Deutsche Bank AG\r\n"
        "IBAN: DE44 5001 0517 5407 3249 31\r\n"
        "BIC: DEUTDEDB\r\n"
        "\r\n"
        "Payment is requested within 14 days.\r\n"
        "\r\n"
        "Best regards,\r\n"
        "Alice\r\n",
    ),
]


def generate(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name, content in MESSAGES:
        (dest / name).write_bytes(content.encode("utf-8"))
    print(f"Wrote {len(MESSAGES)} .eml files to {dest}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    default = Path(__file__).parent.parent / "tests" / "fixtures" / "corpus"
    ap.add_argument("dest", nargs="?", type=Path, default=default)
    args = ap.parse_args()
    generate(args.dest)


if __name__ == "__main__":
    main()
