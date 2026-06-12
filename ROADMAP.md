# Roadmap <!-- fables-turn roadmap v1 -->

Executor-facing task spec. Each item is sized for ONE Sonnet session. Items are
the single source of truth — TODO.md carries only a summary line. Executors tick
checkboxes; only the reviewer adds, removes, or re-scopes items.

Central-ledger context: zkm-eml items in `~/src/zkm/TODO.md` use the `M` prefix
(general) and `A` prefix (mbsync auto-trigger). M1 and M4 are mirrored below.
Never edit the central TODO.md from this repo.

House rules that bind every item: hermetic tests (tmp stores, synthetic fixtures,
never real mail), `uv run ruff check` clean on touched files, conventional commits,
bump-and-tag if you change the pyproject version. The plugin-done gate (HEAD pushed
to upstream) is checked by the orchestrator, not by you.

## Items

- [x] Sync plugin version metadata and guard against drift [ROUTINE] <!-- id:7674 -->
  - **Acceptance**: `plugin.yaml` (repo root), `src/zkm_eml/plugin.yaml`, and
    `frontmatter.PLUGIN_VERSION` all report the same version as `pyproject.toml`
    (currently 0.14.0 vs 0.13.0 drift in both plugin.yaml copies). Recurrence is
    prevented by a test, so the next version bump fails CI if any copy is missed.
  - **Tests**: `tests/test_version_sync.py::test_root_plugin_yaml_version_matches_pyproject`,
    `::test_packaged_plugin_yaml_version_matches_pyproject` (each `# roadmap:7674`)
    (currently RED); `::test_frontmatter_plugin_version_matches_pyproject` is already
    green (PLUGIN_VERSION happens to be in sync) and serves as the recurrence guard.
  - **Done-check**: `uv run pytest tests/test_version_sync.py`
  - **Context**: `pyproject.toml` + git tag are canonical (house rule: no version
    literals duplicated without a guard). Simplest fix: edit both plugin.yaml
    `version:` fields to match pyproject. You MAY instead make
    `frontmatter.PLUGIN_VERSION` dynamic via `importlib.metadata.version("zkm-eml")`
    — the test accepts either, but keep plugin.yaml literal (core reads it without
    importing the package). This is metadata-only — do NOT bump the pyproject
    version for this item.

- [x] Make the test suite green from a fresh clone [ROUTINE] <!-- id:e14b -->
  - **Acceptance**: `uv run pytest` passes in a pristine worktree. Two tests
    currently fail on fresh checkouts: (a) `test_tmp_always_skipped` writes into
    `tests/fixtures/maildir/account1/INBOX/tmp/` which git cannot track while empty
    — create the directory in the test (`mkdir(parents=True, exist_ok=True)`)
    before writing; (b) `test_slugify_ascii_fold_when_env_set` tests the retired
    `EML_SLUG_ASCII` env mechanism (removed in the M2 config migration) — rewrite
    it to the current parameter contract `slugify(s, slug_ascii=True)` (no
    monkeypatch, no importlib.reload) and rename it accordingly.
  - **Tests**: `tests/test_source.py::test_tmp_always_skipped`,
    `tests/test_naming.py::test_slugify_ascii_fold_when_env_set`
    (both pre-existing, tagged `# roadmap:e14b`) (currently RED)
  - **Done-check**: `uv run pytest` (entire suite green)
  - **Context**: `src/zkm_eml/naming.py` already implements `slug_ascii=` and
    `convert.py` threads the `slug_ascii` config key — only the tests are stale.
    See REVIEW_ME.md for the rewrite-vs-delete judgment call.

- [ ] Detach data-URI images on --reprocess [ROUTINE] <!-- id:9bf0 -->
  - **Acceptance**: `reprocess()` applies the same data-URI detach as `convert()`:
    after `zkm convert eml --reprocess`, no `data:` URI appears in any rendered .md
    body, and the detached payloads exist as CAS objects. (Today reprocess re-parses
    the stored original — whose HTML body keeps the URIs verbatim by round-trip
    design — and leaks them back into the markdown.)
  - **Tests**: `tests/test_reprocess.py::test_reprocess_detaches_data_uris`
    (`# roadmap:9bf0`) (currently RED)
  - **Done-check**: `uv run pytest tests/test_reprocess.py -k data_uris`
  - **Context**: factor the detach block in `convert()` (src/zkm_eml/convert.py,
    "Detach inline data-URI images" — `render.detach_html_data_uris`) into a helper
    used by both paths. CAS writes (`zkm.cas.write_object`) are idempotent, so
    re-writing the same object on reprocess is fine. Do not modify the stored
    original — it intentionally keeps body text verbatim (ARCHITECTURE.md §6, §7).

- [ ] Preserve foreign frontmatter keys and attachments[] on --reprocess [ROUTINE] <!-- id:9255 -->
  - **Acceptance**: reprocessing never loses (a) keys written by other producers
    (amenders: `entities`, `source_deleted`, …) or (b) the `attachments:` list that
    only the convert path can compute. Keys owned by the writer (body-derived:
    `subject`, `participants`, `thread`, `signature_block`, …) are refreshed as today.
  - **Tests**: `tests/test_reprocess.py::test_reprocess_preserves_foreign_frontmatter_keys`,
    `::test_reprocess_preserves_attachments_meta` (each `# roadmap:9255`) (currently RED)
  - **Done-check**: `uv run pytest tests/test_reprocess.py -k preserves`
  - **Context**: `write_message_md` (src/zkm_eml/frontmatter.py) rebuilds the meta
    dict from scratch. Preferred fix per ARCHITECTURE.md §14: in `reprocess()`, load
    the existing post and carry over every key not produced by `write_message_md`
    (plus `attachments`), e.g. via an `extra_meta=` parameter on `write_message_md`
    with owned-keys precedence. The store-wide amendment contract makes frontmatter
    multi-producer — see core `docs/` amendment notes. Judgment call recorded in
    REVIEW_ME.md.

- [x] Fall back to In-Reply-To for thread identity when References is empty [ROUTINE] <!-- id:f583 -->
  - **Acceptance**: a reply that carries `In-Reply-To` but no `References` header
    (common for some webmail/mobile clients) lands in its parent's thread instead of
    starting a singleton thread, both at the unit level (`thread_id_for`) and through
    `convert()` (same `thread_id` frontmatter, shared thread index file).
  - **Tests**: `tests/test_threading.py::test_thread_id_falls_back_to_in_reply_to`,
    `tests/test_threading.py::test_references_still_win_over_in_reply_to`,
    `tests/test_convert.py::test_convert_threads_reply_with_only_in_reply_to`
    (each `# roadmap:f583`) (currently RED)
  - **Done-check**: `uv run pytest -k in_reply_to`
  - **Context**: `thread_id_for(message_id, references)` in src/zkm_eml/threading.py
    gains a keyword arg `in_reply_to: str | None = None`; root resolution becomes
    `references[0] or in_reply_to or message_id`. Update both call sites in
    src/zkm_eml/convert.py (convert + reprocess). This only repairs one-hop breaks
    (parent must be the thread root); deeper broken chains are out of scope — see
    REVIEW_ME.md. thread_id stability for already-imported mail with References is
    unaffected (references[0] still wins).

- [ ] Refresh README to the current config contract [ROUTINE] <!-- id:d206 -->
  - **Acceptance**: README.md no longer documents the retired `.env` / `EML_*`
    environment mechanism; it documents the `zkm-config.yaml` plugin-config keys
    (`source_dir`, `folders_exclude`, `keep_originals`, `attachment_inbox`,
    `quote_strip`, `slug_ascii`, `deleted_policy`) and the sharded store layout
    (`mail/messages/YYYY/MM/…`). The "direction detection" claim is removed
    (`owner_addresses` is reserved, unused).
  - **Tests**: `tests/test_docs.py::test_readme_no_retired_env_config`,
    `::test_readme_documents_zkm_config` (each `# roadmap:d206`) (currently RED)
  - **Done-check**: `uv run pytest tests/test_docs.py`
  - **Context**: CLAUDE.md "Config" section is the accurate reference; plugin.yaml
    `config:` block lists defaults/descriptions. Keep the mbsync setup, retrieval,
    reprocess, and hook sections — only the config mechanism and layout examples are
    stale.

- [ ] M1: decoration vs inline-photo attachment classification [HARD — strong model] <!-- id:ff0f -->
  - **Why HARD**: heuristic design with unknown base rates — signals (payload size,
    same-CAS-object recurrence across senders, cid-referenced-but-tiny, alt-text,
    tracking-pixel dimensions) need evidence from a real mailbox before thresholds
    are set ("observe before preventing" house rule). Misclassification costs are
    asymmetric (hiding a real photo from inbox fan-out is worse than fanning out a
    logo). Mirrors central ledger item **M1** (no central id token).
  - **Acceptance** (when picked up): each attachment gains a
    `classification: decoration|content|unknown` field in frontmatter + sidecar;
    inbox fan-out policy for `decoration` is config-gated; a logging/census mode
    ships FIRST to gather distribution evidence before any default flips.

## Deferred (gated — do not start)

- M4: drafts mode — "follow draft updates" on Message-ID/content change across saves.
  Explicitly YAGNI (central ledger M4). **Gate**: a concrete user need to ingest the
  Drafts folder at all (it is excluded by default via `folders_exclude`); until a
  draft-derived note is actually missed in search, any work here is speculative.
  Do not write tests or code; if the gate fires, hold a scoping meeting first
  (draft churn breaks the Message-ID dedup invariant — each save may mint a new ID,
  needs a supersede/tombstone design). <!-- id:6186 -->
