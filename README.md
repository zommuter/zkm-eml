# zkm-eml

[zkm](https://github.com/zommuter/zkm) plugin that converts Maildir or `.eml` files to markdown in the knowledge store with full thread modeling and attachment extraction.

## What it does

- Reads mail from `~/mail` by default (mbsync Maildir tree) or any directory configured via `source_dir` in `zkm-config.yaml`
- Handles both Maildir format (files in `cur/`/`new/` without `.eml` extension) and flat `.eml` dumps
- Writes one `mail/messages/<date>_<slug>.md` per message with frontmatter per the [zkm messaging-spec](https://github.com/zommuter/zkm/blob/main/docs/messaging-spec.md)
- Groups messages into threads via RFC 5322 `References` chains — one `mail/threads/<thread_id>.md` per thread, regenerated on every run
- Collapses full tail-quote blocks into a single `> *[Quoted from: …]*` link — English and German attribution lines ("On … wrote:" / "Am … schrieb:") are detected and removed; interleaved replies and low-similarity quotes are left untouched (configurable via `quote_strip`)
- Stores stripped originals in `originals/mail/` (attachment payloads detached, stubs added) — raw bytes reproducible via `git cat-file blob <source_blob>`; body text is always preserved verbatim in the original for round-trip fidelity
- Attachments go into a content-addressed store at `originals/mail/_objects/` (sha256-named, deduplicated) and are symlinked from `inbox/` for other zkm plugins to pick up
- Deduplicates by `Message-ID` — re-running is safe and idempotent
- Skips `Trash`, `Junk`, `Spam`, `Drafts`, and similar noise folders by default

## Setup

### 1. Fetch mail with mbsync

Example `.mbsyncrc`:

```
IMAPAccount personal
Host imap.example.com
User you@example.com
PassCmd "pass email/personal"
SSLType IMAPS

IMAPStore personal-remote
Account personal

MaildirStore personal-local
Path ~/mail/personal/
Inbox ~/mail/personal/INBOX

Channel personal
Far :personal-remote:
Near :personal-local:
Patterns INBOX Sent
Create Near
SyncState *
```

```bash
mbsync personal
```

### 2. Install the plugin

Clone this repo inside your zkm `plugins/` directory:

```bash
git clone https://github.com/zommuter/zkm-eml.git plugins/zkm-eml
```

The plugin is auto-discovered from that location — no `zkm plugin add` needed.

### 3. Configure (optional)

Without any configuration the plugin runs against `~/mail` using built-in defaults. To override, add a `plugins.eml:` section to `$ZKM_STORE/zkm-config.yaml`:

```yaml
plugins:
  eml:
    # Optional — defaults to ~/mail
    source_dir: ~/mail

    # Optional — list of folder name patterns to skip (case-insensitive, any path segment)
    # folders_exclude: [Trash, Junk, Spam, Drafts]

    # Optional — set false to skip stripped-original storage and attachment extraction
    # keep_originals: true
    # attachment_inbox: true

    # Optional — set false to keep raw quoted text (no tail-quote collapsing)
    # quote_strip: true

    # Optional — force ASCII-only slugs (strip accents/umlauts)
    # slug_ascii: false

    # Optional — what to do when a source mail is deleted between runs (git sources only)
    # deleted_policy: keep  # keep | log | purge | archive
```

### 4. Convert

```bash
zkm convert eml
```

## Store layout

Messages and threads are sharded by year and month:

```
$ZKM_STORE/
├── mail/
│   ├── messages/2026/04/2026-04-13-1230-a1b2c3d4-invoice-from-acme.md  # one per message
│   ├── threads/2026/04/2026-04-13-a1b2c3d4-invoice-thread.md            # one per thread
│   └── _objects/
│       ├── 9f/2a3b...c4d5                          # deduplicated CAS objects
│       └── de/adbeef...
├── originals/mail/2026/04/
│   ├── 2026-04-13-1230-a1b2c3d4-invoice-from-acme.eml    # stripped (no attachment payloads)
│   └── 2026-04-13-1230-a1b2c3d4-invoice-from-acme/
│       ├── invoice.pdf                             # symlink → mail/_objects/9f/2a3b...
│       └── acme-logo.png                           # symlink → mail/_objects/de/adbeef...
└── inbox/mail/2026/04/
    ├── invoice.pdf                                  # symlink → mail/_objects/...
    └── acme-logo.png                                # deduped — one link per unique payload
```

## Retrieving full originals

Three paths to the unstripped source, in order of robustness:

```bash
# 1. Via git blob hash (works even after the file is moved/deleted in ~/mail)
git -C ~/mail cat-file blob $(jq -r .source_blob originals/mail/2026-04-13_foo.source.json)

# 2. Via commit + relative path
git -C ~/mail show \
    "$(jq -r .source_repo_commit originals/mail/2026-04-13_foo.source.json):\
$(jq -r .source_path_rel_home originals/mail/2026-04-13_foo.source.json)"

# 3. Direct path (works if file is still in ~/mail)
cat "$(jq -r .source_path originals/mail/2026-04-13_foo.source.json)"
```

## Re-processing

After upgrading the plugin (e.g. to v0.7 which adds quote stripping), re-derive all existing markdown from stored originals:

```bash
zkm convert eml --reprocess
```

## Auto-trigger from mbsync

After mbsync syncs the mail repo, a git post-commit hook can run `zkm convert eml && zkm index` automatically — no manual invocation needed.

**Prerequisites:** `zkm` must be on PATH. Install once:

```bash
uv tool install --editable path/to/zkm
uv tool update-shell   # ensures ~/.local/bin is on PATH
```

**Install the hook** (default target: `~/mail`):

```bash
cd plugins/zkm-eml
make install-hook                        # symlinks hooks/post-commit → ~/mail/.git/hooks/post-commit
make install-hook MAIL_REPO=~/work-mail  # custom mail repo
```

**Monitor logs:**

```bash
journalctl -t zkm-eml-hook -n 50
```

**Remove:**

```bash
make uninstall-hook
```

See `docs/install.md` in the zkm repo for full setup details and the `ZKM_BYPASS_DIRTY_CHECK` bypass for development runs.

## Development

```bash
cd plugins/zkm-eml
uv sync --extra dev
uv run pytest
uv run ruff check src/ tests/ convert.py
```

## License

MIT — see [LICENSE](LICENSE)
