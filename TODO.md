# TODO

## Current
- [ ] Decoration vs inline-photo classification: heuristics to distinguish logos/banners from informational inline images (size, repeated cid across senders, alt-text, tracking domains). Currently all attachments treated uniformly.
- [ ] Per-store YAML/JSON config shared by zkm core and all plugins — replaces long comma-separated env vars
- [ ] Deleted-mail policy: detect removals from ~/mail between runs; options: always-keep (default), purge, archive-only
- [ ] Drafts: optional "follow draft updates" mode (Message-ID/content changes on each save) — YAGNI for now
- [ ] `_objects` GC: walk stripped .eml stubs and remove unreferenced CAS objects (analogous to `git gc`)
- [ ] v0.4 quote stripping: detect and collapse full-quote blocks; trigger via --reprocess. Design sketch in CLAUDE.md.
- [ ] SHA-256 git repo support: auto-detect via `git rev-parse --show-object-format`; fall back to subprocess for source_blob
- [ ] Attachment MIME type refinement: use python-magic for more accurate typing of synthesized filenames
- [ ] Update installed plugin copy in ~/src/zkm/plugins/zkm-zkm-eml to v0.3
- [ ] Migration: wipe mail/messages/, mail/threads/, flat originals/mail/*.eml and reconvert existing store (v0.2 layout is incompatible with v0.3 sharded layout)

## Done
- [x] v0.1 EML to markdown with thread modeling — covered by tests (test_convert.py, test_parse.py, test_threading.py) on 2026-05-05
- [x] v0.2 default ~/mail, Maildir iteration, CAS attachment extraction, inbox symlinks — covered by tests (37 passing) on 2026-05-05
- [x] ESC/Ctrl+C cancellation responsiveness: replaced O(T×N) thread index regen in `finally` with O(T) in-memory write via `build_thread_membership` + `write_thread_index` — covered by tests (38 passing) on 2026-05-05
- [x] Fixed-width progress bar layout (zkm core): added explicit `bar_format=` to tqdm call to prevent horizontal jitter — covered by tests (23 zkm tests passing) on 2026-05-05
- [x] v0.3 sharded paths + HHMM filenames + smart empty-subject slug: mail/messages/<aa>/<rest>/YYYY-MM-DD-HHMM-slug.md, same for threads and originals; from-<localpart> fallback; stem shared between .md and .eml to eliminate drift — covered by tests (49 passing) on 2026-05-05
