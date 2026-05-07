"""Full-quote block detection and tail-quote collapse for rendered message bodies."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

_ATTRIBUTION_RE = re.compile(
    r"^(?:"
    r"On\s.+\bwrote:\s*"           # English: "On <date>, X wrote:"
    r"|Am\s.+\bschrieb\s.+:\s*"    # German Thunderbird: "Am <date> schrieb X:"
    r"|.+\bwrote:\s*"              # Generic English: "X wrote:"
    r"|.+\bschrieb:\s*"            # Generic German: "X schrieb:"
    r")$",
    re.IGNORECASE,
)

_QUOTED_FROM_MARKER = "*[Quoted from:"


@dataclass
class QuoteBlock:
    start: int            # index of first '>' line
    end: int              # exclusive end index
    attribution: int | None  # index of attribution line before the block, or None
    text: str             # one-level-stripped plaintext of the block (for matching)


def find_tail_quote(lines: list[str]) -> QuoteBlock | None:
    """Return a QuoteBlock if the message ends with a single tail-quoted block.

    Conservative: returns None for interleaved replies (any '>' line in the
    author's own text section) or for single-line blocks that are already the
    collapsed marker (idempotency guard).
    """
    n = len(lines)
    # Skip trailing blank lines
    end = n
    while end > 0 and not lines[end - 1].strip():
        end -= 1
    if end == 0 or not lines[end - 1].startswith(">"):
        return None

    # Extend start backward over contiguous '>' lines
    start = end
    while start > 0 and lines[start - 1].startswith(">"):
        start -= 1

    # Build one-level-stripped text
    stripped_lines = [_strip_one_level(ln) for ln in lines[start:end]]
    text = "\n".join(stripped_lines)

    # Idempotency: already a collapsed marker
    if text.strip().startswith(_QUOTED_FROM_MARKER):
        return None

    # Scan backward before the quote block to find an optional attribution line
    attr_scan = start
    while attr_scan > 0 and not lines[attr_scan - 1].strip():
        attr_scan -= 1
    attribution: int | None = None
    if attr_scan > 0 and _ATTRIBUTION_RE.match(lines[attr_scan - 1].strip()):
        attribution = attr_scan - 1

    # Interleaved guard: any '>' line in the author's section means not a clean tail quote
    cutoff = attribution if attribution is not None else start
    for i in range(cutoff):
        if lines[i].startswith(">"):
            return None

    return QuoteBlock(start=start, end=end, attribution=attribution, text=text)


def normalize_for_match(text: str) -> str:
    """Lowercase and collapse whitespace for fuzzy comparison."""
    text = text.lower()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(\s*\n)+", "\n", text)
    return text.strip()


def similarity(a: str, b: str) -> float:
    """SequenceMatcher ratio on pre-normalized strings."""
    return difflib.SequenceMatcher(None, a, b).ratio()


def strip_full_quote(
    body: str,
    parent_plain: str,
    parent_md_link: str,
    threshold: float = 0.90,
) -> str:
    """Replace a matching tail-quote block with a single collapsed marker line.

    parent_md_link should be a fully-formatted markdown link like
    '[Subject](relative/path.md)'.

    Returns body unchanged if:
    - no tail quote found
    - similarity to parent_plain is below threshold
    - block is already the collapsed marker (idempotency)
    """
    lines = body.splitlines()
    block = find_tail_quote(lines)
    if block is None:
        return body

    sim = similarity(normalize_for_match(block.text), normalize_for_match(parent_plain))
    if sim < threshold:
        return body

    # Determine splice point: attribution line (if found) or start of quote block
    cut_from = block.attribution if block.attribution is not None else block.start
    # Strip trailing blank lines so we add exactly one blank before the marker
    while cut_from > 0 and not lines[cut_from - 1].strip():
        cut_from -= 1

    marker = f"> *[Quoted from: {parent_md_link}]*"
    new_lines = lines[:cut_from] + ["", marker]
    return "\n".join(new_lines).strip()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_one_level(line: str) -> str:
    """Remove a single leading '> ' (or bare '>') from a quoted line."""
    if line.startswith("> "):
        return line[2:]
    if line.startswith(">"):
        return line[1:]
    return line
