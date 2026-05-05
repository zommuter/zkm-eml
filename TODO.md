# TODO

## Current
- [ ] Decoration vs inline-photo classification: heuristics to distinguish logos/banners from informational inline images (size, repeated cid across senders, alt-text, tracking domains). Currently all attachments treated uniformly.
- [ ] Per-store YAML/JSON config shared by zkm core and all plugins — replaces long comma-separated env vars
- [ ] Deleted-mail policy: detect removals from ~/mail between runs; options: always-keep (default), purge, archive-only
- [ ] Drafts: optional "follow draft updates" mode (Message-ID/content changes on each save) — YAGNI for now
- [ ] `_objects` GC: walk stripped .eml stubs and remove unreferenced CAS objects (analogous to `git gc`)
- [ ] v0.3 quote stripping: detect and collapse full-quote blocks; trigger via --reprocess. Design sketch in CLAUDE.md.
- [ ] SHA-256 git repo support: auto-detect via `git rev-parse --show-object-format`; fall back to subprocess for source_blob
- [ ] Attachment MIME type refinement: use python-magic for more accurate typing of synthesized filenames
- [ ] Update installed plugin copy in ~/src/zkm/plugins/zkm-zkm-eml to v0.2

## Done
- [x] v0.1 EML to markdown with thread modeling — covered by tests (test_convert.py, test_parse.py, test_threading.py) on 2026-05-05
- [x] v0.2 default ~/mail, Maildir iteration, CAS attachment extraction, inbox symlinks — covered by tests (37 passing) on 2026-05-05
