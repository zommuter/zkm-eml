"""Unit tests for quote_strip.py — pure functions, no I/O."""

from __future__ import annotations

from zkm_eml.quote_strip import (
    find_tail_quote,
    normalize_for_match,
    similarity,
    strip_full_quote,
)


# ---------------------------------------------------------------------------
# find_tail_quote
# ---------------------------------------------------------------------------

def test_simple_tail_quote():
    lines = [
        "Thanks for the message!",
        "",
        "> Hi Bob,",
        ">",
        "> Simple email.",
    ]
    block = find_tail_quote(lines)
    assert block is not None
    assert block.start == 2
    assert block.end == 5
    assert block.attribution is None
    assert "Hi Bob," in block.text
    assert "Simple email." in block.text


def test_tail_quote_with_english_attribution():
    lines = [
        "Thanks!",
        "",
        "On Mon, 13 Apr 2026, Alice <alice@example.com> wrote:",
        "> Hi Bob,",
        ">",
        "> Simple email.",
    ]
    block = find_tail_quote(lines)
    assert block is not None
    assert block.attribution == 2
    assert block.start == 3


def test_tail_quote_with_german_attribution():
    lines = [
        "Danke!",
        "",
        "Am Mon, 13 Apr 2026 schrieb Alice <alice@example.com>:",
        "> Hi Bob,",
        ">",
        "> Simple email.",
    ]
    block = find_tail_quote(lines)
    assert block is not None
    assert block.attribution == 2


def test_interleaved_quotes_not_detected():
    lines = [
        "I agree with the first.",
        "",
        "> First point.",
        "",
        "But not the second.",
        "",
        "> Second point.",
    ]
    assert find_tail_quote(lines) is None


def test_no_quote_block():
    lines = ["Just a message.", "", "No quotes here.", ""]
    assert find_tail_quote(lines) is None


def test_empty_body():
    assert find_tail_quote([]) is None


def test_idempotency_guard():
    lines = [
        "Thanks!",
        "",
        "> *[Quoted from: [Hello](../foo.md)]*",
    ]
    assert find_tail_quote(lines) is None


def test_trailing_blank_lines_ignored():
    lines = [
        "Reply text.",
        "",
        "> Quoted text.",
        "",
        "",
    ]
    block = find_tail_quote(lines)
    assert block is not None
    assert block.end == 3  # blank lines excluded


def test_nested_quote_stripped_one_level():
    """Tail quote with nested >> — stripped one level, inner > preserved."""
    lines = [
        "Charlie here.",
        "",
        "> Bob's reply.",
        ">",
        "> > Alice's original.",
    ]
    block = find_tail_quote(lines)
    assert block is not None
    assert "Bob's reply." in block.text
    assert "> Alice's original." in block.text  # inner level preserved


# ---------------------------------------------------------------------------
# normalize_for_match
# ---------------------------------------------------------------------------

def test_normalize_case():
    assert normalize_for_match("Hello WORLD") == "hello world"


def test_normalize_whitespace():
    assert normalize_for_match("a  b\t c") == "a b c"


def test_normalize_blank_lines():
    assert normalize_for_match("a\n\n\nb") == "a\nb"


def test_normalize_strips():
    assert normalize_for_match("  hello  ") == "hello"


# ---------------------------------------------------------------------------
# similarity
# ---------------------------------------------------------------------------

def test_identical_similarity():
    assert similarity("hello", "hello") == 1.0


def test_zero_similarity():
    assert similarity("hello", "world xyz abc") < 0.5


def test_high_similarity_with_whitespace():
    a = normalize_for_match("Hi Bob,\n\nThis is a test.\n\nAlice")
    b = normalize_for_match("Hi Bob,\n\nThis is a test.\n\nAlice\n")
    assert similarity(a, b) > 0.95


# ---------------------------------------------------------------------------
# strip_full_quote — integration
# ---------------------------------------------------------------------------

PARENT_BODY = "Hi Bob,\n\nThis is a simple test email.\n\nCheers,\nAlice"

CHILD_SIMPLE = """\
Thanks for the message!

> Hi Bob,
>
> This is a simple test email.
>
> Cheers,
> Alice"""

CHILD_ATTR_EN = """\
Thanks for the message!

On Mon, 13 Apr 2026, Alice <alice@example.com> wrote:
> Hi Bob,
>
> This is a simple test email.
>
> Cheers,
> Alice"""

CHILD_ATTR_DE = """\
Danke!

Am Mon, 13 Apr 2026 schrieb Alice <alice@example.com>:
> Hi Bob,
>
> This is a simple test email.
>
> Cheers,
> Alice"""

CHILD_INLINE = """\
I agree with the first.

> Hi Bob,

But not the rest.

> This is a simple test email."""

CHILD_LOW_SIM = """\
Completely unrelated.

> This quoted text bears no resemblance to the parent message at all.
> Entirely fabricated content for testing low similarity detection."""


def test_strip_simple_tail_quote():
    result = strip_full_quote(CHILD_SIMPLE, PARENT_BODY, "[Hello Bob](../hello-bob.md)")
    assert "Quoted from:" in result
    assert "Hi Bob," not in result
    assert "Thanks for the message!" in result


def test_strip_english_attribution():
    result = strip_full_quote(CHILD_ATTR_EN, PARENT_BODY, "[Hello Bob](../hello-bob.md)")
    assert "Quoted from:" in result
    assert "wrote:" not in result   # attribution line also removed
    assert "Hi Bob," not in result


def test_strip_german_attribution():
    result = strip_full_quote(CHILD_ATTR_DE, PARENT_BODY, "[Hello Bob](../hello-bob.md)")
    assert "Quoted from:" in result
    assert "schrieb" not in result
    assert "Hi Bob," not in result


def test_no_strip_interleaved():
    result = strip_full_quote(CHILD_INLINE, PARENT_BODY, "[Hello Bob](../hello-bob.md)")
    assert result == CHILD_INLINE


def test_no_strip_low_similarity():
    result = strip_full_quote(CHILD_LOW_SIM, PARENT_BODY, "[Hello Bob](../hello-bob.md)")
    assert result == CHILD_LOW_SIM


def test_no_strip_no_quote_block():
    body = "Just a message with no quotes."
    result = strip_full_quote(body, PARENT_BODY, "[Hello Bob](../hello-bob.md)")
    assert result == body


def test_idempotent_already_stripped():
    body = "Thanks!\n\n> *[Quoted from: [Hello Bob](../hello-bob.md)]*"
    result = strip_full_quote(body, PARENT_BODY, "[Hello Bob](../hello-bob.md)")
    assert result == body


def test_marker_format():
    result = strip_full_quote(CHILD_SIMPLE, PARENT_BODY, "[Hello Bob](../hello-bob.md)")
    assert "> *[Quoted from: [Hello Bob](../hello-bob.md)]*" in result


def test_nested_chain_strip():
    """Chain: B's body contains A quoted at one level; C's body quotes B at one level."""
    body_a = "Hi everyone,\n\nWelcome to the chain test.\n\nAlice"
    body_b = "Thanks Alice, good to start.\n\nBob\n\n> Hi everyone,\n>\n> Welcome to the chain test.\n>\n> Alice"

    # C quotes B entirely — after stripping one level from C's quote, should match B
    body_c = (
        "Agreed, let's keep going.\n\nCharlie\n\n"
        "On Mon, 20 Apr 2026, Bob wrote:\n"
        "> Thanks Alice, good to start.\n"
        ">\n"
        "> Bob\n"
        ">\n"
        "> > Hi everyone,\n"
        "> >\n"
        "> > Welcome to the chain test.\n"
        "> >\n"
        "> > Alice"
    )

    result_b = strip_full_quote(body_b, body_a, "[Welcome to chain test](../chain_a.md)")
    assert "Quoted from:" in result_b
    assert "Hi everyone," not in result_b

    result_c = strip_full_quote(body_c, body_b, "[Re: Welcome to chain test](../chain_b.md)")
    assert "Quoted from:" in result_c
    assert "Thanks Alice" not in result_c
    # inner nested content gone too (whole tail replaced by one line)
    assert "Hi everyone," not in result_c
