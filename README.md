# zkm-eml

[zkm](https://github.com/Zommuter/zkm) plugin that converts `.eml` files to markdown in the knowledge store with full thread modeling.

## What it does

- Reads `.eml` files from a directory (typically an mbsync Maildir)
- Writes one `mail/messages/<date>_<slug>.md` per message with frontmatter per the [zkm messaging-spec](https://github.com/Zommuter/zkm/blob/main/docs/messaging-spec.md)
- Groups messages into threads via RFC 5322 `References` chains — one `mail/threads/<thread_id>.md` per thread, regenerated on every run
- Stores raw `.eml` originals in `originals/mail/` so future algorithm improvements can re-derive markdown via `zkm convert zkm-eml --reprocess`
- Deduplicates by `Message-ID` — re-running is safe

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

```bash
zkm plugin add ~/src/zkm-eml
# or from GitHub once published:
# zkm plugin add https://github.com/Zommuter/zkm-eml.git
```

### 3. Configure

In `$ZKM_STORE/.env`:

```
EML_SOURCE_DIR=~/mail/personal
EML_KEEP_ORIGINALS=true
EML_OWNER_ADDRESSES=you@example.com,you@work.example.com
```

### 4. Convert

```bash
zkm convert zkm-eml
```

## Re-processing

When the plugin algorithm improves (e.g. quote stripping is added in v0.2), re-derive all existing markdown from stored originals:

```bash
zkm convert zkm-eml --reprocess-all
```

## Development

```bash
cd ~/src/zkm-eml
uv sync --extra dev
uv run pytest
uv run ruff check src/ tests/ convert.py
```
