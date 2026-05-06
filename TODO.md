# TODO

## Current
- [ ] Decoration vs inline-photo classification: heuristics to distinguish logos/banners from informational inline images (size, repeated cid across senders, alt-text, tracking domains). Currently all attachments treated uniformly.
- [ ] Per-store YAML/JSON config shared by zkm core and all plugins — replaces long comma-separated env vars
- [ ] Deleted-mail policy: detect removals from ~/mail between runs; options: always-keep (default), purge, archive-only
- [ ] Drafts: optional "follow draft updates" mode (Message-ID/content changes on each save) — YAGNI for now
- [ ] `_objects` GC: walk `mail/_objects/<aa>/<rest>.json` producer lists, prune CAS objects and sidecars whose producers all reference deleted messages
- [ ] v0.5 quote stripping: detect and collapse full-quote blocks; trigger via --reprocess. Design sketch in CLAUDE.md.
- [ ] SHA-256 git repo support: auto-detect via `git rev-parse --show-object-format`; fall back to subprocess for source_blob
- [ ] Attachment MIME type refinement: use python-magic for more accurate typing of synthesized filenames
- [ ] Update installed plugin copy in ~/src/zkm/plugins/zkm-zkm-eml to v0.6 (was v0.5)
- [ ] CLAUDE.md: update architecture diagram and "Filename convention" section for v0.4 layout; document EML_LIMIT_RECENT, EML_SLUG_ASCII, and v0.6 sidecar files
- [ ] Run --reprocess on ~/knowledge to rewrite all existing md files with role-tagged participants + mojibake fixes + attachment sidecars (v0.5→v0.6 schema change)

## Done
- [x] v0.1 EML to markdown with thread modeling — covered by tests (test_convert.py, test_parse.py, test_threading.py) on 2026-05-05
- [x] v0.2 default ~/mail, Maildir iteration, CAS attachment extraction, inbox symlinks — covered by tests (37 passing) on 2026-05-05
- [x] ESC/Ctrl+C cancellation responsiveness: replaced O(T×N) thread index regen in `finally` with O(T) in-memory write via `build_thread_membership` + `write_thread_index` — covered by tests (38 passing) on 2026-05-05
- [x] Fixed-width progress bar layout (zkm core): added explicit `bar_format=` to tqdm call to prevent horizontal jitter — covered by tests (23 zkm tests passing) on 2026-05-05
- [x] v0.3 sharded paths + HHMM filenames + smart empty-subject slug: mail/messages/<aa>/<rest>/YYYY-MM-DD-HHMM-slug.md, same for threads and originals; from-<localpart> fallback; stem shared between .md and .eml to eliminate drift — covered by tests (49 passing) on 2026-05-05
- [x] v0.4 date-sharded layout: mail/messages/YYYY/MM/YYYY-MM-DD-HHMM-thread8-slug.md; threads/YYYY/MM/YYYY-MM-DD-thread8-slug.md (first-message date); mail/_objects/ CAS (out of originals/); inbox/mail/YYYY/MM/ symlinks; EML_LIMIT_RECENT for fast test runs; knowledge store rolled back and re-seeded with 10 messages — covered by tests (54 passing) on 2026-05-05
- [x] Inbox origin sidecar: one-canonical-symlink-per-CAS dedup + <file>.origin.json listing all producers (plugin, message path, sha256); build_inbox_canonical_index pre-scans existing symlinks; atomic read-merge-write — covered by tests (57/57 passing) on 2026-05-05
- [x] v0.6 mojibake fix: RFC 2047 header decode (subject, display names, attachment filenames), body charset cascade (utf-8 → cp1252 → latin-1), NFC normalize filenames, EML_SLUG_ASCII env; per-message-attachment sidecar (<stem>/<filename>.json) and per-CAS sidecar (mail/_objects/<aa>/<rest>.json) — covered by tests (73/73 passing) on 2026-05-06
