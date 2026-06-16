"""Attachment decoration-vs-content classification (M1, census mode).

This is a CENSUS-FIRST classifier (house rule "observe before preventing"): it
labels every attachment with ``decoration | content | unknown`` so a real mailbox
can be surveyed for the actual distribution, but it does NOT change any default
behaviour. Inbox fan-out for ``decoration`` is config-gated and defaults to ON
(unchanged), so nothing is hidden until the census produces evidence to justify a
threshold flip.

Signals are intentionally conservative and single-message (no cross-sender CAS
recurrence yet — that needs the census evidence to calibrate):

- ``decoration`` — a small, inline, cid-referenced image: the classic newsletter
  logo / banner / spacer. Also tracking-pixel-sized images (<= 1x1-ish, i.e. a
  few hundred bytes) regardless of inline flag.
- ``content`` — any non-image part (pdf, docx, zip, …) of non-trivial size, and
  any image that is NOT inline-and-cid-referenced (a genuine photo attachment).
- ``unknown`` — everything the two clear rules don't cover. The deliberate
  catch-all: when in doubt we observe, we do not hide.

These thresholds are HEURISTIC, not evidence-backed yet — see REVIEW_ME.md /
ROADMAP id:ff0f. They are deliberately loose so the ``unknown`` bucket stays
large until the census says otherwise.
"""

from __future__ import annotations

from .parse import ParsedAttachment

# A decoration image is "small": logos/banners/spacers are well under this.
# Real inline photographs are typically far larger. Loose on purpose.
DECORATION_MAX_BYTES = 50_000

# A tracking pixel is a 1x1 (or near) image — only a few hundred bytes encoded.
TRACKING_PIXEL_MAX_BYTES = 1_024

# Image parts below this are too small to be informational content.
CONTENT_IMAGE_MIN_BYTES = 50_000

VALID_CLASSES = ("decoration", "content", "unknown")


def _is_image(content_type: str) -> bool:
    return (content_type or "").lower().startswith("image/")


def classify_attachment(att: ParsedAttachment) -> str:
    """Return ``"decoration"`` | ``"content"`` | ``"unknown"`` for one attachment.

    Pure function of a single attachment's metadata — deterministic, no I/O.
    """
    is_image = _is_image(att.content_type)

    # Non-image parts are content (documents) unless trivially small.
    if not is_image:
        # A 0-byte or near-empty non-image part is ambiguous junk, not content.
        if att.size <= 0:
            return "unknown"
        return "content"

    # --- image parts ---

    # Tracking-pixel-sized image: decoration regardless of inline flag.
    if att.size <= TRACKING_PIXEL_MAX_BYTES:
        return "decoration"

    # Small inline, cid-referenced image embedded in the HTML body: logo/banner.
    if att.is_inline and att.referenced_in_html and att.size <= DECORATION_MAX_BYTES:
        return "decoration"

    # A genuine image attachment (not inline-and-referenced) above the floor is
    # almost certainly a photo the user cares about.
    if not (att.is_inline and att.referenced_in_html) and att.size >= CONTENT_IMAGE_MIN_BYTES:
        return "content"

    # Everything else (mid-size inline images, large embedded images, …) is left
    # for the census to characterise.
    return "unknown"
