# zkm-eml

zkm plugin that converts `.eml` files (RFC 5322 email messages) to markdown in the knowledge store, with thread modeling and full compliance with the [zkm messaging-spec](https://github.com/Zommuter/zkm/blob/main/docs/messaging-spec.md).

**Repo**: `~/src/zkm-eml/`  
**Store dirs**: `mail/messages/`, `mail/threads/`, `originals/mail/`  
**Install**: `zkm plugin add ~/src/zkm-eml`

## Why EML, not IMAP

The IMAP fetch concern is separated from conversion. `mbsync` (or any Maildir-producing tool) handles fetching. This plugin reads whatever `.eml` files it finds in `EML_SOURCE_DIR`. A future `zkm-imap` plugin could be a thin wrapper if live IMAP fetch is ever needed.

## Architecture

```
EML_SOURCE_DIR/          # mbsync Maildir or any .eml dump
    *.eml  (recursive)
         │
         ▼
    parse.py             # email.message_from_bytes → ParsedMessage dataclass
         │
         ├── threading.py     # References chain → thread_id, thread tree
         ├── render.py        # body selection: plaintext > HTML→markdownify
         ├── frontmatter.py   # write frontmatter per messaging-spec.md
         └── thread_index.py  # regenerate mail/threads/<thread_id>.md
         │
         ▼
    mail/messages/<date>_<slug>.md   # one per message
    mail/threads/<thread_id>.md      # one per thread (regenerated on each run)
    originals/mail/<msgid_slug>.eml  # raw original (for --reprocess)
```

## Module responsibilities

### `parse.py`
- Entry: `parse_eml(path: Path) -> ParsedMessage`
- Uses stdlib `email` + `email.policy.default` — no external parser
- Returns a dataclass with: `message_id`, `in_reply_to`, `references`, `date`, `subject`, `from_addr`, `to_addrs`, `cc_addrs`, `plain_body`, `html_body`, `has_attachments`
- If `Message-ID` header is missing, synthesizes a stable ID from `sha256(headers)`
- Normalizes all address fields to `"Name <addr>"` strings

### `threading.py`
- Entry: `thread_id_for(message_id: str, references: list[str]) -> str`
- Thread ID = first 16 hex chars of `sha256(root_message_id.encode())`
- Root = oldest `Message-ID` in References chain, or the message's own ID if References is empty
- Also: `build_thread_tree(messages: list[ParsedMessage]) -> dict` for thread index rendering
- Designed so thread_id is stable: same input always produces same ID

### `render.py`
- Entry: `render_body(msg: ParsedMessage) -> str`
- Prefer `plain_body` if non-empty (after whitespace normalization)
- Fall back to `markdownify(html_body)` if plain is absent
- **v0.1**: no quote stripping — body preserved as-is
- **v0.2 design** (deferred — see below): detect and collapse full-quote blocks

### `frontmatter.py`
- Entry: `write_message_md(dest: Path, msg: ParsedMessage, thread_id: str, thread_path: str, direction: str, sha256: str) -> None`
- Writes frontmatter per messaging-spec.md + base plugin-spec.md fields
- Field name mapping: `message_id`, `thread_id`, `in_reply_to`, `references`, `thread`, `participants`, `direction`, `source`, `date`, `tags`, `sha256`, `original`, `processor`, `processor_version`

### `thread_index.py`
- Entry: `regenerate_thread_index(store_path: Path, thread_id: str) -> Path`
- Walks `mail/messages/` to collect all messages for a given thread_id
- Sorts chronologically by `date` frontmatter
- Writes `mail/threads/<thread_id>.md` with a table of message links

## Deduplication

- Primary key: `message_id`. On first convert run, scan all existing `.md` in `mail/messages/` to build a `{message_id: path}` index.
- Skip any `.eml` whose `message_id` is already present.
- `sha256` is computed over raw `.eml` bytes and stored in frontmatter for the base plugin contract; it is NOT used as the primary dedup key (email re-encoding can change bytes without changing content).

## Filename convention

`mail/messages/{YYYY-MM-DD}_{slug}.md`

- `{YYYY-MM-DD}` from the `Date:` header (UTC)
- `{slug}` from `slugify(subject)`, up to 60 chars, collision-suffixed with `_1`, `_2`, ...
- Thread index: `mail/threads/{thread_id}.md`

## Direction detection

`EML_OWNER_ADDRESSES` (comma-separated, from `.env`) is matched against the `From:` address:
- If From is in owner addresses → `outgoing`
- Otherwise → `incoming`
- If `EML_OWNER_ADDRESSES` is empty → `unknown`

## v0.2 quote-stripping (deferred)

**Design sketch** (kept here so it doesn't get re-derived):

1. **Full-quote detection**: after stripping `> ` prefixes from each line run, compare normalized text against the `plain_body` of the parent in the thread tree.
   - If similarity ≥ 90% (e.g. via `difflib.SequenceMatcher`) → replace quoted block with `> *[Quoted from: [parent subject](../messages/parent.md)]*`
2. **Partial-quote detection** (v0.3): segment by `>`-prefix runs. For each run, find the best match in any ancestor. Replace with an anchored link `[…quoted from parent](…#anchor)`.
3. **HTML↔plaintext canonicalization**: normalize both to comparable plaintext before matching — handles the common case where the HTML body quotes the plain body of the parent (or vice versa).

Trigger via `zkm convert zkm-eml --reprocess` once v0.2 is released. The `original` frontmatter field (pointing to `originals/mail/`) enables this without re-fetching.

## Tests

All test fixtures are **synthetic** — no real email. Never commit real `.eml` files.

- `tests/fixtures/*.eml` — hand-crafted minimal EML files for edge cases
- `test_parse.py` — multipart, missing Message-ID, broken encoding, attachments
- `test_threading.py` — thread_id stability, broken References chain, orphaned reply
- `test_convert.py` — end-to-end against a temp store; idempotency; thread index regeneration

## Development setup

```bash
cd ~/src/zkm-eml
uv sync --extra dev
uv run pytest

# Wire into zkm:
cd ~/src/zkm
uv run zkm plugin add ~/src/zkm-eml

# Point at a Maildir and run:
ZKM_STORE=~/knowledge uv run zkm convert zkm-eml
```
