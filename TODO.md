# zkm-eml TODO

This is the work ledger for zkm-eml (Option B, decided 2026-06-30 — `~/src/zkm/docs/meeting-notes/2026-06-30-1004-per-plugin-todo-topology-revisited.md`). Executor queue: `ROADMAP.md` (relay-managed). Cross-cutting items (e.g. the spam/source-deleted removal mechanics, which need core `zkm rm`/`zkm gc`) stay in central `~/src/zkm/TODO.md`. <!-- lint-ok: file-purpose preamble -->

## Current

- [ ] Relay: 0 open ROADMAP items; 1 deferred/gated (id:6186); 6 [ROUTINE] + 1 [HARD] (id:ff0f) closed <!-- id:e662 -->
- [ ] **M1.** Decoration vs inline-photo classification — heuristics to distinguish logos/banners from informational inline images (size, repeated cid across senders, alt-text, tracking domains). Currently all attachments treated uniformly. <!-- id:6755 -->
- [ ] **M4.** Drafts — optional "follow draft updates" mode (Message-ID/content changes on each save). YAGNI for now. <!-- id:2527 -->
