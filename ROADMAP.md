# Roadmap <!-- fables-turn roadmap v1 -->

Executor-facing task spec. Each item is sized for ONE Sonnet session. Items are
the single source of truth — TODO.md carries only a summary line. Executors tick
checkboxes; only the reviewer adds, removes, or re-scopes items.

Ledger context (Option B, 2026-06-30): this repo's `TODO.md` is the work ledger —
M1/M4 moved in from central `~/src/zkm/TODO.md`. Cross-cutting items needing core
(`zkm rm`/`zkm gc`) stay central. Never edit the central TODO.md from this repo.

House rules that bind every item: hermetic tests (tmp stores, synthetic fixtures,
never real mail), `uv run ruff check` clean on touched files, conventional commits,
bump-and-tag if you change the pyproject version. The plugin-done gate (HEAD pushed
to upstream) is checked by the orchestrator, not by you.

## Items

## Deferred (gated — do not start)

- M1 remainder: evidence-backed classification phase — cross-sender CAS-recurrence
  signal, alt-text/tracking-domain heuristics, `decoration_fanout` default flip.
  **Gate**: the first census distribution from a real mailbox (census mode shipped
  under id:ff0f, 2026-06-16; `decoration_fanout` defaults TRUE so no behaviour has
  flipped). Until that distribution exists, threshold/default work is speculative
  ("observe before preventing"). Twin of TODO.md M1 remainder. <!-- id:6755 -->

- M4: drafts mode — "follow draft updates" on Message-ID/content change across saves.
  Explicitly YAGNI (central ledger M4). **Gate**: a concrete user need to ingest the
  Drafts folder at all (it is excluded by default via `folders_exclude`); until a
  draft-derived note is actually missed in search, any work here is speculative.
  Do not write tests or code; if the gate fires, hold a scoping meeting first
  (draft churn breaks the Message-ID dedup invariant — each save may mint a new ID,
  needs a supersede/tombstone design). <!-- id:6186 -->
