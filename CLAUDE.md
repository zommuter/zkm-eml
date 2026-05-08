# zkm-eml

zkm plugin that converts `.eml` files (RFC 5322 email messages) to markdown in the knowledge store, with thread modeling and full compliance with the [zkm messaging-spec](https://github.com/Zommuter/zkm/blob/main/docs/messaging-spec.md).

**Repo**: `~/src/zkm/plugins/zkm-eml/`  
**Store dirs**: `mail/messages/`, `mail/threads/`, `originals/mail/`  
**Install**: already discovered (repo lives in `zkm/plugins/`); no `zkm plugin add` needed

## Why EML, not IMAP

The IMAP fetch concern is separated from conversion. `mbsync` (or any Maildir-producing tool) handles fetching. This plugin reads Maildir trees or flat `.eml` dumps found under `EML_SOURCE_DIR` (default `~/mail`), always read-only. A future `zkm-imap` plugin could be a thin wrapper if live IMAP fetch is ever needed.

## Architecture

```
EML_SOURCE_DIR/          # mbsync Maildir tree or flat .eml dump (default ~/mail)
    <account>/<folder>/{cur,new}/*   # Maildir-format (no extension)
    *.eml  (recursive)
         │
         ▼
    source.py            # iter_messages() — Maildir + .eml, folder pruning
         │
         ▼
    parse.py             # email.message_from_bytes → ParsedMessage + ParsedAttachment
         │
         ├── threading.py     # References chain → thread_id, thread tree
         ├── render.py        # body selection: plaintext > HTML→markdownify; parent lookup
         ├── quote_strip.py   # tail-quote detection, similarity, collapse
         ├── frontmatter.py   # write frontmatter per messaging-spec.md
         ├── thread_index.py  # regenerate mail/threads/<thread_id>.md
         ├── naming.py        # slugify, unique_path, sanitize_filename (shared)
         └── originals.py     # strip+detach, CAS storage, sidecar JSON, inbox symlinks
         │
         ▼
    mail/messages/<date>_<slug>.md         # one per message
    mail/threads/<thread_id>.md            # one per thread (regenerated each run)
    originals/mail/<date>_<slug>.eml       # stripped .eml (text only, attachment stubs)
    originals/mail/<date>_<slug>/          # per-message attachment symlinks
    originals/mail/_objects/<aa>/<rest>    # CAS attachment objects (sha256-named)
    originals/mail/<date>_<slug>.source.json  # reconstruction hints
    inbox/<filename>                       # symlinks to CAS objects for other plugins
```

## Module responsibilities

### `source.py`
- Entry: `iter_messages(src: Path, exclude_folders: list[str]) -> Iterator[Path]`
- Yields every mail file: Maildir (`cur/`/`new/` contents) and `*.eml` files
- Prunes `.git`, `.notmuch`, `.snapshots`, `tmp/` unconditionally
- Prunes any segment matching `exclude_folders` (case-insensitive, supports multi-segment like `[Google Mail]/Trash`)
- `default_exclude_folders() -> list[str]` — built-in sensible defaults

### `naming.py`
- `slugify(s)` — strips Re/Aw/Fwd prefix, lowercases, max 60 chars (extracted from `convert.py`)
- `msgid_slug(message_id)` — filesystem-safe slug from a Message-ID
- `unique_path(directory, stem, suffix)` — collision-suffix with `_1`, `_2`, ...
- `sanitize_filename(name, fallback)` — strips path separators, control chars, leading dots

### `parse.py`
- Entry: `parse_eml(path: Path) -> ParsedMessage`
- Uses stdlib `email` + `email.policy.default` — no external parser
- Returns a dataclass with: `message_id`, `in_reply_to`, `references`, `date`, `subject`, `from_addr`, `to_addrs`, `cc_addrs`, `plain_body`, `html_body`, `has_attachments`, `attachments`
- `ParsedAttachment`: `filename`, `content_type`, `content_id`, `is_inline`, `referenced_in_html`, `size`, `sha256`, `payload`, `part_index`
- If `Message-ID` header is missing, synthesizes a stable ID from `sha256(headers)`
- Normalizes all address fields to `"Name <addr>"` strings

### `threading.py`
- Entry: `thread_id_for(message_id: str, references: list[str]) -> str`
- Thread ID = first 16 hex chars of `sha256(root_message_id.encode())`
- Root = oldest `Message-ID` in References chain, or the message's own ID if References is empty
- Designed so thread_id is stable: same input always produces same ID

### `render.py`
- Entry: `render_body(msg: ParsedMessage, parent_lookup=None, dest=None) -> str`
- Prefer `plain_body` if non-empty; fall back to `markdownify(html_body)` if plain is absent
- When `parent_lookup` and `dest` are provided, calls `quote_strip.strip_full_quote` on the selected body
- `parent_lookup(message_id) -> ParentInfo | None` — caller-supplied closure; built in `convert.py`
- `html_to_markdown(html) -> str` — public re-export of the markdownify wrapper (used by parent lookup for HTML-only parents)

### `originals.py`
- Entry: `write_original(store_path, msg, raw_eml, msg_slug, source_repo, source_repo_commit, source_blob) -> (eml_rel, [(att, symlink_rel), ...])`
- Writes stripped `.eml` (text bodies kept, attachment payloads replaced by stubs with `X-Zkm-Detached` headers)
- CAS storage: `originals/mail/_objects/<sha[:2]>/<sha[2:]>` — idempotent, atomic writes
- Per-message symlinks: `originals/mail/<slug>/<filename>` → `../_objects/<aa>/<rest>`
- Sidecar JSON: `originals/mail/<slug>.source.json` with `source_path`, `source_blob`, `source_repo_commit` for three retrieval paths
- `git_blob_sha1(data: bytes) -> str` — computes `git hash-object` SHA-1 locally, no subprocess per message
- `symlink_inbox(store_path, att)` — creates `inbox/<filename>` → CAS object, deduplicated

### `frontmatter.py`
- Entry: `write_message_md(dest, msg, thread_id, thread_path, direction, body, original_path, attachment_meta, source_path_rel_home, source_repo_commit, source_blob) -> None`
- Writes frontmatter per messaging-spec.md + base plugin-spec.md fields
- Core fields: `message_id`, `thread_id`, `in_reply_to`, `references`, `thread`, `participants`, `direction`, `source`, `date`, `tags`, `sha256`, `original`, `processor`, `processor_version`
- New fields: `attachments` (list with filename/sha256/path/object/content_type/size/inline/cid_referenced), `source_path`, `source_repo_commit`, `source_blob`

### `thread_index.py`
- Entry: `build_thread_membership(messages_dir) -> (message_ids, thread_membership, parent_index)`
  - `message_ids` — `set[str]` of all known message_ids for deduplication
  - `thread_membership` — `{thread_id: [ThreadMember, ...]}` for index writes
  - `parent_index` — `{message_id: (md_path, original_rel)}` for quote-strip parent lookup
- `write_thread_index(store_path, thread_id, members)` — writes `mail/threads/YYYY/MM/…md` from in-memory list
- `regenerate_thread_index(store_path, thread_id)` — back-compat wrapper: scans disk then writes

## Deduplication

- Primary key: `message_id`. On first convert run, scan all existing `.md` in `mail/messages/` to build a `{message_id: path}` index.
- Skip any `.eml` whose `message_id` is already present.
- `sha256` is computed over raw `.eml` bytes and stored in frontmatter for the base plugin contract; it is NOT used as the primary dedup key (email re-encoding can change bytes without changing content).

## Filename convention

Messages: `mail/messages/{YYYY-MM-DD}_{slug}.md`
Originals: `originals/mail/{YYYY-MM-DD}_{slug}.eml` (same slug, stripped payload)
Attachment subfolder: `originals/mail/{YYYY-MM-DD}_{slug}/`
CAS objects: `originals/mail/_objects/{sha256[:2]}/{sha256[2:]}`
Thread index: `mail/threads/{thread_id}.md`
Inbox links: `inbox/{filename}` (symlinks to CAS objects)

- `{YYYY-MM-DD}` from the `Date:` header (UTC)
- `{slug}` from `slugify(subject)`, up to 60 chars, `Re:`/`Aw:`/`Fwd:` stripped, collision-suffixed with `_1`, `_2`, ...

## Attachments

All attachment payloads are detached from the stored `.eml` and written to the CAS (`_objects/`) using their sha256 as the key. The stripped `.eml` contains stub headers (`X-Zkm-Detached`, `X-Zkm-Detached-Sha256`, `X-Zkm-Detached-Size`) pointing to the CAS location. Re-forwarded attachments and repeated decoration logos dedup automatically.

Per-message symlinks (`originals/mail/<slug>/<filename>`) point at CAS objects with human-readable names. `inbox/<filename>` symlinks (one per unique CAS object) expose attachments to other zkm plugins (zkm-pdf, zkm-photo, recursive zkm-eml).

Decoration vs inline photos: currently treated uniformly — all attachments go through the same path. See TODO.md for the open classification question.

### `quote_strip.py`
- Entry: `strip_full_quote(body, parent_plain, parent_md_link, threshold=0.90) -> str`
- `find_tail_quote(lines) -> QuoteBlock | None` — detects a contiguous `>`-prefixed block at the tail of the message; returns None for interleaved replies (any `>` line in the author's own text section)
- `normalize_for_match(text) -> str` — lowercase + collapse horizontal whitespace + collapse blank lines (no `>` stripping — that's done by `find_tail_quote`)
- `similarity(a, b) -> float` — `difflib.SequenceMatcher.ratio()` on pre-normalized strings
- Attribution detection: single-line `"On … wrote:"` (English) or `"Am … schrieb …:"` (German Thunderbird) immediately before the quote block; removed along with the block when similarity matches
- Nested chains: strips exactly ONE `> ` level per line; inner `> > …` nesting is preserved so the stripped text matches the parent's own plain_body (which already contains those nested quotes)
- Idempotency guard: if the block is already the `*[Quoted from: …]*` marker, `find_tail_quote` returns None
- Stdlib only — `difflib.SequenceMatcher`, no new deps

Quote stripping is controlled via `EML_QUOTE_STRIP=true` (default). When false, `render_body` receives no `parent_lookup` and bodies are passed through as-is (v0.6 behaviour). Requires `EML_KEEP_ORIGINALS=true` for accurate matching; falls back to reading the rendered .md body with a one-time warning if originals are absent.

**Round-trip guarantee**: `originals/mail/<slug>.eml` always preserves the full body verbatim (only attachment payloads are detached). The rendered .md body is the only lossy surface. Re-running with `EML_QUOTE_STRIP=false` or `--reprocess` after any algorithm change recovers the original rendering from the stored .eml.

**v0.8 design** (deferred): partial/interleaved quote collapse — segment by `>`-prefix runs, match each segment against ancestors, replace with anchored links.

## Direction detection

`EML_OWNER_ADDRESSES` (comma-separated, from `.env`) is matched against the `From:` address:
- If From is in owner addresses → `outgoing`
- Otherwise → `incoming`
- If `EML_OWNER_ADDRESSES` is empty → `unknown`

## Tests

All test fixtures are **synthetic** — no real email. Never commit real `.eml` files.

- `tests/fixtures/*.eml` — hand-crafted minimal EML files for edge cases
- `tests/fixtures/chain_{a,b,c,d}.eml` — four-message nested-quote chain for v0.7 tests
- `tests/fixtures/reply_attribution.eml` — English "On … wrote:" attribution pattern
- `tests/fixtures/reply_attribution_de.eml` — German "Am … schrieb …:" attribution pattern
- `tests/fixtures/reply_inline.eml` — interleaved quoting (must NOT be collapsed)
- `tests/fixtures/reply_low_similarity.eml` — quote doesn't match parent (< 0.90)
- `tests/fixtures/reply_already_stripped.eml` — idempotency fixture
- `test_parse.py` — multipart, missing Message-ID, broken encoding, attachments
- `test_threading.py` — thread_id stability, broken References chain, orphaned reply
- `test_quote_strip.py` — unit tests for quote_strip.py pure functions
- `test_convert.py` — end-to-end against a temp store; idempotency; thread index regeneration; quote-strip integration

## Development setup

```bash
cd ~/src/zkm/plugins/zkm-eml
uv sync --extra dev
uv run pytest

# Plugin is auto-discovered (repo lives in zkm/plugins/); no `zkm plugin add` needed.
# To verify:

# Point at a Maildir and run:
ZKM_STORE=~/knowledge uv run zkm convert zkm-eml
```
