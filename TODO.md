# zkm-eml TODO

This is the work ledger for zkm-eml (Option B, decided 2026-06-30 — `~/src/zkm/docs/meeting-notes/2026-06-30-1004-per-plugin-todo-topology-revisited.md`). Executor queue: `ROADMAP.md` (relay-managed). Cross-cutting items (e.g. the spam/source-deleted removal mechanics, which need core `zkm rm`/`zkm gc`) stay in central `~/src/zkm/TODO.md`. <!-- lint-ok: file-purpose preamble -->

## Current

- [ ] [ROUTINE] Relay: 0 open ROADMAP items; 2 deferred/gated (id:6186, id:6755); 7 + 1 [HARD] (id:ff0f) closed <!-- id:e662 -->
- [ ] **M1 remainder.** Decoration classification, evidence-backed phase — census mode shipped (ROADMAP id:ff0f closed: `classification: decoration|content|unknown` in frontmatter+sidecars, `decoration_fanout` gate default-TRUE). Remaining: cross-sender CAS-recurrence signal (same logo object from N senders), alt-text/tracking-domain heuristics, and any flip of the `decoration_fanout` default. **Gate**: run the census on a real mailbox and read the first distribution before touching thresholds or the default ("observe before preventing"). <!-- id:6755 -->
- [ ] **M4.** Drafts — optional "follow draft updates" mode (Message-ID/content changes on each save). YAGNI for now; gated in ROADMAP (same id). <!-- id:6186 -->
