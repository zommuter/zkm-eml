# Human review queue <!-- budget: 15 min -->

Judgment calls encoded in red tests — confirm or correct the interpretation.
Max ~10 open boxes; the reviewer prunes resolved ones each review turn.

- [ ] tests/test_reprocess.py::test_reprocess_preserves_foreign_frontmatter_keys
  (roadmap:9255) — `reprocess()` currently rewrites frontmatter from scratch, nuking
  amender keys (`entities`, `source_deleted`). The test encodes: **carry over every
  key the writer does not own**. Alternative reading: "reprocess invalidates
  enrichment; re-run NER afterwards" — rejected because the amendment contract makes
  frontmatter multi-producer and NER re-runs are expensive.
  → owner 2026-06-13 CONFIRMED: carry over every key the writer does not own.
  Multi-producer frontmatter is the right model — reprocess must not nuke
  amender keys (`entities`, `source_deleted`). Sounds sensible.

- [ ] tests/test_threading.py::test_thread_id_falls_back_to_in_reply_to (roadmap:f583)
  — interpretation: `in_reply_to` is a *fallback root* when References is empty. This
  only repairs one-hop breaks (reply-to-root); a deeper chain whose client strips
  References still splits. Also: In-Reply-To-only messages **already imported** keep
  their old singleton thread_id until reprocessed — accepted drift. Correct if you
  want full repair via parent's stored thread_id lookup instead (bigger change).

- [ ] tests/test_naming.py::test_slugify_ascii_fold_when_env_set (roadmap:e14b) — the
  test exercises the retired `EML_SLUG_ASCII` env mechanism. Interpretation: rewrite
  to the parameter contract (`slugify(s, slug_ascii=True)`), keeping NFKD-fold
  coverage ("Grüße" → "grue..."). Alternative: delete the test (coverage loss) or
  reintroduce an env override (contradicts "replace means delete").

- [ ] tests/test_reprocess.py::test_reprocess_detaches_data_uris (roadmap:9bf0) — fix
  is specced on the **reprocess path** (re-apply detach), NOT by stripping data-URIs
  out of the stored original .eml — the original's body stays verbatim per the
  round-trip guarantee (ARCHITECTURE.md §6/§7). Confirm that boundary.

- [ ] tests/test_docs.py::test_readme_no_retired_env_config (roadmap:d206) — strict
  reading: NO `EML_*` env var may appear anywhere in README, even in a historical
  note. If you want a "migrating from ≤v0.9" appendix mentioning the old names,
  loosen the test to scan only fenced config examples.
